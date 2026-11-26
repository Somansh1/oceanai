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


# Synonym equivalence classes: "costs" must match "charged at USD", "stay"
# must match "occupancy". Vocabulary-blind matching once rewrote covered
# topics ("berth change or stay costs") into must-refuse and poisoned the
# agent's refusal policy with its own core scope.
_SYNONYM_CLASSES = [
    {"cost", "costs", "fee", "fees", "charge", "charges", "charged", "price",
     "prices", "pricing", "rate", "rates", "tariff", "tariffs", "due", "dues"},
    {"weather", "wind", "swell", "sea", "wave", "forecast", "conditions",
     "storm", "marine"},
    {"stay", "occupancy", "berthing", "alongside", "turnaround"},
    {"leave", "vacation", "absence", "holiday"},
    {"vessel", "ship", "tanker", "craft"},
    {"schedule", "arrival", "eta", "berth", "berths"},
    {"tug", "tugs", "towage"},
]

# Tool capability map: tools extend groundability. Live-data topics have no
# document evidence by design — open_meteo supplies them.
_TOOL_TOPICS = {
    "open_meteo": ["weather", "wind", "swell", "sea condition", "forecast",
                   "wave", "sea state", "current condition"],
    "now": ["current date", "today", "how many days", "next vessel",
            "upcoming", "relative"],
    "calculator": ["cost", "fee", "charge", "price", "total", "demurrage",
                   "difference", "compute", "arithmetic"],
    "csv_lookup": ["schedule", "berth", "vessel", "imo", "lookup", "price list"],
}


def _expand(term: str) -> set[str]:
    out = {term}
    for cls in _SYNONYM_CLASSES:
        if term in cls:
            out |= cls
    return out


def _terms_present(terms: list[str], text: str) -> int:
    """How many topic terms appear in text, honoring synonym classes."""
    low = text.lower()
    count = 0
    for t in terms:
        if any(s in low for s in _expand(t)):
            count += 1
    return count


def _tool_backed(topic: str, attached: list[str]) -> str | None:
    low = topic.lower()
    for tool, kws in _TOOL_TOPICS.items():
        if tool in attached and any(re.search(rf"\b{re.escape(k)}\b", low) for k in kws):
            return tool
    return None


def _topic_terms(topic: str) -> list[str]:
    from ..retrieve.bm25 import tokenize
    return [t for t in tokenize(topic) if len(t) > 2]


def _corroborate(topic: str, hits: list[tuple[str, float]], index: HybridIndex
                 ) -> tuple[str | None, str | None, bool]:
    """Deterministic evidence check. Returns (chunk_id, snippet, heading_match).

    heading_match=True when a markdown heading in the chunk contains a head
    topic term (synonym classes honored) — near-conclusive structural
    evidence (the corpus has a whole SECTION on this topic)."""
    terms = _topic_terms(topic)
    if not terms:
        return None, None, False
    for cid, _ in hits:
        chunk = index.get_chunk(cid)
        if not chunk:
            continue
        low = chunk.text.lower()
        present = _terms_present(terms, low)
        need = max(2, -(-len(terms) * 3 // 5))
        if present >= min(need, len(terms)):
            # Match headings at start-of-line OR after inline overlap concatenation
            headings = [
                h.lower()
                for h in re.findall(r"(?:^|\s)#{1,3}\s+([^\n#]+)", chunk.text, flags=re.M)
            ]
            heading_hit = any(_terms_present(terms, h) > 0 for h in headings) or (
                len(terms) >= 2 and present == len(terms)
            )
            # quote a window around the first matched term
            first = next((s for t in terms for s in _expand(t) if s in low), terms[0])
            pos = low.find(first)
            start = max(0, pos - 80)
            snippet = chunk.text[start : pos + 160].replace("\n", " ")
            return cid, snippet, heading_hit
    return None, None, False


def _embed_query(harness: Harness, index: HybridIndex, text: str) -> list[float] | None:
    if not index._dense_ready or not harness.backend.available():
        return None
    try:
        return harness.backend.embed([text])[0]
    except Exception:
        return None


def _probe_topic(harness: Harness, index: HybridIndex, topic: str) -> TopicCoverage:
    qvec = _embed_query(harness, index, topic)
    hits = index.query(topic, vector=qvec, top_k=5)
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


def run_groundability(harness: Harness, index: HybridIndex, req: RequirementsDoc,
                      attached_tools: list[str] | None = None) -> RequirementsDoc:
    """Probe every must-answer topic; rewrite unsupported ones into must-refuse.

    Tools extend groundability: a live-data topic with no document evidence by
    design stays must-answer when its supplying tool is attached."""
    attached = attached_tools or []
    rows: list[TopicCoverage] = []
    rewriting: list[TopicCoverage] = []
    for topic in req.must_answer_topics:
        tool = _tool_backed(topic, attached)
        if tool and not _probe_topic_would_pass(harness, index, topic):
            rows.append(TopicCoverage(
                topic=topic, status="supported", evidence_density=0.0,
                supporting_chunk_ids=[], note=f"supported via attached tool '{tool}' (live data)"))
            continue
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


def _probe_topic_would_pass(harness: Harness, index: HybridIndex, topic: str) -> bool:
    """Cheap pre-check: deterministic corroboration already passes?"""
    hits = index.query(topic, top_k=5)
    cid, _snippet, heading = _corroborate(topic, hits, index)
    return bool(cid and heading)
