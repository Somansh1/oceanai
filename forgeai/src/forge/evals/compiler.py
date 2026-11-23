"""Eval compiler: builds the test set FROM the documents themselves.

Stratified sampling across docs and chunk positions; every answerable case
carries expected chunk IDs + atomic expected facts; canaries are traps for
hallucination; rephrase pairs measure stability. Deduped by token overlap.
"""
from __future__ import annotations

import random
import re

from pydantic import BaseModel, Field

from ..core import Chunk
from ..evaltypes import CaseKind, EvalCase
from ..llm import Harness
from ..retrieve import HybridIndex
from ..retrieve.bm25 import tokenize
from ..spec import RequirementsDoc


class AnswerableDraft(BaseModel):
    question: str
    expected_facts: list[str] = Field(default_factory=list)
    archetype: str = "lookup"
    difficulty: str = "medium"


class RefusalDraft(BaseModel):
    question: str
    mode: str = "refusal"
    why_refusal_expected: str = ""


class EdgeDraft(BaseModel):
    question: str
    mode: str = "cross_doc"
    expected_facts: list[str] = Field(default_factory=list)
    expected_value: float | None = None
    derivation: str | None = None


class RephraseDraft(BaseModel):
    rephrased_question: str


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class _Dedup:
    def __init__(self, threshold: float = 0.6):
        self.seen: list[str] = []
        self.threshold = threshold

    def accept(self, question: str) -> bool:
        if any(_jaccard(question, s) >= self.threshold for s in self.seen):
            return False
        self.seen.append(question)
        return True


def _stratified_chunks(index: HybridIndex, n: int, rng: random.Random) -> list[Chunk]:
    ids = index.all_chunk_ids()
    by_doc: dict[str, list[str]] = {}
    for cid in ids:
        by_doc.setdefault(cid.split("#")[0], []).append(cid)
    for doc in by_doc:
        rng.shuffle(by_doc[doc])
    picked: list[str] = []
    doc_keys = list(by_doc)
    while len(picked) < n and any(by_doc.values()):
        for doc in doc_keys:
            if by_doc[doc] and len(picked) < n:
                picked.append(by_doc[doc].pop())
    return [index.get_chunk(c) for c in picked if index.get_chunk(c)]


def compile_evalset(harness: Harness, index: HybridIndex, req: RequirementsDoc,
                    n_answerable: int = 14, n_refusal: int = 4, n_canary: int = 3,
                    n_edge: int = 6, seed: int = 13) -> list[EvalCase]:
    rng = random.Random(seed)
    dedup = _Dedup()
    cases: list[EvalCase] = []

    def next_id() -> str:
        return f"q{len(cases) + 1:02d}"

    # --- answerable (stratified; small corpora get multiple archetypes per chunk) ---
    chunks = _stratified_chunks(index, max(n_answerable, n_edge), rng)
    numeric_ready = [c for c in chunks if len(re.findall(r"\d", c.text)) >= 6]
    # negation deliberately excluded: a correct negation answer cannot state
    # the affirmative facts coverage scoring demands — wrong-shaped, not wrong
    # agent (caught live on "What is NOT a requirement for requesting annual leave")
    archetypes = ["lookup", "comparison", "aggregation", "lookup"]
    quota = max(2, -(-n_answerable // max(1, len(chunks))))
    n_ans = 0
    for chunk in chunks:
        for j in range(quota):
            if n_ans >= n_answerable:
                break
            prompt, sha = harness.prompts.render(
                "05_eval_answerable", chunk_id=chunk.id, chunk_text=chunk.text[:2200])
            prompt += f"\n\nRequired archetype this time: {archetypes[j % len(archetypes)]}"
            d = harness.ask_json(AnswerableDraft, prompt, stage="eval_answerable", prompt_sha=sha)
            if not d.question or not d.expected_facts or not dedup.accept(d.question):
                continue
            # SELF-DISTRUST: every expected fact must survive its own grounding
            # chunk, or it dies here. Facts that contradict or float free of the
            # source are eval-set poison (caught live: compiler once inverted a
            # medical-certificate rule and shipped date-strings as "facts").
            verified = []
            for f in d.expected_facts:
                fp, fs = harness.prompts.render("08_fact_match", fact=f,
                                                excerpt=chunk.text[:3000])
                if harness.yes_no(fp, stage="eval_fact_verify", prompt_sha=fs):
                    verified.append(f)
            if not verified:
                continue
            cases.append(EvalCase(id=next_id(), kind=CaseKind.ANSWERABLE, question=d.question,
                                  expected_chunk_ids=[chunk.id], expected_facts=verified,
                                  generation_provenance=chunk.id, notes=f"{d.archetype}/{d.difficulty}"))
            n_ans += 1

    # --- edge: numeric from number-dense chunks ---
    used = {c.generation_provenance for c in cases if c.generation_provenance}
    for chunk in [c for c in numeric_ready if c.id not in used][: max(1, n_edge // 3)]:
        prompt, sha = harness.prompts.render(
            "07_eval_edge", chunk_a_id=chunk.id, chunk_a_text=chunk.text[:2200],
            chunk_b_id="(none)", chunk_b_text="(none)")
        d = harness.ask_json(EdgeDraft, prompt, stage="eval_edge", prompt_sha=sha)
        if not d.question or d.expected_value is None or not dedup.accept(d.question):
            continue
        cases.append(EvalCase(id=next_id(), kind=CaseKind.NUMERIC, question=d.question,
                              expected_chunk_ids=[chunk.id], expected_facts=d.expected_facts,
                              expected_value=d.expected_value, generation_provenance=chunk.id,
                              notes=d.derivation))

    # --- edge: cross-doc ---
    remaining = [c for c in chunks if c.id not in used and c not in numeric_ready]
    for i in range(min(max(1, n_edge // 3), len(remaining) // 2)):
        a = remaining[i * 2]
        b = remaining[i * 2 + 1]
        prompt, sha = harness.prompts.render(
            "07_eval_edge", chunk_a_id=a.id, chunk_a_text=a.text[:1500],
            chunk_b_id=b.id, chunk_b_text=b.text[:1500])
        d = harness.ask_json(EdgeDraft, prompt, stage="eval_edge", prompt_sha=sha)
        if not d.question or not dedup.accept(d.question):
            continue
        ids = [a.id] + ([b.id] if b.provenance.doc_id != a.provenance.doc_id else [])
        cases.append(EvalCase(id=next_id(), kind=CaseKind.CROSS_DOC, question=d.question,
                              expected_chunk_ids=ids or [a.id, b.id],
                              expected_facts=d.expected_facts,
                              generation_provenance=f"{a.id}+{b.id}",
                              notes="cross-doc" if len(ids) > 1 else "same-doc combine (small corpus)"))

    # --- edge: ambiguous ---
    amb_pool = remaining[2:]
    for chunk in amb_pool[: max(1, n_edge // 3)]:
        prompt, sha = harness.prompts.render(
            "07_eval_edge", chunk_a_id=chunk.id, chunk_a_text=chunk.text[:1500],
            chunk_b_id="(none)", chunk_b_text="(none)")
        d = harness.ask_json(EdgeDraft, prompt, stage="eval_edge", prompt_sha=sha,
                             system="You generate AMBIGUOUS questions: deliberately vague "
                                    "phrasing where the agent must state its reading or answer "
                                    "cautiously. mode must be 'ambiguous'.")
        if not d.question or not dedup.accept(d.question):
            continue
        cases.append(EvalCase(id=next_id(), kind=CaseKind.AMBIGUOUS, question=d.question,
                              expected_chunk_ids=[chunk.id], expected_facts=d.expected_facts,
                              generation_provenance=chunk.id, notes="ambiguous phrasing"))

    # --- refusal + canaries ---
    covered = "; ".join(req.must_answer_topics[:12]) or "(see vocabulary)"
    vocab = "; ".join(
        h for cid in index.all_chunk_ids()[:12]
        for h in re.findall(r"^#{1,3}\s+(.+)$", index.get_chunk(cid).text or "", flags=re.M)
    )[:800]
    for mode, count in (("refusal", n_refusal), ("canary", n_canary)):
        got, attempts = 0, 0
        while got < count and attempts < count * 3:
            attempts += 1
            prompt, sha = harness.prompts.render(
                "06_eval_refusal", scope_summary=covered, covered_topics=covered,
                vocabulary=vocab or "(vocabulary unavailable)")
            already = "\n".join(f"- {q}" for q in dedup.seen[-12:])
            prompt += (f"\n\nRequired mode this time: {mode}"
                       + (f"\n\nQuestions already in the set (do NOT duplicate their topic):\n{already}"
                          if already else ""))
            d = harness.ask_json(RefusalDraft, prompt, stage=f"eval_{mode}", prompt_sha=sha)
            if not d.question or not dedup.accept(d.question):
                continue
            # ANSWERABILITY GATE: if the corpus actually answers it, it is not a
            # refusal case (caught live: a canary landed on a topic the doc
            # covers, and a "refusal" case was fully answerable). Small corpora
            # gate over EVERY chunk — top-3 retrieval once missed the answer.
            all_ids = index.all_chunk_ids()
            if len(all_ids) <= 25:
                gate_chunks = [index.get_chunk(c) for c in all_ids]
                gate_ctx = "\n\n---\n\n".join(c.text[:1200] for c in gate_chunks if c)
            else:
                gate_hits = index.query(d.question, top_k=5)
                gate_ctx = "\n\n---\n\n".join(
                    f"{index.get_chunk(cid).text[:1200]}" for cid, _ in gate_hits
                    if index.get_chunk(cid))
            gate_prompt = (
                "Based ONLY on the context chunks below, can this question be answered "
                "from them?\n\nQuestion: " + d.question + "\n\nContext:\n" + gate_ctx +
                "\n\nAnswer with exactly one word: YES or NO.")
            if harness.yes_no(gate_prompt, stage="eval_refusal_gate"):
                continue
            cases.append(EvalCase(id=next_id(),
                                  kind=CaseKind.REFUSAL if mode == "refusal" else CaseKind.CANARY,
                                  question=d.question, expected_refusal=True,
                                  notes=d.why_refusal_expected or mode))
            got += 1

    # --- rephrase stability pairs (2 pairs) ---
    pool = [c for c in cases if c.kind == CaseKind.ANSWERABLE][:4]
    for i in range(0, min(2, len(pool))):
        base = pool[i]
        prompt, sha = harness.prompts.render("10_rephrase", question=base.question)
        d = harness.ask_json(RephraseDraft, prompt, stage="eval_rephrase", prompt_sha=sha)
        if not d.rephrased_question or not dedup.accept(d.rephrased_question):
            continue
        base.kind = CaseKind.REPHRASE_A
        pair_id = next_id()
        base.rephrase_pair = pair_id
        cases.append(EvalCase(id=pair_id, kind=CaseKind.REPHRASE_B,
                              question=d.rephrased_question,
                              expected_chunk_ids=base.expected_chunk_ids,
                              expected_facts=base.expected_facts,
                              rephrase_pair=base.id,
                              generation_provenance=f"rephrase of {base.id}"))

    # shuffle + renumber (fixing pair links across the renumber)
    rng.shuffle(cases)
    renumber = {c.id: f"q{i:02d}" for i, c in enumerate(cases, 1)}
    for c in cases:
        c.id = renumber[c.id]
    for c in cases:
        if c.rephrase_pair:
            c.rephrase_pair = renumber.get(c.rephrase_pair)
    return cases


