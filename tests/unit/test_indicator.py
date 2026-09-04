"""indicator.py 离线单元测试。"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from easy_tdx.indicator import _REGISTRY, compute_indicators, list_indicators


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    high = close + np.abs(rng.standard_normal(n))
    low = close - np.abs(rng.standard_normal(n))
    open_ = low + (high - low) * rng.random(n)
    vol = (rng.random(n) * 1e6).astype(float)
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n, freq="D"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": vol * close,
        }
    )


class TestRegistry:
    def test_all_indicators_registered(self):
        assert len(_REGISTRY) >= 22

    def test_list_indicators_returns_metadata(self):
        info = list_indicators()
        assert len(info) >= 22
        for entry in info:
            assert "name" in entry
            assert "inputs" in entry
            assert "outputs" in entry
            assert "description" in entry


class TestComputeIndicators:
    def test_single_indicator_macd(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["MACD"])
        assert "MACD_DIF" in result.columns
        assert "MACD_DEA" in result.columns
        assert "MACD_HIST" in result.columns
        assert len(result) == 200

    def test_multiple_indicators(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["MACD", "KDJ", "RSI"])
        for col in ["MACD_DIF", "MACD_DEA", "MACD_HIST", "KDJ_K", "KDJ_D", "KDJ_J", "RSI"]:
            assert col in result.columns

    def test_keep_ohlcv_true(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["RSI"], keep_ohlcv=True)
        for col in ["open", "high", "low", "close", "vol"]:
            assert col in result.columns

    def test_keep_ohlcv_false(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["RSI"], keep_ohlcv=False)
        assert "close" not in result.columns
        assert "RSI" in result.columns
        # datetime 应保留
        assert "datetime" in result.columns

    def test_keep_ohlcv_false_no_time_cols(self):
        df = _make_ohlcv()
        df = df.drop(columns=["datetime"])
        result = compute_indicators(df, ["RSI"], keep_ohlcv=False)
        assert "close" not in result.columns
        assert "RSI" in result.columns

    def test_tail_parameter(self):
        df = _make_ohlcv(200)
        result = compute_indicators(df, ["MACD"], tail=30)
        assert len(result) == 30
        assert "MACD_DIF" in result.columns

    def test_case_insensitive(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["macd", "kdj"])
        assert "MACD_DIF" in result.columns
        assert "KDJ_K" in result.columns

    def test_custom_params(self):
        df = _make_ohlcv()
        r1 = compute_indicators(df, ["MACD"])
        r2 = compute_indicators(df, ["MACD"], params={"MACD": {"SHORT": 10}})
        # 不同参数应产生不同结果
        assert not np.allclose(r1["MACD_DIF"].values, r2["MACD_DIF"].values, equal_nan=True)

    def test_unknown_indicator_raises(self):
        df = _make_ohlcv()
        with pytest.raises(ValueError, match="未知指标"):
            compute_indicators(df, ["FAKE_INDICATOR"])

    def test_missing_input_columns_raises(self):
        df = pd.DataFrame({"close": np.random.randn(200)})
        with pytest.raises(ValueError, match="缺少必要列"):
            compute_indicators(df, ["KDJ"])

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = compute_indicators(df, ["MACD"])
        assert result.empty

    def test_short_data_warning(self):
        df = _make_ohlcv(50)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compute_indicators(df, ["MACD"])
            assert any("120" in str(warning.message) for warning in w)

    def test_rsi_range(self):
        df = _make_ohlcv(200)
        result = compute_indicators(df, ["RSI"])
        rsi = result["RSI"].dropna()
        assert (rsi >= -10).all() and (rsi <= 110).all()

    def test_boll_bands_order(self):
        df = _make_ohlcv(200)
        result = compute_indicators(df, ["BOLL"])
        valid = result.dropna(subset=["BOLL_UPPER", "BOLL_LOWER"])
        assert (valid["BOLL_UPPER"] >= valid["BOLL_LOWER"]).all()

    def test_obv_with_volume(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["OBV"])
        assert "OBV" in result.columns

    def test_brar_needs_open(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["BRAR"])
        assert "AR" in result.columns
        assert "BR" in result.columns

    def test_all_registered_indicators_run(self):
        """确保所有注册的指标都能无错运行。"""
        df = _make_ohlcv(250)
        for name in _REGISTRY:
            result = compute_indicators(df, [name])
            spec = _REGISTRY[name]
            for col in spec.outputs:
                assert col in result.columns, f"{name} missing output {col}"

    def test_result_index_reset(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["RSI"])
        assert list(result.index) == list(range(len(result)))

    def test_zig_indicator(self):
        df = _make_ohlcv(200)
        result = compute_indicators(df, ["ZIG"])
        assert "ZIG" in result.columns
        assert len(result) == 200
        assert np.isfinite(result["ZIG"]).all()

    def test_backset(self):
        from easy_tdx.MyTT import BACKSET
        s = np.array([False, False, False, True, False])
        res = BACKSET(s, 3)
        # s[3] is True, N=3 -> indices 1, 2, 3 should be True
        assert not res[0]
        assert res[1] and res[2] and res[3]
        assert not res[4]

    def test_td_sequential_nine(self):
        from easy_tdx.MyTT import TD_SEQUENTIAL
        # Monotonically increasing close prices -> C > C[i-4]
        c = np.arange(1, 20, dtype=float)
        td_high, td_low = TD_SEQUENTIAL(c, 9)
        # Indices 4 to 12 form 1..9 sequence
        assert td_high[12] == 9
        assert list(td_high[4:13]) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert td_low.sum() == 0

    def test_td_sequential_thirteen(self):
        from easy_tdx.MyTT import TD_SEQUENTIAL
        c = np.arange(1, 25, dtype=float)
        td_high, td_low = TD_SEQUENTIAL(c, 13)
        assert td_high[16] == 13
        assert list(td_high[4:17]) == list(range(1, 14))

