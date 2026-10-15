"""Tests for market overview real-time index quotes, breadth, and cross-platform resilience."""

import pytest
from easy_tdx.market_overview import (
    _fetch_live_indices_and_market,
    _get_yesterday_turnover_yi,
    _build_market_summary,
)


def test_yesterday_turnover():
    """Verify yesterday turnover returns a valid positive value in 100M (亿)."""
    val = _get_yesterday_turnover_yi("2026-10-15")
    assert isinstance(val, float)
    assert val > 1000.0


def test_fetch_live_indices_structure():
    """Verify major indices contain valid prices, non-dummy pre_close, and breadth."""
    res = _fetch_live_indices_and_market()
    assert "major_indices" in res
    assert len(res["major_indices"]) == 5

    target_codes = {"000001", "399001", "399006", "000688", "000300"}
    returned_codes = {idx["code"] for idx in res["major_indices"]}
    assert target_codes == returned_codes

    for idx in res["major_indices"]:
        assert idx["close"] > 0, f"Index {idx['code']} close should be > 0"
        assert idx["pre_close"] > 0, f"Index {idx['code']} pre_close should be > 0"
        assert idx["amount_yi"] >= 0, f"Index {idx['code']} amount_yi should be >= 0"
        # If price changed significantly from pre_close, change_pct must not be 0.0
        if abs(idx["close"] - idx["pre_close"]) > 0.5:
            assert idx["change_pct"] != 0.0, f"Index {idx['code']} change_pct should reflect price difference"

    # Breadth should not be completely 0
    assert res["up_count"] > 0 or res["down_count"] > 0
    assert res["total_turnover_yi"] > 1000.0


def test_build_market_summary():
    """Verify market summary calculation produces valid sentiment and turnover."""
    summary = _build_market_summary()
    assert summary["status"] == "success"
    assert "sentiment" in summary
    assert 0 <= summary["sentiment"]["score"] <= 100
    assert "turnover" in summary
    assert summary["turnover"]["total_yi"] > 1000.0
    assert "breadth" in summary
    assert summary["breadth"]["ratio"] >= 0
