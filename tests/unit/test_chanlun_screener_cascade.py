"""Unit tests for Chanlun 4-tier cascading period screener presets and evaluation."""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd

from easy_tdx.screener.scanner import (
    parse_chanlun_screener_preset,
    CHANLUN_PERIOD_PRESETS,
    _evaluate_stock_for_strategy,
    _is_top_sell_downtrend,
)
from easy_tdx.strategies.registry import get_strategy
from easy_tdx.web.routers.screener import ScreenerScanRequest, ScreenerTaskStartRequest


def test_parse_chanlun_screener_preset_definitions():
    """Verify all 4 presets match the user's explicit specification."""
    # 1. 30F 5F 1F
    p1 = parse_chanlun_screener_preset("30F_5F_1F")
    assert p1["periods"] == ["30F", "5F", "1F"]
    assert p1["high_period"] == "30F"
    assert p1["kline_period"] == "30M"
    assert p1["label"] == "30F 5F 1F"

    # 2. 日 30F 5F (Default)
    p2 = parse_chanlun_screener_preset("DAY_30F_5F")
    assert p2["periods"] == ["DAY", "30F", "5F"]
    assert p2["high_period"] == "DAY"
    assert p2["kline_period"] == "DAY"
    assert p2["label"] == "日 30F 5F"

    # 3. 周 日 30F
    p3 = parse_chanlun_screener_preset("WEEK_DAY_30F")
    assert p3["periods"] == ["WEEK", "DAY", "30F"]
    assert p3["high_period"] == "WEEK"
    assert p3["kline_period"] == "WEEK"
    assert p3["label"] == "周 日 30F"

    # 4. 月 周 日
    p4 = parse_chanlun_screener_preset("MONTH_WEEK_DAY")
    assert p4["periods"] == ["MONTH", "WEEK", "DAY"]
    assert p4["high_period"] == "MONTH"
    assert p4["kline_period"] == "MONTH"
    assert p4["label"] == "月 周 日"


def test_parse_chanlun_screener_preset_fallbacks():
    """Verify fallback defaults to DAY_30F_5F for empty or unknown periods."""
    default_preset = CHANLUN_PERIOD_PRESETS["DAY_30F_5F"]
    assert parse_chanlun_screener_preset(None) == default_preset
    assert parse_chanlun_screener_preset("") == default_preset
    assert parse_chanlun_screener_preset("unknown_period") == default_preset

    # Also test single period aliases
    assert parse_chanlun_screener_preset("30M")["key"] == "30F_5F_1F"
    assert parse_chanlun_screener_preset("DAY")["key"] == "DAY_30F_5F"
    assert parse_chanlun_screener_preset("WEEK")["key"] == "WEEK_DAY_30F"
    assert parse_chanlun_screener_preset("MONTH")["key"] == "MONTH_WEEK_DAY"


def test_evaluate_chanlun_strategy_month_week_day():
    """Verify MONTH_WEEK_DAY preset: Month big buy + uptrend + Day 1BUY."""
    st = get_strategy("chanlun_strategy")
    dts = [f"2026-{i+1:02d}" for i in range(20)]
    dummy_month_df = pd.DataFrame({
        "datetime": dts,
        "open": [10.0] * 20,
        "high": [10.5] * 20,
        "low": [9.5] * 20,
        "close": [10.2] * 20,
        "volume": [10000] * 20,
        "amount": [100000] * 20,
    })

    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=dummy_month_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance") as mock_resonance:
        mock_resonance.return_value = {
            "symbol": "600519",
            "name": "贵州茅台",
            "summary": {
                "high_state": {"is_bearish": False, "recent_mmd_bars_ago": 2},
                "mid_state": {"is_bearish": False},
                "low_state": {"is_bearish": False},
            },
            "unified_chart": {
                "mmd_marks": [
                    {"bar_idx": 15, "date": "2026-08", "type": "3BUY", "label": "月线主升3买", "is_buy": True, "level": "high"},
                    {"bar_idx": 19, "date": "2026-10-18", "type": "1BUY", "label": "日线1买", "is_buy": True, "level": "low"},
                ]
            }
        }
        res = _evaluate_stock_for_strategy(
            sym="600519",
            strategy_name="chanlun_strategy",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="MONTH_WEEK_DAY"
        )
        assert res is not None
        assert "[月周日]大买共振·日线1买" in res["status_label"]
        assert res["chan_periods"] == ["MONTH", "WEEK", "DAY"]
        assert res["high_period"] == "MONTH"


def test_evaluate_chanlun_strategy_week_day_30f():
    """Verify WEEK_DAY_30F preset: Week big buy + uptrend + 30M 1BUY."""
    st = get_strategy("chanlun_strategy")
    dts = [f"2026-10-{i+1:02d}" for i in range(25)]
    dummy_df = pd.DataFrame({
        "datetime": dts,
        "open": [10.0] * 25,
        "high": [10.5] * 25,
        "low": [9.5] * 25,
        "close": [10.2] * 25,
        "volume": [10000] * 25,
        "amount": [100000] * 25,
    })

    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=dummy_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance") as mock_resonance:
        mock_resonance.return_value = {
            "symbol": "000001",
            "name": "平安银行",
            "summary": {
                "high_state": {"is_bearish": False, "recent_mmd_bars_ago": 3},
                "mid_state": {"is_bearish": False},
                "low_state": {"is_bearish": False},
            },
            "unified_chart": {
                "mmd_marks": [
                    {"bar_idx": 2, "date": "2026-10-15", "type": "2BUY", "label": "周线2买", "is_buy": True, "level": "high"},
                    {"bar_idx": 20, "date": "2026-10-20 10:30", "type": "1BUY", "label": "30M 1买", "is_buy": True, "level": "low"},
                ]
            }
        }
        res = _evaluate_stock_for_strategy(
            sym="000001",
            strategy_name="chanlun_strategy",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="WEEK_DAY_30F"
        )
        assert res is not None
        assert "[周日30M]大买共振·30M1买" in res["status_label"]
        assert res["high_period"] == "WEEK"


def test_evaluate_chanlun_strategy_day_30f_5f_default():
    """Verify DAY_30F_5F (Default): Day big buy + 5M 2BUY."""
    st = get_strategy("chanlun_strategy")
    dts = [f"2026-10-{i+1:02d}" for i in range(25)]
    dummy_df = pd.DataFrame({
        "datetime": dts,
        "open": [10.0] * 25,
        "high": [10.5] * 25,
        "low": [9.5] * 25,
        "close": [10.2] * 25,
        "volume": [10000] * 25,
        "amount": [100000] * 25,
    })

    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=dummy_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance") as mock_resonance:
        mock_resonance.return_value = {
            "symbol": "600000",
            "name": "浦发银行",
            "summary": {
                "high_state": {"is_bearish": False, "recent_mmd_bars_ago": 1},
                "mid_state": {"is_bearish": False},
                "low_state": {"is_bearish": False},
            },
            "unified_chart": {
                "mmd_marks": [
                    {"bar_idx": 10, "date": "2026-10-18", "type": "3BUY", "label": "日线3买", "is_buy": True, "level": "high"},
                    {"bar_idx": 24, "date": "2026-10-21 09:40", "type": "2BUY", "label": "5M 2买", "is_buy": True, "level": "low"},
                ]
            }
        }
        res = _evaluate_stock_for_strategy(
            sym="600000",
            strategy_name="chanlun_strategy",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="DAY_30F_5F"
        )
        assert res is not None
        assert "[日30M5F]大买共振·5M2买" in res["status_label"]
        assert res["high_period"] == "DAY"
        assert res["period_preset"] == "DAY_30F_5F"


def test_evaluate_chanlun_strategy_filters_top_sell_downtrend():
    """Verify that stocks with top-sell downtrend (e.g. 002463) are strictly filtered out."""
    st = get_strategy("chanlun_strategy")
    # Simulate a stock peaking at 158.0 and falling to 110.0 (< MA5)
    closes = [100, 110, 130, 150, 158, 140, 130, 120, 110]
    highs = [c + 5 for c in closes]
    highs[4] = 160.0
    lows = [c - 5 for c in closes]
    dts = [f"2026-{i+1:02d}" for i in range(len(closes))]
    top_down_df = pd.DataFrame({
        "datetime": dts,
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [10000] * len(closes),
        "amount": [100000] * len(closes),
    })

    # Test helper directly
    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=top_down_df):
        assert _is_top_sell_downtrend("002463", "MONTH") is True

    # Test screener integration filter
    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=top_down_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance") as mock_resonance:
        mock_resonance.return_value = {
            "symbol": "002463",
            "name": "沪电股份",
            "summary": {
                "high_state": {"is_bearish": False, "recent_mmd_bars_ago": 1},
                "mid_state": {"is_bearish": False},
                "low_state": {"is_bearish": False},
            },
            "unified_chart": {
                "mmd_marks": [
                    {"bar_idx": 0, "date": "2025-01", "type": "1BUY", "label": "月线1买", "is_buy": True, "level": "high"},
                    {"bar_idx": 8, "date": "2026-09-01", "type": "1BUY", "label": "日线1买", "is_buy": True, "level": "low"},
                ]
            }
        }
        res = _evaluate_stock_for_strategy(
            sym="002463",
            strategy_name="chanlun_strategy",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="MONTH_WEEK_DAY"
        )
        assert res is None, "Must filter out stock in top sell downtrend!"


def test_screener_request_models_defaults():
    """Verify router request models and discovery default to chanlun_resonance."""
    req_scan = ScreenerScanRequest()
    assert req_scan.strategy == "chanlun_resonance"
    assert req_scan.period == "ALL_CASCADE"

    req_task = ScreenerTaskStartRequest(universe="core")
    assert req_task.strategy == "chanlun_resonance"
    assert req_task.period == "ALL_CASCADE"


def test_strategy_registry_includes_chanlun_resonance():
    """Verify chanlun_resonance is top-priority default and chanlun_strategy is #1."""
    from easy_tdx.strategies.registry import list_all_strategies
    all_strategies = list_all_strategies()
    assert len(all_strategies) > 1
    # chanlun_resonance must be the very first strategy in the list (Default)
    assert all_strategies[0]["name"] == "chanlun_resonance"
    assert all_strategies[1]["name"] == "chanlun_strategy"

    st = get_strategy("chanlun_resonance")
    assert st.name == "chanlun_resonance"
    assert "共振" in st.display_name


def test_evaluate_chanlun_resonance_strategy_all_satisfied():
    """Verify chanlun_resonance selects stock ONLY when all 3 cascade presets are satisfied."""
    st = get_strategy("chanlun_resonance")
    dts = [f"2026-10-{i+1:02d}" for i in range(25)]
    dummy_df = pd.DataFrame({
        "datetime": dts,
        "open": [10.0] * 25,
        "high": [10.5] * 25,
        "low": [9.5] * 25,
        "close": [10.2] * 25,
        "volume": [10000] * 25,
        "amount": [100000] * 25,
    })

    # Mock resonance for the 3 distinct multi-period cascades
    def mock_resonance_side_effect(code, periods, count, force_refresh):
        p_tuple = tuple(periods)
        if p_tuple == ("MONTH", "WEEK", "DAY"):
            return {
                "summary": {"high_state": {"is_bearish": False, "recent_mmd_bars_ago": 1}, "mid_state": {"is_bearish": False}},
                "unified_chart": {
                    "mmd_marks": [
                        {"date": "2026-09", "type": "1BUY", "label": "月线1买", "is_buy": True, "level": "high"},
                        {"date": "2026-10-18", "type": "1BUY", "label": "日线1买", "is_buy": True, "level": "low"},
                    ]
                }
            }
        elif p_tuple == ("WEEK", "DAY", "30F"):
            return {
                "summary": {"high_state": {"is_bearish": False, "recent_mmd_bars_ago": 2}},
                "unified_chart": {
                    "mmd_marks": [
                        {"date": "2026-10-10", "type": "2BUY", "label": "周线2买", "is_buy": True, "level": "high"},
                        {"date": "2026-10-19 14:30", "type": "1BUY", "label": "30M 1买", "is_buy": True, "level": "low"},
                    ]
                }
            }
        elif p_tuple == ("DAY", "30F", "5F"):
            return {
                "summary": {"high_state": {"is_bearish": False, "recent_mmd_bars_ago": 1}},
                "unified_chart": {
                    "mmd_marks": [
                        {"date": "2026-10-20", "type": "1BUY", "label": "日线1买", "is_buy": True, "level": "high"},
                        {"date": "2026-10-21 09:45", "type": "2BUY", "label": "5M 2买", "is_buy": True, "level": "low"},
                    ]
                }
            }
        return None

    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=dummy_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance", side_effect=mock_resonance_side_effect):
        res = _evaluate_stock_for_strategy(
            sym="600519",
            strategy_name="chanlun_resonance",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="ALL_CASCADE"
        )
        assert res is not None
        assert "全级别共振" in res["status_label"]
        assert res["high_period"] == "MONTH"
        assert res["period_preset"] == "ALL_CASCADE"


def test_evaluate_chanlun_resonance_strategy_fails_when_condition_missing():
    """Verify chanlun_resonance rejects stock if any of the 3 cascade conditions is missing."""
    st = get_strategy("chanlun_resonance")
    dts = [f"2026-10-{i+1:02d}" for i in range(25)]
    dummy_df = pd.DataFrame({
        "datetime": dts,
        "open": [10.0] * 25,
        "high": [10.5] * 25,
        "low": [9.5] * 25,
        "close": [10.2] * 25,
        "volume": [10000] * 25,
        "amount": [100000] * 25,
    })

    # Suppose condition 3 (5M 2BUY) is missing (only has 3SELL)
    def mock_missing_5m(code, periods, count, force_refresh):
        p_tuple = tuple(periods)
        if p_tuple == ("MONTH", "WEEK", "DAY"):
            return {
                "summary": {"high_state": {"is_bearish": False, "recent_mmd_bars_ago": 1}, "mid_state": {"is_bearish": False}},
                "unified_chart": {
                    "mmd_marks": [
                        {"date": "2026-09", "type": "1BUY", "label": "月线1买", "is_buy": True, "level": "high"},
                        {"date": "2026-10-18", "type": "1BUY", "label": "日线1买", "is_buy": True, "level": "low"},
                    ]
                }
            }
        elif p_tuple == ("WEEK", "DAY", "30F"):
            return {
                "summary": {"high_state": {"is_bearish": False, "recent_mmd_bars_ago": 2}},
                "unified_chart": {
                    "mmd_marks": [
                        {"date": "2026-10-10", "type": "2BUY", "label": "周线2买", "is_buy": True, "level": "high"},
                        {"date": "2026-10-19 14:30", "type": "1BUY", "label": "30M 1买", "is_buy": True, "level": "low"},
                    ]
                }
            }
        elif p_tuple == ("DAY", "30F", "5F"):
            return {
                "summary": {"high_state": {"is_bearish": False, "recent_mmd_bars_ago": 1}},
                "unified_chart": {
                    "mmd_marks": [
                        {"date": "2026-10-20", "type": "1BUY", "label": "日线1买", "is_buy": True, "level": "high"},
                        {"date": "2026-10-21 09:45", "type": "3SELL", "label": "5M 3卖", "is_buy": False, "level": "low"},
                    ]
                }
            }
        return None

    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=dummy_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance", side_effect=mock_missing_5m):
        res = _evaluate_stock_for_strategy(
            sym="600519",
            strategy_name="chanlun_resonance",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="ALL_CASCADE"
        )
        assert res is None, "Should be rejected because 5M 2BUY is missing!"


def test_evaluate_chanlun_strategy_displays_daily_price_and_change_pct():
    """Verify that screener results always reflect daily price and daily change percentage."""
    st = get_strategy("chanlun_strategy")
    
    # Month DF: 20 bars, price is 150.0
    month_dts = [f"2025-{i+1:02d}" for i in range(12)] + [f"2026-{i+1:02d}" for i in range(8)]
    month_df = pd.DataFrame({
        "datetime": month_dts,
        "open": [100.0] * 18 + [120.0, 140.0],
        "high": [110.0] * 18 + [130.0, 160.0],
        "low": [95.0] * 18 + [115.0, 135.0],
        "close": [100.0] * 18 + [120.0, 150.0],
        "volume": [100000] * 20,
        "amount": [1000000] * 20,
    })

    # Day DF: yesterday close was 145.0, today close is 148.0 (daily change = +2.07%)
    day_df = pd.DataFrame({
        "datetime": [f"2026-10-{i+1:02d}" for i in range(20)],
        "open": [140.0] * 18 + [144.0, 145.0],
        "high": [145.0] * 18 + [146.0, 149.0],
        "low": [138.0] * 18 + [142.0, 144.0],
        "close": [140.0] * 18 + [145.0, 148.0],
        "volume": [50000] * 18 + [60000, 75000],
        "amount": [500000] * 18 + [600000, 750000],
    })

    def mock_kline(sym, period="DAY", force_refresh=False):
        if period == "MONTH":
            return month_df
        return day_df

    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", side_effect=mock_kline), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance") as mock_resonance:
        mock_resonance.return_value = {
            "summary": {
                "high_state": {"is_bearish": False, "recent_mmd_bars_ago": 1},
                "mid_state": {"is_bearish": False},
                "low_state": {"is_bearish": False},
            },
            "unified_chart": {
                "mmd_marks": [
                    {"date": "2026-09", "type": "1BUY", "label": "月线1买", "is_buy": True, "level": "high"},
                    {"date": "2026-10-18", "type": "1BUY", "label": "日线1买", "is_buy": True, "level": "low"},
                ]
            }
        }
        res = _evaluate_stock_for_strategy(
            sym="600519",
            strategy_name="chanlun_strategy",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="MONTH_WEEK_DAY"
        )
        assert res is not None
        # Price must be daily close (148.0), NOT monthly close (150.0)
        assert res["price"] == 148.0
        # Change percentage must be daily change (+2.07%), NOT monthly change (+25.0%)
        assert res["change_pct"] == 2.07
        assert res["latest_change_pct"] == 2.07
        assert res["volume"] == 75000


