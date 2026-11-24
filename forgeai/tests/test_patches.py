"""Unit tests for the critic-optimizer patch library."""
from __future__ import annotations

from forge.critic.patches import (
    patch_completeness,
    patch_grounding,
    patch_over_refusal,
    patch_refusal_posture,
    patch_retrieval,
)
from forge.spec import AgentDefinition, OutputContract, RetrievalConfig


def _make_defn() -> AgentDefinition:
    return AgentDefinition(
        name="CandidateAgent",
        system_prompt="Base system prompt instructions.",
        requirements_digest="Scope: test requirements; tone: neutral",
        retrieval=RetrievalConfig(top_k_dense=4, top_k_sparse=6),
        tools=[],
        output_contract=OutputContract(),
    )


def test_patch_refusal_posture():
    defn = _make_defn()
    summary = patch_refusal_posture(defn)
    assert "Refusal discipline" in defn.system_prompt
    assert "refuse" in summary.lower()


def test_patch_completeness():
    defn = _make_defn()
    summary = patch_completeness(defn)
    assert "Answer completeness" in defn.system_prompt
    assert "calculator" in defn.system_prompt.lower()
    assert "calculator" in summary.lower()


def test_patch_retrieval_increases_top_k():
    defn = _make_defn()
    old_dense = defn.retrieval.top_k_dense
    old_sparse = defn.retrieval.top_k_sparse
    summary = patch_retrieval(defn)
    assert defn.retrieval.top_k_dense > old_dense
    assert defn.retrieval.top_k_sparse > old_sparse
    assert "top_k_dense" in summary.lower()
