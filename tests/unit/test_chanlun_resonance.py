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


def test_fractal_state_machine_dedup():
    """测试分型顶底交替状态机：连续同向分型只保留更极端的分型。"""
    from easy_tdx.chanlun.fractal import find_fractals
    from easy_tdx.chanlun.types import CLKline, FXType

    dt = datetime(2026, 1, 1)

    def _make_ck(idx: int, h: float, l: float) -> CLKline:
        return CLKline(
            k_index=idx,
            date=dt + timedelta(days=idx),
            open=l,
            close=h,
            high=h,
            low=l,
            amount=0.0,
            index=idx,
            merged_count=1,
        )

    # 构造：顶(10) -> 更高顶(12) -> 底(5)
    # ck[0]: 6-8, ck[1]: 7-10 (顶1), ck[2]: 7-9, ck[3]: 8-12 (顶2), ck[4]: 7-9, ck[5]: 5-6 (底)
    cks = [
        _make_ck(0, 8.0, 6.0),
        _make_ck(1, 10.0, 7.0),  # 顶 1 (val=10)
        _make_ck(2, 9.0, 7.0),
        _make_ck(3, 12.0, 8.0),  # 顶 2 (val=12, 更极端)
        _make_ck(4, 8.0, 6.0),
        _make_ck(5, 6.0, 4.0),   # 底 (val=4)
        _make_ck(6, 7.0, 5.0),
    ]
    fxs = find_fractals(cks)
    assert len(fxs) == 2
    assert fxs[0].fx_type == FXType.DING
    assert fxs[0].val == 12.0  # 更高的顶被保留，10 被淘汰
    assert fxs[1].fx_type == FXType.DI
    assert fxs[1].val == 4.0


def test_bi_range_with_cklines():
    """测试笔划分时扫描全部缠论K线计算真实极值。"""
    from easy_tdx.chanlun.bi import find_bis
    from easy_tdx.chanlun.fractal import find_fractals
    from easy_tdx.chanlun.types import CLKline

    dt = datetime(2026, 1, 1)

    def _make_ck(idx: int, h: float, l: float) -> CLKline:
        return CLKline(
            k_index=idx,
            date=dt + timedelta(days=idx),
            open=l,
            close=h,
            high=h,
            low=l,
            amount=0.0,
            index=idx,
            merged_count=1,
        )

    # 顶(10) -> 中间有更低K线(2) -> 底(4)
    cks = [
        _make_ck(0, 8.0, 7.0),
        _make_ck(1, 10.0, 7.0),  # 顶分型 (val=10)
        _make_ck(2, 9.0, 7.0),
        _make_ck(3, 8.0, 2.0),   # 中间K线打出更低点 2.0 (超出底分型端点)
        _make_ck(4, 6.0, 4.0),
        _make_ck(5, 5.0, 3.5),   # 底分型 (val=3.5)
        _make_ck(6, 7.0, 5.0),
    ]
    fxs = find_fractals(cks)
    bis = find_bis(fxs, cklines=cks)
    assert len(bis) >= 1
    # 真实最低价应当为 2.0（包含中间K线），而非分型端点的 3.5
    assert bis[0].low == 2.0
    assert bis[0].high == 10.0


def test_mmd_priority_buy3():
    """测试三类买点优先于二类买点被识别。"""
    from easy_tdx.chanlun.mmd import find_mmds
    from easy_tdx.chanlun.types import BI, FX, CLKline, Direction, FXType, MMDType, ZS

    dt = datetime(2026, 1, 1)
    k0 = CLKline(0, dt, 10, 10, 10, 10, 0, 0, 1)
    fx_di = FX(FXType.DI, k0, [k0, k0, k0], 10.0, 0)
    fx_ding = FX(FXType.DING, k0, [k0, k0, k0], 12.0, 1)

    # 中枢区间：zd=8.0, zg=11.0
    zs = ZS(zd=8.0, zg=11.0, gg=13.0, dd=7.0, index=0)

    # 一笔回调向下：low=11.5 (> zg=11.0)，属于三买
    bi_down = BI(
        start=fx_ding,
        end=fx_di,
        direction=Direction.DOWN,
        index=2,
        high=13.0,
        low=11.5,
    )
    # 前一个向下笔 low=6.0
    prev_down = BI(
        start=fx_ding,
        end=fx_di,
        direction=Direction.DOWN,
        index=0,
        high=10.0,
        low=6.0,
    )
    mid_up = BI(
        start=fx_di,
        end=fx_ding,
        direction=Direction.UP,
        index=1,
        high=13.0,
        low=6.0,
    )

    mmds = find_mmds([prev_down, mid_up, bi_down], [zs])
    # 应该识别为 BUY_3，而不是误判为 BUY_2
    assert len(mmds) == 1
    assert mmds[0].mmd_type == MMDType.BUY_3


def test_resonance_signal_dedup():
    """测试共振信号在同一 bar_idx 仅保留最高级别评级。"""
    from easy_tdx.chanlun.resonance import _dedup_resonances, ResonanceSignal, PeriodState

    p_state = PeriodState("DAY", 10, "2026-01-01", 10.0, "up")
    r_aa = ResonanceSignal(
        timestamp="2026-01-01",
        price=10.0,
        direction="BUY",
        grade="AA",
        pattern_name="二类买点",
        high_period="DAY",
        mid_period="30F",
        low_period="5F",
        high_state=p_state,
        mid_state=p_state,
        low_state=p_state,
        low_bar_idx=50,
        mid_bar_idx=10,
        high_bar_idx=5,
        description="AA信号",
    )
    r_aaa = ResonanceSignal(
        timestamp="2026-01-01",
        price=10.0,
        direction="BUY",
        grade="AAA",
        pattern_name="蓝2进1双重确认",
        high_period="DAY",
        mid_period="30F",
        low_period="5F",
        high_state=p_state,
        mid_state=p_state,
        low_state=p_state,
        low_bar_idx=50,
        mid_bar_idx=10,
        high_bar_idx=5,
        description="AAA顶级信号",
    )

    deduped = _dedup_resonances([r_aa, r_aaa])
    assert len(deduped) == 1
    assert deduped[0].grade == "AAA"

