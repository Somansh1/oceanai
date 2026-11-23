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

from ..evaltypes import (CaseResult, EvalCase, FailureClass, IterationScorecard,
                         PatchRecord)
from ..judge import build_scorecard
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


def optimize(evaluator: Evaluator, definition: AgentDefinition, cases: list[EvalCase],
             candidates: list[AgentDefinition] | None = None,
             max_iterations: int = 3, min_gain: float = 0.03) -> OptimizeResult:
    tournament_log: list[dict] = []
    if candidates and len(candidates) > 1:
        definition, tournament_log = tournament(evaluator, candidates, cases)
        tournament_log.append({"note": "winner selected on pilot subset before iteration 0"})

    entries: list[IterationEntry] = []
    applied: set[FailureClass] = set()
    recent_gains: list[float] = []   # per-patch gains for patient early-stop
    stopped_early = False

    for i in range(max_iterations + 1):
        results, sc = evaluator(definition)
        entry = IterationEntry(scorecard=sc)
        definition.iteration = i
        entries.append(entry)

        if sc.score >= 1.0:
            entry.note = "all cases pass — stopping"
            break
        if i == max_iterations:
            entry.note = "iteration budget exhausted"
            break
        # patient early-stop: TWO consecutive patches must fail to pay for
        # themselves before we quit — one unlucky patch never ends the loop
        if len(recent_gains) >= 2 and all(g < min_gain for g in recent_gains[-2:]):
            entry.note = (f"early stop: last two patches gained "
                          f"{recent_gains[-2]:+.3f}, {recent_gains[-1]:+.3f} — "
                          f"both below {min_gain}")
            stopped_early = True
            break

        ranking = sorted(sc.by_failure.items(), key=lambda kv: -kv[1])
        target_class = None
        for cls_name, _count in ranking:
            try:
                fc = FailureClass(cls_name)
            except ValueError:
                continue
            if fc in applied or fc in (FailureClass.JUDGE_UNSTABLE, FailureClass.UNEXPLAINED):
                continue
            target_class = fc
            break
        if target_class is None:
            entry.note = "no patchable failure class remains (all already patched)"
            break

        from .patches import PATCH_LIBRARY
        patch_fn = PATCH_LIBRARY.get(target_class)
        if patch_fn is None:
            entry.note = f"no patch available for {target_class.value}"
            break

        failing_ids = [r.case_id for r in results
                       if not r.passed and r.failure_class == target_class]
        change = patch_fn(definition)
        applied.add(target_class)
        definition.version += 1

        t0 = time.time()
        results2, sc2 = evaluator(definition)
        pr = PatchRecord(
            iteration=i, failure_class=target_class, target="system_prompt/retrieval",
            change=change,
            rationale=(f"dominant failure class {target_class.value} "
                       f"({sc.by_failure.get(target_class.value, 0)} cases)"),
            failure_ids=failing_ids, score_before=sc.score, score_after=sc2.score)
        entry.patches.append(pr)
        entries.append(IterationEntry(scorecard=sc2, patches=[],
                                      note=f"post-patch re-eval ({time.time()-t0:.0f}s)"))
        definition.iteration = i + 1
        recent_gains.append(sc2.score - sc.score)
        if sc2.score >= 1.0:
            entries[-1].note = "all cases pass after patch — stopping"
            break

    return OptimizeResult(definition=definition, entries=entries,
                          tournament_log=tournament_log, stopped_early=stopped_early)
