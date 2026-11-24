"""Unit tests for statistical calculations and confidence intervals."""
from __future__ import annotations

import pytest
from forge.judge.stats import wilson_interval


def test_wilson_interval_zero_total():
    low, high = wilson_interval(0, 0)
    assert low == 0.0
    assert high == 1.0


def test_wilson_interval_all_passed():
    low, high = wilson_interval(20, 20)
    assert 0.80 < low < 1.0
    assert high == pytest.approx(1.0, abs=1e-5)


def test_wilson_interval_none_passed():
    low, high = wilson_interval(0, 20)
    assert low == 0.0
    assert 0.0 < high < 0.20


def test_wilson_interval_bounds_and_symmetry():
    low, high = wilson_interval(10, 20)
    assert 0.0 <= low <= high <= 1.0
    # Symmetric 50% split should have interval centered around 0.5
    assert abs((low + high) / 2.0 - 0.5) < 0.01


def test_wilson_interval_widens_with_smaller_sample():
    low_small, high_small = wilson_interval(5, 10)
    low_large, high_large = wilson_interval(50, 100)
    span_small = high_small - low_small
    span_large = high_large - low_large
    assert span_small > span_large
