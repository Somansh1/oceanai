"""Specification artifacts: requirements, groundability, agent definition.

The AgentDefinition is the declarative product the factory ships. The generic
runner loads ANY definition; the judge scores against the same output contract
the runner enforces. One contract, three consumers.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- requirements


class Assumption(BaseModel):
    """An --auto resolution of an interview question. Logged, never hidden."""

    question: str
    decision_resolved: str  # e.g. "refusal_posture", "tool_need", "scope_boundary"
    assumed_answer: str
    basis: str  # "conservative default" | "derived from d02#c014" | ...


class TopicCoverage(BaseModel):
    topic: str
    status: Literal["supported", "thin", "unsupported"]
    evidence_density: float  # 0..1 — share of probe claims matched
    supporting_chunk_ids: list[str] = Field(default_factory=list)
    note: str | None = None  # e.g. "asked for salary bands; docs support grades only"


class GroundabilityMap(BaseModel):
    rows: list[TopicCoverage] = Field(default_factory=list)
    rewritten_to_refusal: list[TopicCoverage] = Field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts = {s: 0 for s in ("supported", "thin", "unsupported")}
        for r in self.rows:
            counts[r.status] += 1
        return counts


class RequirementsDoc(BaseModel):
    brief_verbatim: str
    agent_name: str
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    audience: str | None = None
    tone: str | None = None
    must_answer_topics: list[str] = Field(default_factory=list)
    must_refuse_topics: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    groundability: GroundabilityMap = Field(default_factory=GroundabilityMap)


# ------------------------------------------------------------- agent definition


class RetrievalConfig(BaseModel):
    """All retrieval knobs are DATA — the runner reads them from the definition."""

    chunk_size: int = 900
    chunk_overlap: int = 150
    top_k_dense: int = 5
    top_k_sparse: int = 8
    rrf_k: int = 60
    hybrid: bool = True
    query_rewrite: bool = False
    min_score: float = 0.0


class ToolBinding(BaseModel):
    name: str  # registry key: csv_lookup | calculator | open_meteo | now
    justification: str
    invoked_when: str
    config: dict[str, Any] = Field(default_factory=dict)


class ToolRejection(BaseModel):
    name: str
    reason: str


class ContractField(BaseModel):
    name: str
    type: Literal["string", "number", "boolean", "array", "object"]
    required: bool = True
    description: str


class OutputContract(BaseModel):
    """The measurement instrument: runner enforces it, judge exploits it."""

    fields: list[ContractField] = Field(default_factory=lambda: [
        ContractField(name="answer", type="string", description="Grounded answer, or empty if refusing"),
        ContractField(name="refused", type="boolean", description="True when the agent declines to answer"),
        ContractField(name="citations", type="array", description="Chunk IDs grounded on, e.g. [\"d01#c003\"]"),
        ContractField(name="confidence", type="number", required=False, description="0..1 self-assessed grounding strength"),
    ])

    def to_json_schema(self) -> dict[str, Any]:
        props: dict[str, Any] = {}
        required: list[str] = []
        type_map = {"string": "string", "number": "number", "boolean": "boolean"}
        for f in self.fields:
            if f.type in type_map:
                props[f.name] = {"type": type_map[f.type], "description": f.description}
            elif f.type == "array":
                props[f.name] = {"type": "array", "items": {"type": "string"}, "description": f.description}
            else:
                props[f.name] = {"type": "object", "description": f.description}
            if f.required:
                required.append(f.name)
        return {"type": "object", "properties": props, "required": required}


class RefusalPolicy(BaseModel):
    must_refuse_topics: list[str] = Field(default_factory=list)
    refusal_template: str = (
        "I don't have grounded information about {topic} in the provided documents. "
        "I can help with topics covered there."
    )
    over_refusal_guard: str | None = None  # prompt clause patched on wrong-refusal failures


class AgentDefinition(BaseModel):
    """The shipped product: declarative, runnable by the generic runner."""

    name: str
    version: int = 1
    iteration: int = 0
    system_prompt: str
    requirements_digest: str
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    tools: list[ToolBinding] = Field(default_factory=list)
    rejected_tools: list[ToolRejection] = Field(default_factory=list)
    output_contract: OutputContract = Field(default_factory=OutputContract)
    refusal_policy: RefusalPolicy = Field(default_factory=RefusalPolicy)
    tournament_candidates: list[dict[str, Any]] = Field(default_factory=list)
