"""Patch library: ONE surgical modification per failure class.

Patches APPEND versioned sections (never rewrite) so every change is a
visible diff in the system prompt's history. Regeneration is never the fix.
"""
from __future__ import annotations

from typing import Callable

from ..evaltypes import FailureClass
from ..spec import AgentDefinition

PatchFn = Callable[[AgentDefinition], str]  # returns human-readable change summary

_V = 2  # patch-section version marker


def _append(defn: AgentDefinition, title: str, body: str) -> None:
    defn.system_prompt = defn.system_prompt.rstrip() + f"\n\n## {title} (v{_V})\n{body}"


def patch_refusal_posture(defn: AgentDefinition) -> str:
    _append(defn, "Refusal discipline",
            "Before answering, check: do the retrieved chunks contain the SPECIFIC fact "
            "asked for? If the question asks for a number, policy or rule and the chunks "
            "only discuss the general topic without that specific fact, set refused=true "
            "and use the refusal template. Never infer, generalize, or approximate an "
            "answer from nearby information. Guessing is worse than refusing.")
    return "appended 'Refusal discipline' section: refuse when the SPECIFIC fact is absent, even if the topic is covered"


def patch_completeness(defn: AgentDefinition) -> str:
    has_calc = any(t.name == "calculator" for t in defn.tools)
    body = (
        "Address EVERY part of the question. For comparisons: state BOTH sides with "
        "their numbers AND the difference. For 'how many' questions: give the total AND "
        "the rule behind it. For entitlement or fee questions about a specific case: "
        "state the general rule and apply it to the case with the arithmetic shown."
    )
    summary = "appended 'Answer completeness' section: comparisons state both sides + difference"
    if has_calc:
        body += " Use the calculator tool for ALL arithmetic — never compute in your head."
        summary += "; calculator mandatory for arithmetic"
    _append(defn, "Answer completeness", body)
    return summary


def patch_grounding(defn: AgentDefinition) -> str:
    _append(defn, "Citation discipline",
            "Cite only chunk ids that appear in the provided context, formatted like "
            "d01#c002. When refusing, citations MUST be an empty list. Never cite a chunk "
            "you did not use.")
    return "appended 'Citation discipline' section: citations restricted to context ids; empty on refusal"


def patch_over_refusal(defn: AgentDefinition) -> str:
    _append(defn, "Answer when grounded",
            "If ANY context chunk contains information that answers the question — even "
            "partially — answer from it with citations. Refuse ONLY when no chunk "
            "addresses the question's specifics at all.")
    return "appended 'Answer when grounded' section: refuse only when no chunk addresses the specifics"


def patch_retrieval(defn: AgentDefinition) -> str:
    old_d, old_s = defn.retrieval.top_k_dense, defn.retrieval.top_k_sparse
    defn.retrieval.top_k_dense = min(old_d + 2, 12)
    defn.retrieval.top_k_sparse = min(old_s + 3, 16)
    defn.retrieval.query_rewrite = True
    return (f"retrieval.top_k_dense {old_d}->{defn.retrieval.top_k_dense}, "
            f"top_k_sparse {old_s}->{defn.retrieval.top_k_sparse}, query_rewrite=on")


def patch_contract(defn: AgentDefinition) -> str:
    _append(defn, "Output format reminder",
            "Respond ONLY with the JSON object specified in your instructions: "
            '{"answer": str, "refused": bool, "citations": [ids], "confidence": 0..1}. '
            "No prose before or after the JSON.")
    return "appended 'Output format reminder' section: JSON-only responses enforced"


def select_prompt_defect_patch(defn: AgentDefinition, failing_results: list) -> PatchFn:
    """Pick the specific prompt patch matching the observed defect telemetry."""
    if any(getattr(r, "parse_failed", False) for r in failing_results):
        return patch_contract
    if any(getattr(r, "cited_valid", True) is False for r in failing_results):
        return patch_grounding
    return patch_completeness


PATCH_LIBRARY: dict[FailureClass, PatchFn] = {
    FailureClass.HALLUCINATION: patch_refusal_posture,
    FailureClass.PROMPT_DEFECT: patch_completeness,
    FailureClass.WRONG_REFUSAL: patch_over_refusal,
    FailureClass.RETRIEVAL_MISS: patch_retrieval,
}
