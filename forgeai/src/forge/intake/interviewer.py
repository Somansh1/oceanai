"""Interviewer: evidence-driven intake.

Questions are only asked when the answer changes the build; every question is
tagged with the decision it resolves. --auto resolves everything to the
conservative suggested default and logs it as an explicit assumption.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ..core import Chunk, DocumentMeta
from ..llm import Harness
from ..spec import Assumption


class ProposedQuestion(BaseModel):
    question: str
    decision_resolves: str
    suggested_default: str


class QuestionSet(BaseModel):
    questions: list[ProposedQuestion] = Field(default_factory=list)


def build_inventory(metas: list[DocumentMeta], chunks: list[Chunk]) -> str:
    """Compact, model-readable inventory: what the folder actually contains."""
    by_doc: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_doc.setdefault(c.provenance.doc_id, []).append(c)
    lines: list[str] = []
    for m in metas:
        dchunks = by_doc.get(m.doc_id, [])
        lines.append(f"### {m.filename} ({m.kind}, {m.n_chunks} chunks)")
        heads: list[str] = []
        for c in dchunks:
            if c.kind.value == "schema_profile":
                lines.append("columns: " + _columns_of(c.text))
            else:
                for h in re.findall(r"^#{1,3}\s+(.+)$", c.text, flags=re.M):
                    heads.append(h.strip())
        if heads:
            lines.append("sections: " + " | ".join(heads[:12]))
        sample = dchunks[0].text[:220].replace("\n", " ") if dchunks else ""
        lines.append(f"sample: {sample}")
    return "\n".join(lines)


def _columns_of(schema_text: str) -> str:
    for line in schema_text.splitlines():
        if line.startswith("columns:"):
            return line[len("columns:"):].strip()
    return "(unknown)"


def run_interview(harness: Harness, brief: str, inventory: str, *,
                  auto: bool = True) -> tuple[list[Assumption], list[str]]:
    """Returns (assumptions, interactive_answers). In --auto the second is empty."""
    prompt, sha = harness.prompts.render("01_intake_questions", brief=brief, doc_inventory=inventory)
    qs = harness.ask_json(QuestionSet, prompt, stage="interview", prompt_sha=sha)
    assumptions: list[Assumption] = []
    answers: list[str] = []
    for q in qs.questions[:5]:
        if auto:
            assumptions.append(Assumption(
                question=q.question, decision_resolved=q.decision_resolves,
                assumed_answer=q.suggested_default, basis="conservative default (--auto)",
            ))
        else:
            print(f"\n[{q.decision_resolved}] {q.question}")
            print(f"  (suggested default: {q.suggested_default})")
            ans = input("answer (enter = default): ").strip() or q.suggested_default
            answers.append(f"Q: {q.question}\nA: {ans}")
            assumptions.append(Assumption(
                question=q.question, decision_resolved=q.decision_resolves,
                assumed_answer=ans, basis="requester",
            ))
    return assumptions, answers
