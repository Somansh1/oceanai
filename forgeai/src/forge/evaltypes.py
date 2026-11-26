"""Eval artifacts: cases, verdicts, scorecards, patches, manifests, cost ledger."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CaseKind(str, Enum):
    ANSWERABLE = "answerable"
    CROSS_DOC = "cross_doc"          # answer spans two documents
    AMBIGUOUS = "ambiguous"          # vague phrasing; must ask-scope or answer cautiously
    NUMERIC = "numeric"              # judge recomputes with the calculator — exact match
    REFUSAL = "refusal"              # out-of-scope: must refuse
    CANARY = "canary"                # sounds answerable, deliberately absent — trap
    REPHRASE_A = "rephrase_a"        # stability probes come in pairs
    REPHRASE_B = "rephrase_b"


class EvalCase(BaseModel):
    id: str  # "q01"..
    kind: CaseKind
    question: str
    expected_refusal: bool = False
    expected_chunk_ids: list[str] = Field(default_factory=list)
    expected_facts: list[str] = Field(default_factory=list)   # atomic claims
    expected_value: float | None = None                        # numeric cases
    rephrase_pair: str | None = None                           # partner case id
    generation_provenance: str | None = None                   # which chunk(s) seeded it
    notes: str | None = None


class FailureClass(str, Enum):
    RETRIEVAL_MISS = "retrieval_miss"
    PROMPT_DEFECT = "prompt_defect"
    HALLUCINATION = "hallucination"
    WRONG_REFUSAL = "wrong_refusal"
    JUDGE_UNSTABLE = "judge_unstable"
    UNEXPLAINED = "unexplained"


class CaseResult(BaseModel):
    case_id: str
    refused: bool
    answer: str
    citations: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    expected_retrieved: bool | None = None    # was an expected chunk in the retrieved set?
    cited_valid: bool | None = None           # all cited IDs exist in the index
    grounded: bool | None = None              # answer claims entailed by cited chunks + tool outputs
    parse_failed: bool = False                # agent breached the output contract
    fact_matches: dict[str, bool] = Field(default_factory=dict)  # expected fact -> matched
    fact_coverage: float = 0.0
    numeric_ok: bool | None = None
    passed: bool = False
    failure_class: FailureClass | None = None
    judge_unstable: bool = False
    soft_refusal: bool = False        # refused-in-substance: "not specified/covered"
    grounded_reframe: bool = False    # canary answered with verified cited facts, no invention
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class IterationScorecard(BaseModel):
    iteration: int
    total: int
    passed: int
    score: float                       # passed / total
    wilson_low: float
    wilson_high: float
    by_class: dict[str, int] = Field(default_factory=dict)   # kind -> fails
    by_failure: dict[str, int] = Field(default_factory=dict)  # FailureClass -> count
    unstable_pairs: int = 0


class PatchRecord(BaseModel):
    iteration: int
    failure_class: FailureClass
    target: str                        # e.g. "retrieval.top_k_dense", "system_prompt#grounding"
    change: str                        # human-readable diff summary
    rationale: str
    failure_ids: list[str] = Field(default_factory=list)
    score_before: float | None = None
    score_after: float | None = None
    rolled_back: bool = False


class CostEntry(BaseModel):
    stage: str
    model: str
    prompt_sha: str
    in_tokens: int = 0
    out_tokens: int = 0
    latency_ms: int = 0


class CostLedger(BaseModel):
    entries: list[CostEntry] = Field(default_factory=list)

    def add(self, entry: CostEntry) -> None:
        self.entries.append(entry)

    def totals(self) -> dict[str, int]:
        return {
            "calls": len(self.entries),
            "in_tokens": sum(e.in_tokens for e in self.entries),
            "out_tokens": sum(e.out_tokens for e in self.entries),
            "latency_ms": sum(e.latency_ms for e in self.entries),
        }

    def by_stage(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for e in self.entries:
            agg = out.setdefault(e.stage, {"calls": 0, "in_tokens": 0, "out_tokens": 0, "latency_ms": 0})
            agg["calls"] += 1
            agg["in_tokens"] += e.in_tokens
            agg["out_tokens"] += e.out_tokens
            agg["latency_ms"] += e.latency_ms
        return out


class RunManifest(BaseModel):
    run_id: str
    created_at: str
    brief_sha: str
    docs: list[dict[str, Any]] = Field(default_factory=list)  # filename -> sha256, n_chunks
    model: str
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    degraded_modes: list[str] = Field(default_factory=list)    # e.g. "dense retrieval unavailable"
