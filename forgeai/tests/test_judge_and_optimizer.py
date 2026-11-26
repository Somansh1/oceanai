"""Unit tests for layered judge, failure classification, and optimizer rollback/budget."""
from __future__ import annotations

from pathlib import Path

from forge.core import Chunk, ChunkKind, Provenance
from forge.critic.optimizer import optimize
from forge.critic.patches import patch_completeness
from forge.evaltypes import CaseKind, CostEntry, CostLedger, EvalCase, FailureClass
from forge.judge.judge import classify_failure, judge_case
from forge.llm import Harness, PromptLibrary
from forge.retrieve.store import HybridIndex
from forge.runner.engine import AgentResponse
from forge.spec import AgentDefinition, RetrievalConfig, ToolBinding


class _FakeYesNoHarness(Harness):
    def __init__(self, answers: list[bool]):
        super().__init__(ledger=CostLedger(), prompts=PromptLibrary())
        self._answers = list(answers)

    def yes_no(self, question: str, *, stage: str = "judge", prompt_sha: str = "ad-hoc") -> bool:
        return self._answers.pop(0) if self._answers else True


def test_patch_completeness_respects_attached_tools():
    no_tools = AgentDefinition(name="A", system_prompt="Base", requirements_digest="d", tools=[])
    summary_no = patch_completeness(no_tools)
    assert "calculator" not in no_tools.system_prompt.lower()
    assert "calculator" not in summary_no.lower()

    with_calc = AgentDefinition(
        name="B",
        system_prompt="Base",
        requirements_digest="d",
        tools=[ToolBinding(name="calculator", justification="math", invoked_when="math")],
    )
    summary_yes = patch_completeness(with_calc)
    assert "calculator" in with_calc.system_prompt.lower()
    assert "calculator" in summary_yes.lower()


def test_judge_requires_valid_citations_and_groundedness(tmp_path: Path):
    idx = HybridIndex(tmp_path / "index.sqlite")
    idx.add_chunks([
        Chunk(
            id="d01#c000",
            text="Shore staff receive 24 working days of annual leave.",
            kind=ChunkKind.PARAGRAPH,
            provenance=Provenance(doc_id="d01", source_path="hr.md", loader="md"),
        )
    ])
    case = EvalCase(
        id="q01",
        kind=CaseKind.ANSWERABLE,
        question="How many annual leave days?",
        expected_chunk_ids=["d01#c000"],
        expected_facts=["24 working days of annual leave"],
    )

    # Missing citations -> invalid and ungrounded
    resp_nocite = AgentResponse(
        answer="24 working days of annual leave.",
        refused=False,
        citations=[],
        retrieved=["d01#c000"],
    )
    res_nocite = judge_case(_FakeYesNoHarness([]), idx, case, resp_nocite)
    assert res_nocite.cited_valid is False
    assert res_nocite.grounded is False
    assert res_nocite.passed is False
    assert res_nocite.failure_class == FailureClass.PROMPT_DEFECT

    # Valid retrieved citation + grounded L1 yes -> passes
    resp_ok = AgentResponse(
        answer="Shore staff get 24 working days of annual leave.",
        refused=False,
        citations=["d01#c000"],
        retrieved=["d01#c000"],
    )
    res_ok = judge_case(_FakeYesNoHarness([True]), idx, case, resp_ok)
    assert res_ok.cited_valid is True
    assert res_ok.grounded is True
    assert res_ok.passed is True
    idx.close()


def test_classify_failure_distinguishes_incomplete_vs_hallucination():
    case = EvalCase(id="q01", kind=CaseKind.ANSWERABLE, question="?", expected_facts=["a", "b"])
    from forge.evaltypes import CaseResult
    partial = CaseResult(
        case_id="q01", refused=False, answer="a", citations=["d01#c000"],
        retrieved_chunk_ids=["d01#c000"], expected_retrieved=True, cited_valid=True,
        grounded=True, fact_matches={"a": True, "b": False}, fact_coverage=0.5, passed=False,
    )
    assert classify_failure(case, partial) == FailureClass.PROMPT_DEFECT

    ungrounded = partial.model_copy(update={"grounded": False})
    assert classify_failure(case, ungrounded) == FailureClass.HALLUCINATION


def test_optimizer_rolls_back_harmful_patch_and_enforces_budget():
    defn = AgentDefinition(
        name="TestAgent",
        system_prompt="Initial",
        requirements_digest="d",
        retrieval=RetrievalConfig(),
    )
    cases = [EvalCase(id="q01", kind=CaseKind.ANSWERABLE, question="Q1"),
             EvalCase(id="q02", kind=CaseKind.ANSWERABLE, question="Q2")]

    from forge.evaltypes import CaseResult
    from forge.judge import build_scorecard

    def evaluator(d: AgentDefinition, subset=None):
        active = subset or cases
        if "Refusal discipline" in d.system_prompt:
            # Patch hurts score (0.5 -> 0.0) -> must roll back!
            res = [
                CaseResult(case_id="q01", refused=True, answer="", passed=False, failure_class=FailureClass.WRONG_REFUSAL),
                CaseResult(case_id="q02", refused=True, answer="", passed=False, failure_class=FailureClass.WRONG_REFUSAL),
            ]
        else:
            res = [
                CaseResult(case_id="q01", refused=False, answer="ok", passed=True),
                CaseResult(case_id="q02", refused=False, answer="bad", passed=False, failure_class=FailureClass.HALLUCINATION),
            ]
        return res, build_scorecard(res, active, iteration=d.iteration)

    opt = optimize(evaluator, defn, cases, max_iterations=2)
    assert "Refusal discipline" not in opt.definition.system_prompt
    assert any(p.rolled_back for e in opt.entries for p in e.patches)

    # Budget exhaustion stops before applying patches
    ledger = CostLedger(entries=[CostEntry(stage="build", model="m", prompt_sha="x", in_tokens=5000, out_tokens=500)])
    opt_budget = optimize(evaluator, defn, cases, max_iterations=3, ledger=ledger, max_tokens=5000)
    assert opt_budget.budget_exhausted is True
    assert opt_budget.stopped_early is True
    assert len(opt_budget.entries) == 1
