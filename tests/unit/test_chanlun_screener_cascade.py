"""Unit tests for Chanlun 4-tier cascading period screener presets and evaluation."""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd

from easy_tdx.screener.scanner import (
    parse_chanlun_screener_preset,
    CHANLUN_PERIOD_PRESETS,
    _evaluate_stock_for_strategy,
)
from easy_tdx.strategies.registry import get_strategy
from easy_tdx.web.routers.screener import ScreenerScanRequest, ScreenerTaskStartRequest


def test_parse_chanlun_screener_preset_definitions():
    """Verify all 4 presets match the user's explicit specification."""
    # 1. 30F 5F 1F (Default)
    p1 = parse_chanlun_screener_preset("30F_5F_1F")
    assert p1["periods"] == ["30F", "5F", "1F"]
    assert p1["high_period"] == "30F"
    assert p1["kline_period"] == "30M"
    assert p1["label"] == "30F 5F 1F"

    # 2. 日 30F 5F
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


def test_evaluate_chanlun_strategy_big_cycle_buy():
    """Verify that chanlun_strategy selects stock when big cycle triggers Big Buy."""
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

    # Case 1: Big cycle (30F) triggers 3BUY (主升3买) -> should match
    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=dummy_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance") as mock_resonance:
        mock_resonance.return_value = {
            "symbol": "600519",
            "name": "贵州茅台",
            "resonance_status": "STRONG_RESONANCE",
            "unified_chart": {
                "mmd_marks": [
                    {"bar_idx": 2, "date": "2026-10-18", "type": "3BUY", "label": "30F主升3买", "is_buy": True, "level": "high"}
                ]
            }
        }
        res = _evaluate_stock_for_strategy(
            sym="600519",
            strategy_name="chanlun_strategy",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="30F_5F_1F"
        )

        assert res is not None
        assert "30F" in res["status_label"] and "3买" in res["status_label"]
        assert res["chan_periods"] == ["30F", "5F", "1F"]
        assert res["high_period"] == "30F"
        assert res["period_preset"] == "30F_5F_1F"

    # Case 2: Only small cycle triggers buy, big cycle does not -> should be filtered out
    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=dummy_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance") as mock_resonance:
        mock_resonance.return_value = {
            "symbol": "600519",
            "name": "贵州茅台",
            "resonance_status": "NO_RESONANCE",
            "unified_chart": {
                "mmd_marks": [
                    {"bar_idx": 2, "date": "2026-10-18", "type": "1BUY", "label": "1F大级别1买", "is_buy": True, "level": "low"}
                ]
            }
        }
        res_filtered = _evaluate_stock_for_strategy(
            sym="600519",
            strategy_name="chanlun_strategy",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="30F_5F_1F"
        )
        assert res_filtered is None, "Should be filtered out because big cycle (30F) has no big buy"

    # Case 3: Weekly preset WEEK_DAY_30F with big cycle 3BUY
    with patch("easy_tdx.screener.scanner._get_or_fetch_kline", return_value=dummy_df), \
         patch("easy_tdx.chanlun.resonance.analyze_multi_period_resonance") as mock_resonance:
        mock_resonance.return_value = {
            "symbol": "000001",
            "name": "平安银行",
            "resonance_status": "STRONG_RESONANCE",
            "unified_chart": {
                "mmd_marks": [
                    {"bar_idx": 2, "date": "2026-10-18", "type": "3BUY", "label": "周线大级别3买", "is_buy": True, "level": "high"}
                ]
            }
        }
        res_week = _evaluate_stock_for_strategy(
            sym="000001",
            strategy_name="chanlun_strategy",
            st=st,
            lookback_bars=20,
            force_refresh=False,
            period="WEEK_DAY_30F"
        )
        assert res_week is not None
        assert "周线" in res_week["status_label"] and "3买" in res_week["status_label"]
        assert res_week["chan_periods"] == ["WEEK", "DAY", "30F"]
        assert res_week["high_period"] == "WEEK"


def test_screener_request_models_defaults():
    """Verify router request models default to DAY_30F_5F."""
    req_scan = ScreenerScanRequest()
    assert req_scan.period == "DAY_30F_5F"

    req_task = ScreenerTaskStartRequest(strategy="chanlun_strategy", universe="core")
    assert req_task.period == "DAY_30F_5F"
