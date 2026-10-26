"""Unit tests for 5F bar count increase (12000 bars) and new stock fault tolerance."""
import pathlib
import tempfile
import pytest
import pandas as pd
import numpy as np

from easy_tdx.chanlun.resonance import analyze_multi_period_resonance
from easy_tdx.kline_cache import KlineDiskCache
from easy_tdx.market_data import KlineCategory


def _generate_synthetic_5f_bars(n_bars: int) -> pd.DataFrame:
    """Generate n synthetic 5-minute bars."""
    dates = pd.date_range("2026-01-01 09:30", periods=n_bars, freq="5min")
    base_price = 10.0 + np.sin(np.linspace(0, 10, n_bars))
    return pd.DataFrame({
        "datetime": [d.strftime("%Y-%m-%d %H:%M") for d in dates],
        "open": base_price,
        "high": base_price + 0.1,
        "low": base_price - 0.1,
        "close": base_price + 0.05,
        "volume": [1000] * n_bars,
        "amount": [10000.0] * n_bars,
    })


def test_kline_disk_cache_5f_preserves_12000_bars():
    """Verify KlineDiskCache preserves up to 16000 bars for 5F (not truncated to 5000)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = KlineDiskCache(cache_dir=tmp_dir)
        df_12k = _generate_synthetic_5f_bars(12000)

        cache.write_cached("000001", "5F", df_12k, "QFQ")
        cached = cache.read_cached("000001", "5F", "QFQ")

        assert cached is not None
        assert len(cached) == 12000


def test_kline_disk_cache_new_stock_full_history_flag():
    """Verify new stock full_history flag is saved in attrs and meta.json, and preserved in merge_and_update."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = KlineDiskCache(cache_dir=tmp_dir)
        # New stock has only 350 bars
        df_new_stock = _generate_synthetic_5f_bars(350)
        df_new_stock.attrs["full_history"] = True

        cache.write_cached("688999", "5F", df_new_stock, "QFQ")
        read_df = cache.read_cached("688999", "5F", "QFQ")

        assert read_df is not None
        assert len(read_df) == 350
        assert read_df.attrs.get("full_history") is True

        # Incremental merge should retain full_history flag
        delta_df = _generate_synthetic_5f_bars(5)
        merged = cache.merge_and_update("688999", "5F", read_df, delta_df, "QFQ")
        assert merged.attrs.get("full_history") is True


def test_analyze_multi_period_resonance_new_stock_few_bars():
    """Verify analyze_multi_period_resonance succeeds safely when stock has only a few bars (new stock tolerance)."""
    from unittest.mock import patch

    # Stock with only 30 bars of 5F
    synthetic_5f = _generate_synthetic_5f_bars(30)
    synthetic_day = pd.DataFrame({
        "datetime": ["2026-01-01"],
        "open": [10.0],
        "high": [11.0],
        "low": [9.5],
        "close": [10.5],
        "volume": [10000],
        "amount": [100000.0],
    })

    def fake_fetch_kline(clean_code, category, count, force_refresh=False):
        if category in (KlineCategory.MIN_5, "5F", "5M"):
            return synthetic_5f.copy()
        return synthetic_day.copy()

    with patch("easy_tdx.chanlun.resonance.fetch_security_kline", side_effect=fake_fetch_kline):
        result = analyze_multi_period_resonance(
            code="301999",
            periods="DAY,30F,5F",
            count=300,
            force_refresh=True,
        )

    assert result["status"] == "success"
    assert "unified_chart" in result
    assert result["unified_chart"]["dates"] == synthetic_5f["datetime"].tolist()


def test_analyze_multi_period_resonance_zero_bars_tolerance():
    """Verify analyze_multi_period_resonance returns standard empty structure without crashing on 0 bars."""
    from unittest.mock import patch

    empty_df = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])

    with patch("easy_tdx.chanlun.resonance.fetch_security_kline", return_value=empty_df):
        result = analyze_multi_period_resonance(
            code="009999",
            periods="DAY,30F,5F",
            count=300,
            force_refresh=True,
        )

    assert result["status"] == "success"
    assert result["unified_chart"]["dates"] == []
    assert result["unified_chart"]["candles"] == []
    assert result["backtrack_timeline"]["total_bars"] == 0
