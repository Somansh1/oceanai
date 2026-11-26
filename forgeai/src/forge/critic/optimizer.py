"""The critic-optimizer loop: evaluate -> triage -> ONE patch -> re-evaluate.

Rules that make it honest:
- max N iterations, early stop when marginal gain < min_gain
- the dominant failure class drives the patch; never regenerate
- every patch is a PatchRecord: what, why, which failures, score before/after
- the tournament picks the starting prompt on a pilot subset, logged
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from ..evaltypes import (CaseResult, CostLedger, EvalCase, FailureClass,
                         IterationScorecard, PatchRecord)
from ..spec import AgentDefinition

Evaluator = Callable[..., tuple[list[CaseResult], IterationScorecard]]


@dataclass
class IterationEntry:
    scorecard: IterationScorecard
    patches: list[PatchRecord] = field(default_factory=list)
    note: str = ""


@dataclass
class OptimizeResult:
    definition: AgentDefinition
    entries: list[IterationEntry]
    tournament_log: list[dict] = field(default_factory=list)
    stopped_early: bool = False
    budget_exhausted: bool = False
    final_results: list[CaseResult] = field(default_factory=list)
    final_scorecard: IterationScorecard | None = None


def _pilot_subset(cases: list[EvalCase], n: int = 5) -> list[EvalCase]:
    """Mixed pilot with TEETH: 3 answerable + 2 refusal-traps — an all-answerable
    pilot once scored every candidate 100% and chose nothing."""
    answerable = [c for c in cases if not c.expected_refusal][:3]
    traps = [c for c in cases if c.expected_refusal][:2]
    subset = answerable + traps
    return subset or cases[:n]


def _eval_subset(evaluator: Evaluator, defn: AgentDefinition,
                 cases: list[EvalCase]) -> tuple[list[CaseResult], IterationScorecard]:
    """Evaluates ONLY the pilot subset — the evaluator takes an optional case list."""
    return evaluator(defn, cases)


def tournament(evaluator: Evaluator, candidates: list[AgentDefinition],
               cases: list[EvalCase], pilot_n: int = 5) -> tuple[AgentDefinition, list[dict]]:
    pilot = _pilot_subset(cases, pilot_n)
    log: list[dict] = []
    best: AgentDefinition | None = None
    best_score = -1.0
    for cand in candidates:
        _, sc = _eval_subset(evaluator, cand, pilot)
        log.append({"candidate": cand.name, "pilot_score": sc.score,
                    "passed": sc.passed, "total": sc.total})
        if sc.score > best_score:
            best, best_score = cand, sc.score
    assert best is not None
    return best, log


def _budget_exceeded(ledger: CostLedger | None, max_tokens: int | None,
                     max_latency_ms: int | None) -> str | None:
    if ledger is None:
        return None
    totals = ledger.totals()
    used_tokens = totals["in_tokens"] + totals["out_tokens"]
    if max_tokens is not None and used_tokens >= max_tokens:
        return f"token budget reached ({used_tokens:,} >= {max_tokens:,})"
    if max_latency_ms is not None and totals["latency_ms"] >= max_latency_ms:
        return f"latency budget reached ({totals['latency_ms']/1000:.1f}s >= {max_latency_ms/1000:.1f}s)"
    return None


def optimize(evaluator: Evaluator, definition: AgentDefinition, cases: list[EvalCase],
             candidates: list[AgentDefinition] | None = None,
             max_iterations: int = 3, min_gain: float = 0.03,
             ledger: CostLedger | None = None, max_tokens: int | None = None,
             max_latency_ms: int | None = None) -> OptimizeResult:
    tournament_log: list[dict] = []
    if candidates and len(candidates) > 1:
        definition, tournament_log = tournament(evaluator, candidates, cases)
        tournament_log.append({"note": "winner selected on pilot subset before iteration 0"})

    entries: list[IterationEntry] = []
    applied_patches: set[tuple[FailureClass, str]] = set()
    recent_gains: list[float] = []   # per-patch gains for patient early-stop
    stopped_early = False
    budget_exhausted = False

    results, sc = evaluator(definition)
    definition.iteration = 0

    for i in range(max_iterations + 1):
        sc_iter = sc.model_copy(update={"iteration": i})
        entry = IterationEntry(scorecard=sc_iter)
        entries.append(entry)

        if sc.score >= 1.0:
            entry.note = "all cases pass — stopping"
            break
        if i == max_iterations:
            entry.note = "iteration budget exhausted"
            break
        budget_msg = _budget_exceeded(ledger, max_tokens, max_latency_ms)
        if budget_msg:
            entry.note = f"early stop: {budget_msg}"
            stopped_early = True
            budget_exhausted = True
            break
        # patient early-stop: TWO consecutive patches must fail to pay for
        # themselves before we quit — one unlucky patch never ends the loop
        if len(recent_gains) >= 2 and all(g < min_gain for g in recent_gains[-2:]):
            entry.note = (f"early stop: last two patches gained "
                          f"{recent_gains[-2]:+.3f}, {recent_gains[-1]:+.3f} — "
                          f"both below {min_gain}")
            stopped_early = True
            break

        from .patches import PATCH_LIBRARY, select_prompt_defect_patch

        ranking = sorted(sc.by_failure.items(), key=lambda kv: -kv[1])
        target_class = None
        patch_fn = None
        for cls_name, _count in ranking:
            try:
                fc = FailureClass(cls_name)
            except ValueError:
                continue
            if fc in (FailureClass.JUDGE_UNSTABLE, FailureClass.UNEXPLAINED):
                continue
            if fc == FailureClass.PROMPT_DEFECT:
                cls_fails = [r for r in results if not r.passed and r.failure_class == fc]
                cand_fn = select_prompt_defect_patch(definition, cls_fails)
            else:
                cand_fn = PATCH_LIBRARY.get(fc)
            if cand_fn is None or (fc, cand_fn.__name__) in applied_patches:
                continue
            target_class = fc
            patch_fn = cand_fn
            break
        if target_class is None or patch_fn is None:
            entry.note = "no patchable failure class remains (all already patched)"
            break

        failing_ids = [r.case_id for r in results
                       if not r.passed and r.failure_class == target_class]
        snapshot = definition.model_copy(deep=True)
        change = patch_fn(definition)
        applied_patches.add((target_class, patch_fn.__name__))
        definition.version += 1

        t0 = time.time()
        results2, sc2 = evaluator(definition)
        delta = sc2.score - sc.score
        rolled_back = False
        if sc2.score < sc.score:
            # Never keep a patch that degraded performance
            definition = snapshot
            rolled_back = True
            change = f"{change} [ROLLED BACK: score dropped {sc.score:.0%} -> {sc2.score:.0%}]"

        target_label = "retrieval" if target_class == FailureClass.RETRIEVAL_MISS else "system_prompt"
        pr = PatchRecord(
            iteration=i, failure_class=target_class, target=target_label,
            change=change,
            rationale=(f"dominant failure class {target_class.value} "
                       f"({sc.by_failure.get(target_class.value, 0)} cases)"),
            failure_ids=failing_ids, score_before=sc.score, score_after=sc2.score,
            rolled_back=rolled_back)
        entry.patches.append(pr)
        definition.iteration = i + 1
        recent_gains.append(delta)

        if rolled_back:
            entries.append(IterationEntry(scorecard=sc2, patches=[],
                                          note=f"post-patch re-eval rejected & rolled back ({time.time()-t0:.0f}s)"))
            # Keep pre-patch (results, sc) for next iteration
        else:
            results, sc = results2, sc2
            if sc2.score >= 1.0:
                entries.append(IterationEntry(scorecard=sc2, patches=[],
                                              note="all cases pass after patch — stopping"))
                break

    return OptimizeResult(definition=definition, entries=entries,
                          tournament_log=tournament_log, stopped_early=stopped_early,
                          budget_exhausted=budget_exhausted,
                          final_results=results, final_scorecard=sc)
