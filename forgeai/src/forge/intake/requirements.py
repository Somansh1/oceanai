"""Requirements synthesis: brief + inventory + assumptions -> typed RequirementsDoc."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ..llm import Harness
from ..spec import Assumption, GroundabilityMap, RequirementsDoc, TopicCoverage


class RawRequirements(BaseModel):
    """What the model returns; we merge into the full RequirementsDoc ourselves."""

    agent_name: str
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    audience: str = "general staff"
    tone: str = "clear and neutral"
    must_answer_topics: list[str] = Field(default_factory=list)
    must_refuse_topics: list[str] = Field(default_factory=list)


def synthesize_requirements(harness: Harness, brief: str, inventory: str,
                            assumptions: list[Assumption]) -> RequirementsDoc:
    ans_blob = json.dumps(
        [{"q": a.question, "decision": a.decision_resolved, "a": a.assumed_answer,
          "basis": a.basis} for a in assumptions], indent=1)
    prompt, sha = harness.prompts.render(
        "02_requirements_doc", brief=brief, doc_inventory=inventory, answers=ans_blob)
    raw = harness.ask_json(RawRequirements, prompt, stage="requirements", prompt_sha=sha)
    scope_in = raw.scope_in or list(raw.must_answer_topics)
    scope_out = raw.scope_out or list(raw.must_refuse_topics)
    return RequirementsDoc(
        brief_verbatim=brief,
        agent_name=raw.agent_name,
        scope_in=scope_in,
        scope_out=scope_out,
        audience=raw.audience,
        tone=raw.tone,
        must_answer_topics=raw.must_answer_topics,
        must_refuse_topics=raw.must_refuse_topics,
        clarifying_questions=[a.question for a in assumptions],
        assumptions=assumptions,
        groundability=GroundabilityMap(rows=[
            TopicCoverage(topic=t, status="supported", evidence_density=0.0,
                          supporting_chunk_ids=[], note="pending probe")
            for t in raw.must_answer_topics
        ]),
    )


def interactive_checkpoint(req: RequirementsDoc) -> RequirementsDoc:
    """Human checkpoint: let the requester inspect, edit, or approve requirements."""
    print("\n=== Requirements Checkpoint ===")
    print(f"Agent: {req.agent_name}")
    print(f"Audience: {req.audience} | Tone: {req.tone}")
    print(f"Scope IN: {req.scope_in}")
    print(f"Scope OUT: {req.scope_out}")
    print(f"Must-answer: {req.must_answer_topics}")
    print(f"Must-refuse: {req.must_refuse_topics}")
    if req.groundability.rewritten_to_refusal:
        print(f"Groundability rewrites to refusal: {[r.topic for r in req.groundability.rewritten_to_refusal]}")
    choice = input("\nApprove requirements? [Y=approve / e=edit fields / q=abort]: ").strip().lower()
    if choice == "q":
        raise RuntimeError("Requirements rejected at human checkpoint.")
    if choice == "e":
        aud = input(f"Audience [{req.audience}]: ").strip()
        if aud:
            req.audience = aud
        tone = input(f"Tone [{req.tone}]: ").strip()
        if tone:
            req.tone = tone
        ma = input("Must-answer topics (comma-separated, blank to keep): ").strip()
        if ma:
            req.must_answer_topics = [x.strip() for x in ma.split(",") if x.strip()]
        mr = input("Must-refuse topics (comma-separated, blank to keep): ").strip()
        if mr:
            req.must_refuse_topics = [x.strip() for x in mr.split(",") if x.strip()]
    return req
