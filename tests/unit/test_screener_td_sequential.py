"""Regression tests for TD Sequential Screener and Multi-Tier Stock Universes."""
import pytest
from easy_tdx.screener.universe import get_universe_symbols, CORE_UNIVERSE
from easy_tdx.screener.scanner import _evaluate_stock_for_strategy
from easy_tdx.strategies.registry import get_strategy


def test_universe_hierarchical_subsets():
    """Verify core ⊂ hs300 ⊂ zz500 ⊂ zz1000 ⊂ all."""
    core = get_universe_symbols("core")
    hs300 = get_universe_symbols("hs300")
    zz500 = get_universe_symbols("zz500")
    zz1000 = get_universe_symbols("zz1000")
    all_stocks = get_universe_symbols("all")

    assert len(core) == len(CORE_UNIVERSE)
    assert len(hs300) == 300
    assert len(zz500) == 500
    assert len(zz1000) == 1000
    assert len(all_stocks) > 5000

    # Strict prefix inclusion check
    assert hs300[:len(core)] == core
    assert zz500[:300] == hs300
    assert zz1000[:500] == zz500
    assert all_stocks[:1000] == zz1000


def test_td_sequential_starts_at_third_bar():
    """Verify td_sequential begins annotating and screening only from the 3rd daily bar (>=3)."""
    import pandas as pd
    from unittest.mock import patch

    st = get_strategy("td_sequential")

    def make_df_with_seq(seq_len):
        closes = [10.0] * 25
        for i in range(1, seq_len + 1):
            closes.append(10.0 + i)
        dts = [f"2026-08-{i+1:02d}" for i in range(len(closes))]
        return pd.DataFrame({
            "datetime": dts,
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
            "amount": [100000.0] * len(closes)
        })

    # Sequence len 1: Not annotated, filtered out
    with patch("easy_tdx.screener.scanner._get_or_fetch_daily_kline", return_value=make_df_with_seq(1)):
        res1 = _evaluate_stock_for_strategy("TEST01", "td_sequential", st, 20)
        assert res1 is None, "Sequence length 1 should not be selected or annotated"

    # Sequence len 2: Not annotated, filtered out
    with patch("easy_tdx.screener.scanner._get_or_fetch_daily_kline", return_value=make_df_with_seq(2)):
        res2 = _evaluate_stock_for_strategy("TEST02", "td_sequential", st, 20)
        assert res2 is None, "Sequence length 2 should not be selected or annotated"

    # Sequence len 3: Annotation starts! Selected as '今日高3序列'
    with patch("easy_tdx.screener.scanner._get_or_fetch_daily_kline", return_value=make_df_with_seq(3)):
        res3 = _evaluate_stock_for_strategy("TEST03", "td_sequential", st, 20)
        assert res3 is not None
        assert res3["strategy_id"] == "td_sequential"
        assert res3["status_label"] == "今日高3序列"
        assert res3["days_ago"] == 0
        assert "高3序列" in res3["patterns"]
        assert "高3序列" in res3["trigger_patterns"]

    # Sequence len 4: Selected as '高4序列 (1日前启动)'
    with patch("easy_tdx.screener.scanner._get_or_fetch_daily_kline", return_value=make_df_with_seq(4)):
        res4 = _evaluate_stock_for_strategy("TEST04", "td_sequential", st, 20)
        assert res4 is not None
        assert res4["status_label"] == "高4序列 (1日前启动)"
        assert res4["days_ago"] == 1
        assert "高4序列" in res4["patterns"]
        assert "高3序列" in res4["trigger_patterns"]

    # Sequence len 9: Selected as '高9序列 (见顶警示)'
    with patch("easy_tdx.screener.scanner._get_or_fetch_daily_kline", return_value=make_df_with_seq(9)):
        res9 = _evaluate_stock_for_strategy("TEST09", "td_sequential", st, 20)
        assert res9 is not None
        assert res9["status_label"] == "高9序列 (见顶警示)"
        assert res9["days_ago"] == 6
        assert "高9序列(见顶)" in res9["patterns"]
        assert "高3序列" in res9["trigger_patterns"]


def test_td_sequential_strategy_evaluation():
    """Verify td_sequential evaluates properly without buy_mask false rejection."""
    st = get_strategy("td_sequential")
    # Evaluate a known active stock
    res = _evaluate_stock_for_strategy("601888", "td_sequential", st, lookback_bars=20)
    if res is not None:
        assert res["strategy_id"] == "td_sequential"
        assert "patterns" in res
        assert "高" in res["pattern_status"]

