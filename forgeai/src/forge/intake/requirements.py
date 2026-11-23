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
    return RequirementsDoc(
        brief_verbatim=brief,
        agent_name=raw.agent_name,
        scope_in=raw.scope_in,
        scope_out=raw.scope_out,
        audience=raw.audience,
        tone=raw.tone,
        must_answer_topics=raw.must_answer_topics,
        must_refuse_topics=raw.must_refuse_topics,
        assumptions=assumptions,
        groundability=GroundabilityMap(rows=[
            TopicCoverage(topic=t, status="supported", evidence_density=0.0,
                          supporting_chunk_ids=[], note="pending probe")
            for t in raw.must_answer_topics
        ]),
    )
