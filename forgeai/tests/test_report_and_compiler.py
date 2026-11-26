"""Unit tests for eval compiler, honest reporting, and regression mode."""
from __future__ import annotations

import json
from pathlib import Path

from forge.core import Chunk, ChunkKind, Provenance
from forge.evals.compiler import (AnswerableDraft, EdgeDraft, RefusalDraft,
                                  RephraseDraft, compile_evalset)
from forge.evaltypes import CaseKind, CostEntry, CostLedger
from forge.llm import Harness, PromptLibrary
from forge.regression import run_regression
from forge.report import build_report
from forge.retrieve.store import HybridIndex
from forge.spec import AgentDefinition, RequirementsDoc


class _CompilerHarness(Harness):
    _TOPICS = [
        "vacation carryover", "sick certificate", "parental weeks", "sabbatical eligibility",
        "holiday compensation", "berth occupancy", "demurrage free", "pilotage loa",
        "tug duration", "waste disposal", "bunker supplier", "vessel draft",
        "cargo manifest", "crewing rotation", "pension match", "overtime meal",
        "parking permit", "tuition stipend", "visa sponsorship", "insurance deductible",
        "harbour radar", "anchorage fee", "drydock slot", "ballast inspection",
        "customs clearance", "mooring rope", "lighthouse tax", "crane tariff",
        "terminal gate", "reefer plug", "fuel sulfur", "gangway guard",
        "emergency drill", "shore power", "port security", "shift handover",
    ]

    def __init__(self):
        super().__init__(ledger=CostLedger(), prompts=PromptLibrary())
        self._n = 0

    def _topic(self) -> str:
        t = self._TOPICS[(self._n - 1) % len(self._TOPICS)]
        return f"{t} item{self._n}"

    def ask_json(self, schema, prompt: str, *, stage: str = "unknown", **kwargs):
        self._n += 1
        tag = self._topic()
        if schema is AnswerableDraft:
            return AnswerableDraft(
                question=f"Explain {tag} entitlement limit?",
                expected_facts=[f"Rule for {tag}"],
            )
        if schema is EdgeDraft:
            if "numeric" in prompt:
                return EdgeDraft(
                    question=f"Compute total {tag} 10 plus {self._n}?",
                    mode="numeric",
                    expected_facts=[f"Total {10 + self._n}"],
                    expected_value=999.0,  # deliberately wrong to test derivation recompute
                    derivation=f"10 + {self._n}",
                )
            if "cross_doc" in prompt:
                return EdgeDraft(
                    question=f"Compare {tag} across policy and tariff?",
                    mode="cross_doc",
                    expected_facts=["Combined fact"],
                )
            return EdgeDraft(
                question=f"How does {tag} apply generally?",
                mode="ambiguous",
                expected_facts=["Ambiguous reading fact"],
            )
        if schema is RefusalDraft:
            return RefusalDraft(
                question=f"What are {tag} exclusions outside documents?",
                mode="refusal",
                why_refusal_expected="Not in corpus",
            )
        if schema is RephraseDraft:
            return RephraseDraft(rephrased_question=f"Casual phrasing asking {tag}?")
        raise AssertionError(f"unexpected schema: {schema}")

    def yes_no(self, question: str, *, stage: str = "judge", prompt_sha: str = "ad-hoc") -> bool:
        return stage != "eval_refusal_gate"


def test_compile_evalset_meets_min_20_and_all_edge_kinds(tmp_path: Path):
    idx = HybridIndex(tmp_path / "index.sqlite")
    idx.add_chunks([
        Chunk(
            id="d01#c000",
            text="Doc one has 24 annual leave days and 10 sick days and 16 weeks leave.",
            kind=ChunkKind.PARAGRAPH,
            provenance=Provenance(doc_id="d01", source_path="d1.md", loader="md"),
        ),
        Chunk(
            id="d02#c000",
            text="Doc two has 598 USD fuel price and 4500 USD port dues minimum 2026.",
            kind=ChunkKind.PARAGRAPH,
            provenance=Provenance(doc_id="d02", source_path="d2.md", loader="md"),
        ),
    ])
    req = RequirementsDoc(brief_verbatim="brief", agent_name="Agent", must_answer_topics=["leave", "dues"])
    cases = compile_evalset(_CompilerHarness(), idx, req)
    assert len(cases) >= 20
    kinds = {c.kind for c in cases}
    assert CaseKind.ANSWERABLE in kinds
    assert CaseKind.CROSS_DOC in kinds
    assert CaseKind.AMBIGUOUS in kinds
    assert CaseKind.NUMERIC in kinds
    assert CaseKind.REFUSAL in kinds
    assert CaseKind.CANARY in kinds
    assert CaseKind.REPHRASE_A in kinds
    assert CaseKind.REPHRASE_B in kinds
    # Numeric derivation recomputed deterministically instead of trusting 999.0
    num_cases = [c for c in cases if c.kind == CaseKind.NUMERIC]
    assert num_cases[0].expected_value != 999.0
    # Cross-doc actually spans d01 and d02
    cross_cases = [c for c in cases if c.kind == CaseKind.CROSS_DOC]
    assert all(len(c.expected_chunk_ids) == 2 for c in cross_cases)
    # Rephrase provenance points to valid renumbered REPHRASE_A id
    by_id = {c.id: c for c in cases}
    for c in cases:
        if c.kind == CaseKind.REPHRASE_B:
            assert c.generation_provenance == f"rephrase of {c.rephrase_pair}"
            assert by_id[c.rephrase_pair].kind == CaseKind.REPHRASE_A
    idx.close()


def test_build_report_aggregates_ledger_entries_and_baseline(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    req = RequirementsDoc(brief_verbatim="b", agent_name="DemoAgent")
    defn = AgentDefinition(name="DemoAgent", system_prompt="sys", requirements_digest="d")
    (run_dir / "requirements.json").write_text(req.model_dump_json(), encoding="utf-8")
    (run_dir / "definition.json").write_text(defn.model_dump_json(), encoding="utf-8")
    (run_dir / "evalset.jsonl").write_text(
        json.dumps({"id": "q01", "kind": "answerable", "question": "What is leave?", "expected_refusal": False, "expected_chunk_ids": ["d01#c000"], "expected_facts": ["24 days"]}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "results.jsonl").write_text(
        json.dumps({"case_id": "q01", "refused": False, "answer": "wrong", "citations": ["d01#c000"], "retrieved_chunk_ids": ["d01#c000"], "expected_retrieved": True, "cited_valid": True, "grounded": False, "fact_matches": {"24 days": False}, "fact_coverage": 0.0, "passed": False, "failure_class": "hallucination"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "scorecard.json").write_text(
        json.dumps({"iteration": 0, "total": 1, "passed": 0, "score": 0.0, "wilson_low": 0.0, "wilson_high": 0.79}),
        encoding="utf-8",
    )
    (run_dir / "scorecard_baseline_human.json").write_text(
        json.dumps({"iteration": 0, "total": 1, "passed": 1, "score": 1.0, "wilson_low": 0.2, "wilson_high": 1.0}),
        encoding="utf-8",
    )
    ledger = CostLedger(entries=[
        CostEntry(stage="build", model="qwen", prompt_sha="abc", in_tokens=100, out_tokens=20, latency_ms=1000),
        CostEntry(stage="judge_l1", model="qwen", prompt_sha="def", in_tokens=50, out_tokens=5, latency_ms=500),
    ])
    (run_dir / "ledger.json").write_text(ledger.model_dump_json(), encoding="utf-8")

    md = build_report(run_dir)
    assert "Total: 2 calls, 175 tokens, 2s model time." in md
    assert "ungrounded claim" in md
    assert "Factory vs Human Baseline" in md


class _RegHarness(Harness):
    def __init__(self):
        super().__init__(ledger=CostLedger(), prompts=PromptLibrary())

    def ask_text(self, prompt: str, **kwargs) -> str:
        return "24 days"

    def ask_json(self, schema, prompt: str, **kwargs):
        if schema is AnswerableDraft:
            return AnswerableDraft(question="Updated question?", expected_facts=["30 days"])
        if schema is EdgeDraft:
            return EdgeDraft(question="Edge question?", mode="cross_doc", expected_facts=["30 days"])
        if schema is RefusalDraft:
            return RefusalDraft(question="Refusal question?", mode="refusal")
        if schema is RephraseDraft:
            return RephraseDraft(rephrased_question="Rephrased updated question?")
        # ContractAnswer
        return schema(answer="30 days", refused=False, citations=["d01#c000"], confidence=0.9)

    def yes_no(self, question: str, **kwargs) -> bool:
        return kwargs.get("stage") != "eval_refusal_gate"


def test_regression_detects_broken_case(tmp_path: Path):
    run_dir = tmp_path / "run"
    docs_dir = tmp_path / "docs"
    run_dir.mkdir()
    docs_dir.mkdir()
    (docs_dir / "policy.md").write_text("Annual leave is now 30 days instead of 24 days.", encoding="utf-8")

    (run_dir / "requirements.json").write_text(
        RequirementsDoc(brief_verbatim="b", agent_name="HR", must_answer_topics=["leave"]).model_dump_json(),
        encoding="utf-8",
    )
    (run_dir / "definition.json").write_text(
        AgentDefinition(name="HR", system_prompt="sys", requirements_digest="d").model_dump_json(),
        encoding="utf-8",
    )
    (run_dir / "evalset.jsonl").write_text(
        json.dumps({"id": "q01", "kind": "answerable", "question": "Leave days?", "expected_refusal": False, "expected_chunk_ids": ["d01#c000"], "expected_facts": ["24 days"]}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "results.jsonl").write_text(
        json.dumps({"case_id": "q01", "refused": False, "answer": "24 days", "citations": ["d01#c000"], "retrieved_chunk_ids": ["d01#c000"], "expected_retrieved": True, "cited_valid": True, "grounded": True, "fact_matches": {"24 days": True}, "fact_coverage": 1.0, "passed": True}) + "\n",
        encoding="utf-8",
    )
    # Wait: make yes_no return False on judge_l1 for "24 days" since doc now says "30 days"
    class _ChangedJudge(_RegHarness):
        def yes_no(self, question: str, **kwargs) -> bool:
            if kwargs.get("stage") == "judge_l1" and "24 days" in question:
                return False
            return super().yes_no(question, **kwargs)

    report_md = run_regression(run_dir, docs_dir, harness=_ChangedJudge())
    assert "Regressions (1 cases now failing that passed before)" in report_md
    assert "q01" in report_md
