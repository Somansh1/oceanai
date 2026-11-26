"""Unit tests for the critic-optimizer patch library."""
from __future__ import annotations

from forge.critic.patches import (
    patch_completeness,
    patch_refusal_posture,
    patch_retrieval,
)
from forge.spec import AgentDefinition, OutputContract, RetrievalConfig, ToolBinding


def _make_defn(with_calculator: bool = False) -> AgentDefinition:
    tools = (
        [ToolBinding(name="calculator", justification="math", invoked_when="math")]
        if with_calculator
        else []
    )
    return AgentDefinition(
        name="CandidateAgent",
        system_prompt="Base system prompt instructions.",
        requirements_digest="Scope: test requirements; tone: neutral",
        retrieval=RetrievalConfig(top_k_dense=4, top_k_sparse=6),
        tools=tools,
        output_contract=OutputContract(),
    )


def test_patch_refusal_posture():
    defn = _make_defn()
    summary = patch_refusal_posture(defn)
    assert "Refusal discipline" in defn.system_prompt
    assert "refuse" in summary.lower()


def test_patch_completeness():
    defn_no_calc = _make_defn(with_calculator=False)
    summary_no = patch_completeness(defn_no_calc)
    assert "Answer completeness" in defn_no_calc.system_prompt
    assert "calculator" not in defn_no_calc.system_prompt.lower()
    assert "calculator" not in summary_no.lower()

    defn_calc = _make_defn(with_calculator=True)
    summary_yes = patch_completeness(defn_calc)
    assert "Answer completeness" in defn_calc.system_prompt
    assert "calculator" in defn_calc.system_prompt.lower()
    assert "calculator" in summary_yes.lower()


def test_patch_retrieval_increases_top_k():
    defn = _make_defn()
    old_dense = defn.retrieval.top_k_dense
    old_sparse = defn.retrieval.top_k_sparse
    summary = patch_retrieval(defn)
    assert defn.retrieval.top_k_dense > old_dense
    assert defn.retrieval.top_k_sparse > old_sparse
    assert "top_k_dense" in summary.lower()
