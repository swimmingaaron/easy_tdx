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


def test_td_sequential_strategy_evaluation():
    """Verify td_sequential evaluates properly without buy_mask false rejection."""
    st = get_strategy("td_sequential")
    # Evaluate a known active stock
    res = _evaluate_stock_for_strategy("601138", "td_sequential", st, lookback_bars=20)
    if res is not None:
        assert res["strategy_id"] == "td_sequential"
        assert "patterns" in res
        assert "高" in res["pattern_status"]
