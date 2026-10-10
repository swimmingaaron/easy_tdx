"""缠论多周期共振买卖点引擎单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
import pandas as pd
import pytest

from chanlun_resonance_kline import (
    PERIOD_SPECS,
    ThreePeriodResonanceEngine,
    normalize_period,
    parse_three_periods,
    analyze_and_plot_resonance,
)
from easy_tdx.chanlun.analyser import ChanlunAnalyser


def test_period_normalization():
    assert normalize_period("周线") == "WEEK"
    assert normalize_period("日线") == "DAY"
    assert normalize_period("30分钟") == "30F"
    assert normalize_period("30m") == "30F"
    assert normalize_period("120F") == "120F"
    assert normalize_period("月线") == "MONTH"
    assert normalize_period("5F") == "5F"

    with pytest.raises(ValueError):
        normalize_period("invalid_period")


def test_parse_three_periods():
    # 默认空入参返回默认 ["DAY", "30F", "5F"]
    assert parse_three_periods(None) == ["DAY", "30F", "5F"]
    assert parse_three_periods("") == ["DAY", "30F", "5F"]

    # 默认排序自动按大级别到小级别排序
    p = parse_three_periods("30F,周线,日线")
    assert p == ["WEEK", "DAY", "30F"]

    p2 = parse_three_periods("120F, 月线, 5F")
    assert p2 == ["MONTH", "120F", "5F"]

    # 错误测试：少于3个或多于3个
    with pytest.raises(ValueError):
        parse_three_periods("WEEK,DAY")

    with pytest.raises(ValueError):
        parse_three_periods("WEEK,WEEK,DAY")


def _generate_synthetic_df(n_bars: int = 100, trend: str = "up") -> pd.DataFrame:
    """生成带有波段震荡和趋势的合成行情数据。"""
    base_price = 10.0
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(n_bars)]
    rows = []
    price = base_price

    for i in range(n_bars):
        cycle = 1.0 if (i // 5) % 2 == 0 else -0.8
        trend_drift = 0.05 if trend == "up" else -0.05
        change = cycle + trend_drift
        op = price
        cl = price + change
        hi = max(op, cl) + 0.3
        lo = min(op, cl) - 0.3
        price = cl
        rows.append({
            "datetime": dates[i].strftime("%Y-%m-%d"),
            "open": round(op, 2),
            "high": round(hi, 2),
            "low": round(lo, 2),
            "close": round(cl, 2),
            "volume": 10000 + i * 50,
            "amount": (10000 + i * 50) * cl,
        })
    return pd.DataFrame(rows)


def test_three_period_resonance_engine_scan():
    # 模拟三周期数据
    df_high = _generate_synthetic_df(80, trend="up")
    df_mid = _generate_synthetic_df(80, trend="up")
    df_low = _generate_synthetic_df(80, trend="up")

    res_high = ChanlunAnalyser("000001", "weekly").process_klines(df_high)
    res_mid = ChanlunAnalyser("000001", "daily").process_klines(df_mid)
    res_low = ChanlunAnalyser("000001", "30min").process_klines(df_low)

    results = {
        "WEEK": res_high,
        "DAY": res_mid,
        "30F": res_low,
    }

    engine = ThreePeriodResonanceEngine("WEEK", "DAY", "30F", results)
    resonances = engine.scan_resonances()
    assert isinstance(resonances, list)


def test_analyze_and_plot_resonance_pipeline(tmp_path):
    out_png = tmp_path / "test_resonance.png"
    out_html = tmp_path / "test_resonance.html"

    ret = analyze_and_plot_resonance(
        code="000001",
        periods=["WEEK", "DAY", "30F"],
        bars_count=60,
        save_png=True,
        save_html=True,
        show_window=False,
        output_png_path=out_png,
        output_html_path=out_html,
    )

    assert ret["code"] == "000001"
    assert ret["periods"] == ["WEEK", "DAY", "30F"]
    assert out_png.exists()
    assert out_png.stat().st_size > 0
    assert out_html.exists()
    assert out_html.stat().st_size > 0
