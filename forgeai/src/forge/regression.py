"""Regression mode: documents change -> what breaks?

Rebuilds the index from the (possibly changed) docs, re-runs the OLD eval set
against the current agent, compiles a NEW eval set from the changed corpus,
and reports: cases that newly fail (regressions), cases that newly pass
(recoveries), and eval-set drift between old and new questions.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .cli import _ingest_folder  # reuse the same chunking path
from .evaltypes import CaseResult, EvalCase
from .judge import build_scorecard, judge_case
from .llm import Harness, OllamaBackend
from .report import _table
from .retrieve import HybridIndex
from .runner import ForgeAgent
from .spec import AgentDefinition


def run_regression(run_dir: Path, docs: Path, harness: Harness | None = None) -> str:
    from .evals import compile_evalset
    from .spec import RequirementsDoc

    req = RequirementsDoc.model_validate_json(
        (run_dir / "requirements.json").read_text(encoding="utf-8"))
    definition = AgentDefinition.model_validate_json(
        (run_dir / "definition.json").read_text(encoding="utf-8"))
    old_cases = [EvalCase.model_validate_json(line) for line in
                 (run_dir / "evalset.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    # rebuild index from the CURRENT docs state
    reg_dir = run_dir / "regression"
    reg_dir.mkdir(exist_ok=True)
    chunks, metas = _ingest_folder(docs, definition.retrieval.chunk_size,
                                    definition.retrieval.chunk_overlap)
    index_path = reg_dir / "index.sqlite"
    if index_path.exists():
        index_path.unlink()
    index = HybridIndex(index_path)
    backend = OllamaBackend()
    if backend.available():
        vectors = backend.embed([c.text for c in chunks])
        index.add_chunks(chunks, vectors)
    else:
        index.add_chunks(chunks)
    harness = harness or Harness(backend)
    agent = ForgeAgent(harness, index, definition)

    def eval_cases(cases: list[EvalCase]) -> list[CaseResult]:
        out = []
        for case in cases:
            resp = agent.answer(case.question)
            out.append(judge_case(harness, index, case, resp))
        return out

    old_results = {r.case_id: r for r in eval_cases(old_cases)}
    old_score = build_scorecard(list(old_results.values()), old_cases)

    prev = _load_prev_results(run_dir)
    L: list[str] = []
    L.append("# Regression Report")
    L.append("")
    L.append(f"Agent: {definition.name} (v{definition.version}) — docs rescanned from `{docs}`.")
    L.append("")
    L.append("## Old eval set against the current corpus")
    L.append("")
    L.append(_table(["passed", "total", "score", "95% CI"],
                    [[old_score.passed, old_score.total, f"{old_score.score:.0%}",
                      f"[{old_score.wilson_low:.0%}, {old_score.wilson_high:.0%}]"]]))
    L.append("")

    regressions, recoveries = [], []
    if prev:
        for case in old_cases:
            was, now = prev.get(case.id), old_results.get(case.id)
            if was is None or now is None:
                continue
            if was.passed and not now.passed:
                regressions.append([case.id, case.kind.value, case.question[:80],
                                    (now.failure_class.value if now.failure_class else "unclassified")])
            elif not was.passed and now.passed:
                recoveries.append([case.id, case.kind.value, case.question[:80]])
    L.append(f"## Regressions ({len(regressions)} cases now failing that passed before)")
    L.append("")
    if regressions:
        L.append(_table(["id", "kind", "question", "failure class"], regressions))
    else:
        L.append("None.")
    L.append("")
    L.append(f"## Recoveries ({len(recoveries)} cases now passing that failed before)")
    L.append("")
    if recoveries:
        L.append(_table(["id", "kind", "question"], recoveries))
    else:
        L.append("None.")
    L.append("")

    # eval-set drift: fresh compile from the changed corpus
    new_cases = compile_evalset(harness, index, req)
    (reg_dir / "evalset_new.jsonl").write_text(
        "\n".join(c.model_dump_json() for c in new_cases), encoding="utf-8")
    old_qs = {c.question for c in old_cases}
    drifted = [c.question[:80] for c in new_cases if c.question not in old_qs]
    L.append("## Eval-set drift")
    L.append("")
    L.append(f"New set: {len(new_cases)} cases; {len(drifted)} questions the old set "
             "did not contain (fresh generation from the changed corpus).")
    L.append("")
    L.append("---")
    L.append("")
    L.append("*Regression mode is the safety net for document churn: the old tests "
             "keep scoring the agent while the corpus moves underneath it.*")
    out = reg_dir / "regression.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out.read_text(encoding="utf-8")


def _load_prev_results(run_dir: Path) -> dict[str, CaseResult]:
    p = run_dir / "results.jsonl"
    if not p.exists():
        return {}
    return {r.case_id: r for r in
            (CaseResult.model_validate_json(line) for line in p.read_text(encoding="utf-8").splitlines()
             if line.strip())}
