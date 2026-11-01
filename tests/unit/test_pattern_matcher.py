"""Unit tests for pattern matcher quantitative screener."""
from __future__ import annotations

import numpy as np
import pytest

from easy_tdx.screener.pattern_matcher import (
    normalize_min_max,
    calc_pearson_correlation,
    calc_composite_similarity,
    search_pattern_matches,
)


def test_normalize_min_max():
    arr = np.array([10.0, 20.0, 30.0])
    norm = normalize_min_max(arr)
    assert norm == [0.0, 50.0, 100.0]

    # Empty array
    assert normalize_min_max([]) == []

    # Flat array
    assert normalize_min_max([5.0, 5.0, 5.0]) == [50.0, 50.0, 50.0]


def test_calc_pearson_correlation():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
    r = calc_pearson_correlation(x, y)
    assert pytest.approx(r, 0.001) == 1.0

    # Negative correlation
    y_neg = np.array([10.0, 8.0, 6.0, 4.0, 2.0])
    r_neg = calc_pearson_correlation(x, y_neg)
    assert pytest.approx(r_neg, 0.001) == -1.0


def test_composite_similarity():
    x = np.array([10.0, 9.5, 9.2, 10.5, 11.2, 12.0, 11.5, 13.0])

    # 1. Identical pattern must score 100.0
    score_self, details_self = calc_composite_similarity(x, x)
    assert score_self == 100.0
    assert details_self["corr"] == 100.0
    assert details_self["geom"] == 100.0
    assert details_self["scale"] == 100.0
    assert details_self["turning"] == 100.0

    # 2. Highly similar with proportional amplitude should score > 90.0
    y_sim = np.array([20.0, 19.2, 18.5, 21.0, 22.1, 23.8, 23.0, 25.5])
    score_sim, details_sim = calc_composite_similarity(x, y_sim)
    assert score_sim >= 90.0
    assert details_sim["corr"] >= 95.0

    # 3. Same direction but flat movement (< 0.1% amplitude) must be heavily penalized
    y_flat = np.array([10.0, 9.99, 9.98, 10.01, 10.02, 10.03, 10.02, 10.05])
    score_flat, details_flat = calc_composite_similarity(x, y_flat)
    assert score_flat < 30.0  # heavily penalized for lack of momentum
    assert details_flat["scale"] < 10.0

    # 4. Opposite direction must score 0.0
    y_opp = np.array([13.0, 11.5, 12.0, 11.2, 10.5, 9.2, 9.5, 8.0])
    score_opp, _ = calc_composite_similarity(x, y_opp)
    assert score_opp == 0.0


def test_search_pattern_matches_execution():
    prices = [10.0, 9.8, 9.5, 10.2, 11.0, 11.8, 11.5, 12.5]
    future_prices = [13.0, 13.5, 14.0]
    res = search_pattern_matches(
        target_prices=prices,
        target_symbol="600519",
        universe="core",
        period="DAY",
        top_n=5,
        min_similarity=50.0,
        target_future_prices=future_prices,
    )
    assert res["status"] == "success"
    assert res["target_symbol"] == "600519"
    assert res["target_stats"]["target_ret"] > 0
    assert res["target_future_stats"] is not None
    assert res["target_future_stats"]["future_ret"] > 0
    assert "matches" in res
    assert isinstance(res["matches"], list)
