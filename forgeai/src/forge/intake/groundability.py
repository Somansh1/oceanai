"""Groundability guard: does the corpus actually support what the brief asks?

Per must-answer topic: retrieve candidates, ask the model for evidence judgment,
DETERMINE density code-side from matched chunk IDs — the model never gets to
just assert a number. Unsupported topics are rewritten into the must-refuse
list; the brief gets edited, not vetoed.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..llm import Harness
from ..retrieve import HybridIndex
from ..spec import GroundabilityMap, RequirementsDoc, TopicCoverage


class EvidenceVerdict(BaseModel):
    evidence_found: bool
    matched_chunk_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""


def _topic_terms(topic: str) -> list[str]:
    from ..retrieve.bm25 import tokenize
    return [t for t in tokenize(topic) if len(t) > 2]


def _corroborate(topic: str, hits: list[tuple[str, float]], index: HybridIndex
                 ) -> tuple[str | None, str | None, bool]:
    """Deterministic evidence check. Returns (chunk_id, snippet, heading_match).

    heading_match=True when a markdown heading in the chunk contains a head
    topic term — near-conclusive structural evidence (the corpus has a whole
    SECTION on this topic)."""
    terms = _topic_terms(topic)
    if not terms:
        return None, None, False
    for cid, _ in hits:
        chunk = index.get_chunk(cid)
        if not chunk:
            continue
        low = chunk.text.lower()
        present = [t for t in terms if t in low]
        need = max(2, -(-len(terms) * 3 // 5))
        if len(present) >= min(need, len(terms)):
            headings = [h.lower() for h in re.findall(r"^#{1,3}\s+(.+)$", chunk.text, flags=re.M)]
            heading_hit = any(any(t in h for t in terms) for h in headings)
            pos = low.find(present[0])
            start = max(0, pos - 80)
            snippet = chunk.text[start : pos + 160].replace("\n", " ")
            return cid, snippet, heading_hit
    return None, None, False


def _probe_topic(harness: Harness, index: HybridIndex, topic: str) -> TopicCoverage:
    hits = index.query(topic, top_k=5)
    # full chunk text — truncating the probe context once hid the very evidence
    # being judged (sick-leave section sat past char 1000 of its chunk)
    retrieved_text = "\n\n---\n\n".join(
        f"[{cid}]\n{index.get_chunk(cid).text[:2500]}" for cid, _ in hits if index.get_chunk(cid)
    )
    prompt, sha = harness.prompts.render(
        "03_groundability_topics", topic=topic, chunks=retrieved_text or "(no chunks retrieved)")
    verdict = harness.ask_json(EvidenceVerdict, prompt, stage="groundability", prompt_sha=sha)

    notes: list[str] = []
    corroborated_id: str | None = None
    heading_match = False
    # model said "no evidence" but code found the topic terms verbatim in a
    # retrieved chunk -> one pointed re-ask with the evidence quoted
    if not verdict.evidence_found:
        cid, snippet, heading_match = _corroborate(topic, hits, index)
        if cid and snippet:
            corroborated_id = cid
            notes.append(
                f"deterministic corroboration: '{topic}' terms found verbatim in {cid}; "
                "model verdict disputed, re-asked with evidence quoted")
            re_prompt = (
                f"You previously judged that no chunk addresses the topic, but chunk {cid} "
                f"contains this passage:\n\n\"{snippet}\"\n\n"
                f"Topic: {topic}\n"
                "Reconsider strictly: does this passage (and the chunks below) contain facts "
                "that answer real questions about the topic? Answer with the same JSON schema."
                "\n\n" + (retrieved_text or "")
            )
            verdict = harness.ask_json(EvidenceVerdict, re_prompt, stage="groundability_reask",
                                       prompt_sha=sha)
            if verdict.evidence_found and cid not in verdict.matched_chunk_ids:
                verdict.matched_chunk_ids.append(cid)

    valid_ids = [cid for cid in verdict.matched_chunk_ids if index.get_chunk(cid) is not None]
    if verdict.evidence_found and not valid_ids:
        # model asserted evidence with no verified chunk IDs -> downgraded automatically
        verdict.evidence_found = False

    # DETERMINISTIC OVERRIDE: the model disputed its own evidence twice, but a
    # retrieved chunk contains the topic's head terms verbatim AND (ideally) a
    # section heading on the topic. Code disposes over a doubled-down opinion.
    # The override is flagged in the artifact — the report shows it, never hides it.
    if not verdict.evidence_found and corroborated_id and heading_match:
        verdict.evidence_found = True
        if corroborated_id not in valid_ids:
            valid_ids.append(corroborated_id)
        notes.append(
            f"DETERMINISTIC OVERRIDE: model refused twice; section heading + head terms "
            f"for '{topic}' verified in {corroborated_id}. Marked supported against the "
            "model's judgment — disagreement logged for the report.")

    density = len(valid_ids) / max(1, len(hits)) if hits else 0.0
    # support gates on VERIFIED evidence, never on retrieval fractions —
    # tiny corpora must not be punished for having few chunks
    if verdict.evidence_found and valid_ids:
        status = "supported"
    elif verdict.evidence_found or valid_ids:
        status = "thin"
    else:
        status = "unsupported"
    if verdict.reasoning:
        notes.append(verdict.reasoning[:200])
    return TopicCoverage(
        topic=topic, status=status, evidence_density=round(density, 3),
        supporting_chunk_ids=valid_ids, note=" | ".join(notes) or None,
    )


def run_groundability(harness: Harness, index: HybridIndex, req: RequirementsDoc) -> RequirementsDoc:
    """Probe every must-answer topic; rewrite unsupported ones into must-refuse."""
    rows: list[TopicCoverage] = []
    rewriting: list[TopicCoverage] = []
    for topic in req.must_answer_topics:
        row = _probe_topic(harness, index, topic)
        rows.append(row)
        if row.status == "unsupported":
            rewriting.append(row)
            req.must_refuse_topics.append(f"{topic} (uncovered by the documents)")
    # drop rewritten topics from must-answer
    rewrite_names = {r.topic for r in rewriting}
    req.must_answer_topics = [t for t in req.must_answer_topics if t not in rewrite_names]
    req.groundability = GroundabilityMap(rows=rows, rewritten_to_refusal=rewriting)
    return req
