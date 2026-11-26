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


def _verify_facts(harness: Harness, facts: list[str], context: str) -> list[str]:
    verified = []
    for f in facts:
        fp, fs = harness.prompts.render("08_fact_match", fact=f, excerpt=context[:3000])
        if harness.yes_no(fp, stage="eval_fact_verify", prompt_sha=fs):
            verified.append(f)
    return verified


def _safe_eval_derivation(derivation: str | None) -> float | None:
    if not derivation:
        return None
    expr = derivation.strip()
    if "=" in expr:
        expr = expr.split("=")[0].strip()
    if not re.fullmatch(r"[\d\s.+\-*/()]+", expr):
        return None
    from ..tools.registry import REGISTRY
    calc = REGISTRY.get("calculator")
    if not calc:
        return None
    res = calc.run({"expression": expr})
    try:
        return float(res)
    except ValueError:
        return None


def compile_evalset(harness: Harness, index: HybridIndex, req: RequirementsDoc,
                    n_answerable: int = 12, n_refusal: int = 4, n_canary: int = 3,
                    n_edge: int = 6, min_cases: int = 20, seed: int = 13) -> list[EvalCase]:
    rng = random.Random(seed)
    dedup = _Dedup()
    cases: list[EvalCase] = []
    rephrase_sources: list[tuple[EvalCase, str]] = []  # (rephrase_b_case, orig_base_id)

    def next_id() -> str:
        return f"q{len(cases) + 1:02d}"

    all_ids = index.all_chunk_ids()
    all_chunks = [index.get_chunk(cid) for cid in all_ids if index.get_chunk(cid)]
    if not all_chunks:
        return []

    # --- answerable (stratified; small corpora get multiple distinct archetypes per chunk) ---
    chunks = _stratified_chunks(index, max(n_answerable, len(all_chunks)), rng)
    numeric_ready = [c for c in all_chunks if len(re.findall(r"\d", c.text)) >= 6]
    archetypes = ["lookup", "comparison", "aggregation", "lookup"]
    quota = max(2, -(-n_answerable // max(1, len(chunks)))) + 1
    n_ans = 0
    for j in range(quota):
        for chunk in chunks:
            if n_ans >= n_answerable:
                break
            prompt, sha = harness.prompts.render(
                "05_eval_answerable", chunk_id=chunk.id, chunk_text=chunk.text[:2200])
            already = "\n".join(f"- {q}" for q in dedup.seen[-10:])
            prompt += f"\n\nRequired archetype this time: {archetypes[j % len(archetypes)]}"
            if already:
                prompt += f"\n\nAlready generated questions (ask about a DIFFERENT fact):\n{already}"
            d = harness.ask_json(AnswerableDraft, prompt, stage="eval_answerable", prompt_sha=sha)
            if not d.question or not d.expected_facts or not dedup.accept(d.question):
                continue
            verified = _verify_facts(harness, d.expected_facts, chunk.text)
            if not verified:
                continue
            cases.append(EvalCase(id=next_id(), kind=CaseKind.ANSWERABLE, question=d.question,
                                  expected_chunk_ids=[chunk.id], expected_facts=verified,
                                  generation_provenance=chunk.id, notes=f"{d.archetype}/{d.difficulty}"))
            n_ans += 1
        if n_ans >= n_answerable:
            break

    # --- edge: numeric from number-dense chunks (prefer unused, allow reuse on small corpora) ---
    used = {c.generation_provenance for c in cases if c.generation_provenance}
    num_pool = [c for c in numeric_ready if c.id not in used] + [c for c in numeric_ready if c.id in used]
    n_num_target = max(1, n_edge // 3)
    n_num = 0
    for chunk in num_pool:
        if n_num >= n_num_target:
            break
        prompt, sha = harness.prompts.render(
            "07_eval_edge", chunk_a_id=chunk.id, chunk_a_text=chunk.text[:2200],
            chunk_b_id="(none)", chunk_b_text="(none)")
        already = "\n".join(f"- {q}" for q in dedup.seen[-8:])
        prompt += "\n\nRequired mode this time: numeric"
        if already:
            prompt += f"\n\nAvoid duplicating:\n{already}"
        d = harness.ask_json(EdgeDraft, prompt, stage="eval_edge", prompt_sha=sha)
        if not d.question or d.expected_value is None or not dedup.accept(d.question):
            continue
        derived_val = _safe_eval_derivation(d.derivation)
        expected_val = derived_val if derived_val is not None else d.expected_value
        verified = _verify_facts(harness, d.expected_facts, chunk.text) if d.expected_facts else []
        cases.append(EvalCase(id=next_id(), kind=CaseKind.NUMERIC, question=d.question,
                              expected_chunk_ids=[chunk.id], expected_facts=verified,
                              expected_value=expected_val, generation_provenance=chunk.id,
                              notes=d.derivation))
        n_num += 1

    # --- edge: cross-doc (distinct documents when >=2 docs exist, else distinct chunks) ---
    by_doc: dict[str, list[Chunk]] = {}
    for c in all_chunks:
        by_doc.setdefault(c.provenance.doc_id, []).append(c)
    doc_ids = list(by_doc)
    cross_pairs: list[tuple[Chunk, Chunk]] = []
    if len(doc_ids) >= 2:
        for i in range(max(2, n_edge // 3)):
            da = doc_ids[i % len(doc_ids)]
            db = doc_ids[(i + 1) % len(doc_ids)]
            ca = rng.choice(by_doc[da])
            cb = rng.choice(by_doc[db])
            cross_pairs.append((ca, cb))
    elif len(all_chunks) >= 2:
        for i in range(max(2, n_edge // 3)):
            ca = all_chunks[i % len(all_chunks)]
            cb = all_chunks[(i + 1) % len(all_chunks)]
            if ca.id != cb.id:
                cross_pairs.append((ca, cb))
    n_cross = 0
    for a, b in cross_pairs:
        if n_cross >= max(2, n_edge // 3):
            break
        prompt, sha = harness.prompts.render(
            "07_eval_edge", chunk_a_id=a.id, chunk_a_text=a.text[:1500],
            chunk_b_id=b.id, chunk_b_text=b.text[:1500])
        prompt += "\n\nRequired mode this time: cross_doc (must require combining facts from BOTH Chunk A and Chunk B)"
        d = harness.ask_json(EdgeDraft, prompt, stage="eval_edge", prompt_sha=sha)
        if not d.question or not dedup.accept(d.question):
            continue
        verified = _verify_facts(harness, d.expected_facts, a.text + "\n\n" + b.text) if d.expected_facts else []
        if not verified:
            continue
        ids = [a.id] + ([b.id] if b.id != a.id else [])
        cases.append(EvalCase(id=next_id(), kind=CaseKind.CROSS_DOC, question=d.question,
                              expected_chunk_ids=ids,
                              expected_facts=verified,
                              generation_provenance=f"{a.id}+{b.id}",
                              notes="cross-doc" if b.provenance.doc_id != a.provenance.doc_id else "cross-section (single-doc corpus)"))
        n_cross += 1

    # --- edge: ambiguous (draw from all chunks, never starve small corpora) ---
    amb_pool = list(all_chunks)
    rng.shuffle(amb_pool)
    n_amb_target = max(2, n_edge // 3)
    n_amb = 0
    for chunk in amb_pool:
        if n_amb >= n_amb_target:
            break
        prompt, sha = harness.prompts.render(
            "07_eval_edge", chunk_a_id=chunk.id, chunk_a_text=chunk.text[:1500],
            chunk_b_id="(none)", chunk_b_text="(none)")
        already = "\n".join(f"- {q}" for q in dedup.seen[-8:])
        prompt += "\n\nRequired mode this time: ambiguous"
        if already:
            prompt += f"\n\nAlready generated questions (use a different topic):\n{already}"
        d = harness.ask_json(EdgeDraft, prompt, stage="eval_edge", prompt_sha=sha,
                             system="You generate AMBIGUOUS questions: deliberately vague "
                                    "phrasing where the agent must state its reading or answer "
                                    "cautiously. mode must be 'ambiguous'.")
        if not d.question or not dedup.accept(d.question):
            continue
        verified = _verify_facts(harness, d.expected_facts, chunk.text) if d.expected_facts else []
        if not verified:
            continue
        cases.append(EvalCase(id=next_id(), kind=CaseKind.AMBIGUOUS, question=d.question,
                              expected_chunk_ids=[chunk.id], expected_facts=verified,
                              generation_provenance=chunk.id, notes="ambiguous phrasing"))
        n_amb += 1

    # --- refusal + canaries ---
    covered = "; ".join(req.must_answer_topics[:12]) or "(see vocabulary)"
    vocab = "; ".join(
        h for cid in all_ids[:12]
        for h in re.findall(r"^#{1,3}\s+(.+)$", (index.get_chunk(cid).text if index.get_chunk(cid) else ""), flags=re.M)
    )[:800]

    def _add_refusal_cases(mode: str, count: int) -> int:
        got, attempts = 0, 0
        while got < count and attempts < count * 4:
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
            if len(all_ids) <= 25:
                gate_chunks = [index.get_chunk(c) for c in all_ids]
                gate_ctx = "\n\n---\n\n".join(c.text[:1200] for c in gate_chunks if c)
            else:
                gate_hits = index.query(d.question, top_k=8)
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
        return got

    _add_refusal_cases("refusal", n_refusal)
    _add_refusal_cases("canary", n_canary)

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
        rb = EvalCase(id=pair_id, kind=CaseKind.REPHRASE_B,
                      question=d.rephrased_question,
                      expected_chunk_ids=base.expected_chunk_ids,
                      expected_facts=base.expected_facts,
                      rephrase_pair=base.id,
                      generation_provenance=f"rephrase of {base.id}")
        cases.append(rb)
        rephrase_sources.append((rb, base.id))

    # --- backfill to guarantee at least min_cases (default 20) ---
    refill_attempts = 0
    while len(cases) < min_cases and refill_attempts < 30:
        refill_attempts += 1
        chunk = all_chunks[refill_attempts % len(all_chunks)]
        prompt, sha = harness.prompts.render(
            "05_eval_answerable", chunk_id=chunk.id, chunk_text=chunk.text[:2200])
        already = "\n".join(f"- {q}" for q in dedup.seen[-12:])
        prompt += "\n\nRequired archetype this time: lookup"
        if already:
            prompt += f"\n\nAlready generated questions (ask a DIFFERENT question):\n{already}"
        d = harness.ask_json(AnswerableDraft, prompt, stage="eval_answerable", prompt_sha=sha)
        if d.question and d.expected_facts and dedup.accept(d.question):
            verified = _verify_facts(harness, d.expected_facts, chunk.text)
            if verified:
                cases.append(EvalCase(id=next_id(), kind=CaseKind.ANSWERABLE, question=d.question,
                                      expected_chunk_ids=[chunk.id], expected_facts=verified,
                                      generation_provenance=chunk.id, notes=f"{d.archetype}/{d.difficulty}"))
                continue
        if len(cases) < min_cases:
            _add_refusal_cases("refusal" if refill_attempts % 2 == 0 else "canary", 1)

    # shuffle + renumber (fixing pair links AND provenance across the renumber)
    rng.shuffle(cases)
    renumber = {c.id: f"q{i:02d}" for i, c in enumerate(cases, 1)}
    for c in cases:
        c.id = renumber[c.id]
    for c in cases:
        if c.rephrase_pair:
            c.rephrase_pair = renumber.get(c.rephrase_pair)
    for rb, orig_base_id in rephrase_sources:
        rb.generation_provenance = f"rephrase of {renumber.get(orig_base_id, orig_base_id)}"
    return cases


