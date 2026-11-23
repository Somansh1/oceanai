"""The judge: deterministic L0 + micro-binary L1 + derived failure classes."""
from .judge import build_scorecard, judge_case, pair_consistency
from .stats import wilson_interval

__all__ = ["build_scorecard", "judge_case", "pair_consistency", "wilson_interval"]
