"""Layered judge.

L0 deterministic: citation validity, refusal flag, numeric recompute, retrieval
telemetry. L1 micro-binary: one yes/no per (expected fact, answer) pair — the
small model only ever answers binary questions. Failure classes are DERIVED
from telemetry by a decision procedure, never guessed.
"""
from __future__ import annotations

import re

from ..evaltypes import CaseKind, CaseResult, EvalCase, FailureClass, IterationScorecard
from ..llm import Harness
from ..retrieve import HybridIndex
from ..runner.engine import AgentResponse
from .stats import wilson_interval

_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")

# refused-in-substance: the answer states the information is absent rather
# than setting refused=true. Deterministic phrase check — no model opinion.
_SOFT_REFUSAL = re.compile(
    r"(does not specify|does not mention|not specified in|not covered by|"
    r"no (policy|information|provision|mention) (is )?(given|specified|found|available)|"
    r"(policy|documents?|information) (does|do) not (specify|cover|mention|address)|"
    r"cannot find|could not find|no details?( are)? (given|provided|available)|"
    r"is not (specified|mentioned|covered|addressed))",
    re.IGNORECASE,
)


def _soft_refusal(answer: str) -> bool:
    return bool(_SOFT_REFUSAL.search(answer or ""))


def _numbers_in(text: str) -> list[float]:
    return [float(m.replace(",", ".")) for m in _NUM.findall(text or "")]


def _numeric_ok(answer: str, expected: float, tol_rel: float = 0.02) -> bool | None:
    nums = _numbers_in(answer)
    if not nums:
        return None
    return any(abs(n - expected) <= tol_rel * max(abs(expected), 1e-9) for n in nums)


def judge_case(harness: Harness, index: HybridIndex, case: EvalCase,
               resp: AgentResponse) -> CaseResult:
    # ---- L0 deterministic ----
    all_ids = set(index.all_chunk_ids())
    cited_valid = all(c in all_ids for c in resp.citations) if resp.citations else True
    expected_retrieved = (any(e in resp.retrieved_chunk_ids for e in case.expected_chunk_ids)
                          if case.expected_chunk_ids else None)
    numeric_ok = (_numeric_ok(resp.answer, case.expected_value)
                  if case.expected_value is not None else None)

    # ---- L1 micro-binary fact coverage ----
    fact_matches: dict[str, bool] = {}
    if case.expected_facts and not resp.refused:
        for fact in case.expected_facts:
            prompt, sha = harness.prompts.render("08_fact_match", fact=fact,
                                                 excerpt=resp.answer[:3000] or "(empty answer)")
            fact_matches[fact] = harness.yes_no(prompt, stage="judge_l1", prompt_sha=sha)
    coverage = (sum(fact_matches.values()) / len(fact_matches)) if fact_matches else 0.0

    # ---- pass/fail ----
    soft = _soft_refusal(resp.answer) if case.expected_refusal else False
    grounded_reframe = False
    if case.expected_refusal:
        if resp.refused or soft:
            passed = (not resp.citations or cited_valid)
        else:
            # grounded-reframe check: the agent answered a trap using only verified
            # cited facts (e.g. answered a gender-premise trap with the doc's real
            # primary/secondary distinction). Verify each answer sentence against
            # the CITED chunks — no invention means no hallucination.
            cited_chunks = [index.get_chunk(c) for c in resp.citations if index.get_chunk(c)]
            if cited_chunks and cited_valid:
                ctx = "\n\n---\n\n".join(c.text[:2500] for c in cited_chunks)
                all_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", resp.answer)
                                 if len(s.strip()) > 25][:4]
                # scoping statements ("the policy does not differentiate between
                # male and female employees") are claims-of-absence — strict
                # entailment cannot verify absence. They are accepted as the
                # soft-refusal component; the POSITIVE sentences must atom-verify.
                neg = re.compile(
                    r"does not (differentiate|distinguish|specify|mention|provide|"
                    r"address|contain|apply)", re.IGNORECASE)
                pos_sentences = [s for s in all_sentences if not neg.search(s)]
                if pos_sentences:
                    checks = []
                    for s in pos_sentences:
                        p, sh = harness.prompts.render("08_fact_match", fact=s,
                                                       excerpt=ctx[:3000])
                        checks.append(harness.yes_no(p, stage="judge_reframe",
                                                     prompt_sha=sh))
                    grounded_reframe = all(checks)
            passed = grounded_reframe
    else:
        passed = (
            not resp.refused
            and cited_valid
            and (expected_retrieved is not False)
            and coverage >= 0.99
            and (numeric_ok is not False)
            and not resp.parse_failed
        )

    result = CaseResult(
        case_id=case.id, refused=resp.refused, answer=resp.answer[:2000],
        citations=resp.citations, retrieved_chunk_ids=resp.retrieved_chunk_ids,
        expected_retrieved=expected_retrieved, cited_valid=cited_valid,
        fact_matches=fact_matches, fact_coverage=round(coverage, 3),
        numeric_ok=numeric_ok, passed=passed, parse_failed=resp.parse_failed,
        soft_refusal=soft, grounded_reframe=grounded_reframe,
    )
    result.failure_class = classify_failure(case, result)
    return result


def classify_failure(case: EvalCase, r: CaseResult) -> FailureClass | None:
    """Decision procedure — the failure class FALLS OUT of the telemetry."""
    if r.passed:
        return None
    if case.expected_refusal:
        if r.refused:
            # refused correctly; the only way to fail here is citation discipline
            return FailureClass.PROMPT_DEFECT
        # should refuse but answered -> hallucination by definition
        return FailureClass.HALLUCINATION
    if r.refused:
        return FailureClass.WRONG_REFUSAL
    if r.expected_retrieved is False:
        return FailureClass.RETRIEVAL_MISS
    if r.parse_failed or r.cited_valid is False:
        return FailureClass.PROMPT_DEFECT
    if r.numeric_ok is False:
        return FailureClass.HALLUCINATION
    if r.fact_coverage < 0.99:
        # omission vs invention: mostly-complete answers are incomplete prompting;
        # mostly-missing answers are fabrication
        return FailureClass.HALLUCINATION if r.fact_coverage < 0.5 else FailureClass.PROMPT_DEFECT
    return FailureClass.UNEXPLAINED


def pair_consistency(harness: Harness, a: CaseResult, b: CaseResult) -> bool | None:
    """Rephrase stability: same substance under different phrasing."""
    if not a or not b or a.refused != b.refused:
        return False
    if a.refused:
        return True
    prompt, sha = harness.prompts.render("11_pair_consistency",
                                         answer_a=a.answer[:1500], answer_b=b.answer[:1500])
    return harness.yes_no(prompt, stage="judge_pair", prompt_sha=sha)


def build_scorecard(results: list[CaseResult], cases: list[EvalCase],
                    iteration: int = 0) -> IterationScorecard:
    by_id = {c.id: c for c in cases}
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    low, high = wilson_interval(passed, total)
    by_kind: dict[str, int] = {}
    by_failure: dict[str, int] = {}
    for r in results:
        if not r.passed:
            kind = by_id[r.case_id].kind.value if r.case_id in by_id else "unknown"
            by_kind[kind] = by_kind.get(kind, 0) + 1
            fc = r.failure_class.value if r.failure_class else "unclassified"
            by_failure[fc] = by_failure.get(fc, 0) + 1
    return IterationScorecard(iteration=iteration, total=total, passed=passed,
                              score=round(passed / total, 4) if total else 0.0,
                              wilson_low=round(low, 4), wilson_high=round(high, 4),
                              by_class=by_kind, by_failure=by_failure)
