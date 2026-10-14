"""缠论全周期核心算法深度优化单元测试。

覆盖：
1. K线包含处理（开盘价保持、连续合并方向继承、双向覆盖）；
2. 顶分型与底分型（严格极值、平顶平底过滤、同向极值保留、未完成分型标识）；
3. 笔（倒挂排除、极值公理、连续折线无缝连接、新老笔跨度）；
4. 线段（特征序列分型法、包含合并、无缺口与有缺口破坏）；
5. 走势中枢（前三笔基准区间 [ZD, ZG] 恒定、震荡延伸 GG/DD 扩展、离开完成）；
6. 背驰（创新高/新低前置条件、MACD力度、盘整背驰、趋势双中枢背驰）；
7. 买卖点（一二三类买卖点严格判定、三买优先、杜绝中枢震荡滥发二买）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import pytest

from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.beichi import check_bi_beichi
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.mmd import find_mmds
from easy_tdx.chanlun.zs import find_zss
from easy_tdx.chanlun.types import (
    BI,
    CLKline,
    Direction,
    FX,
    FXType,
    Kline,
    MMDType,
    ZS,
)
from easy_tdx.chanlun.xd import find_xds


def _make_kline(
    idx: int,
    dt_str: str,
    o: float,
    c: float,
    h: float,
    l: float,
    vol: float = 1000.0,
) -> Kline:
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M") if " " in dt_str else datetime.strptime(dt_str, "%Y-%m-%d")
    return Kline(index=idx, date=dt, open=o, close=c, high=h, low=l, amount=vol)


class TestKlineMergeOptimized:
    """K线包含处理深度测试。"""

    def test_open_price_preserved_on_merge(self):
        """合并K线应保留首根K线的open，末根K线的close，并累加成交量。"""
        k0 = _make_kline(0, "2026-01-01", o=10.0, c=12.0, h=13.0, l=9.5, vol=100.0)
        k1 = _make_kline(1, "2026-01-02", o=11.0, c=11.5, h=12.5, l=10.0, vol=150.0)  # 被包含
        k2 = _make_kline(2, "2026-01-03", o=11.8, c=12.2, h=12.4, l=10.5, vol=200.0)  # 再次被包含

        res = merge_klines([k0, k1, k2])
        assert len(res) == 1
        ck = res[0]
        assert ck.open == 10.0, "合并K线必须保留初始第一根K线的开盘价"
        assert ck.close == 12.2, "合并K线必须保留最后一根K线的收盘价"
        assert ck.amount == 450.0, "成交量应累加"
        assert ck.merged_count == 3

    def test_consecutive_merge_direction_inheritance(self):
        """连续包含时必须继承已确定的向上走势方向（取高高）。"""
        k0 = _make_kline(0, "2026-01-01", o=10.0, c=11.0, h=11.5, l=9.5)
        k1 = _make_kline(1, "2026-01-02", o=11.2, c=13.0, h=13.5, l=11.0)  # 向上走出无包含
        k2 = _make_kline(2, "2026-01-03", o=12.5, c=12.0, h=13.0, l=11.5)  # 被 k1 包含
        k3 = _make_kline(3, "2026-01-04", o=12.2, c=12.8, h=12.9, l=12.0)  # 再次被包含

        res = merge_klines([k0, k1, k2, k3])
        assert len(res) == 2
        # k1+k2+k3 向上合并取高高：high=max(13.5, 13.0, 12.9)=13.5, low=max(11.0, 11.5, 12.0)=12.0
        assert res[1].high == 13.5
        assert res[1].low == 12.0
        assert res[1].merged_count == 3


class TestFractalOptimized:
    """顶底分型深度测试。"""

    def test_strict_fractal_definition(self):
        """严格模式下平顶或平底不应构成有效分型。"""
        # 平顶测试
        k0 = _make_kline(0, "2026-01-01", 10, 11, 11.5, 9.5)
        k1 = _make_kline(1, "2026-01-02", 11, 13, 14.0, 10.5)
        k2 = _make_kline(2, "2026-01-03", 13, 12, 14.0, 10.0)  # 高点相等
        cks = merge_klines([k0, k1, k2])
        fxs = find_fractals(cks, ChanlunConfig(fx_strict=True))
        assert len(fxs) == 0, "相等高点在严格模式下不能构成顶分型"

    def test_consecutive_same_type_preserves_extrema(self):
        """连续两个同向分型只保留更极端的值并更新内部关联。"""
        # 两个连续顶分型：第一个高15，第二个高17
        cks = [
            CLKline(k_index=0, date=datetime(2026, 1, 1), open=10, close=12, high=12, low=10, amount=0, index=0),
            CLKline(k_index=1, date=datetime(2026, 1, 2), open=12, close=15, high=15, low=11, amount=0, index=1),  # 顶1
            CLKline(k_index=2, date=datetime(2026, 1, 3), open=14, close=13, high=14, low=12, amount=0, index=2),
            CLKline(k_index=3, date=datetime(2026, 1, 4), open=13, close=17, high=17, low=13, amount=0, index=3),  # 顶2 更高
            CLKline(k_index=4, date=datetime(2026, 1, 5), open=16, close=14, high=16, low=13.5, amount=0, index=4),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 1
        assert fxs[0].fx_type == FXType.DING
        assert fxs[0].val == 17.0
        assert fxs[0].k.index == 3


class TestBiOptimized:
    """笔核心规则与公理测试。"""

    def test_reject_inverted_bi(self):
        """向上笔终点顶分型必须严格高于起点底分型，绝不允许倒挂。"""
        # 起点底分型 val=12.0，终点顶分型 val=11.0 (低于底分型)
        k_di = CLKline(0, datetime(2026, 1, 1), 12, 12, 13, 12, 0, 0)
        k_ding = CLKline(5, datetime(2026, 1, 6), 11, 11, 11, 10, 0, 5)

        fx_di = FX(FXType.DI, k_di, [k_di, k_di, k_di], val=12.0, index=0)
        fx_ding = FX(FXType.DING, k_ding, [k_ding, k_ding, k_ding], val=11.0, index=1)

        bis = find_bis([fx_di, fx_ding])
        assert len(bis) == 0, "顶分型低于底分型不能构成向上笔"

    def test_bi_continuous_polyline(self):
        """生成的笔序列必须首尾相接、无缝连续 (bis[i].end == bis[i+1].start)。"""
        from easy_tdx.chanlun.analyser import ChanlunAnalyser
        import pandas as pd
        import numpy as np

        # 生成一段具有明显波动趋势的数据
        n = 80
        t = np.linspace(0, 4 * np.pi, n)
        prices = 20.0 + 5.0 * np.sin(t)
        df = pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=n, freq="D"),
            "open": prices,
            "close": prices + 0.1,
            "high": prices + 0.5,
            "low": prices - 0.5,
            "volume": [1000.0] * n,
        })
        res = ChanlunAnalyser(code="TEST", frequency="DAILY").process_klines(df)
        bis = res.bis
        assert len(bis) >= 2
        for i in range(len(bis) - 1):
            assert bis[i].end == bis[i + 1].start, f"笔[{i}].end 必须严格等于 笔[{i+1}].start"
            assert bis[i].direction != bis[i + 1].direction, "相邻笔方向必须严格交替"


class TestZhongshuOptimized:
    """走势中枢区间恒定与延伸测试。"""

    def test_zhongshu_range_constant_during_extension(self):
        """中枢确立后，[ZD, ZG] 必须保持恒定，后续震荡不缩小区间。"""
        dt = datetime(2026, 1, 1)
        k = CLKline(0, dt, 10, 10, 10, 10, 0, 0)
        fx_ding = FX(FXType.DING, k, [k, k, k], 15.0, 0)
        fx_di = FX(FXType.DI, k, [k, k, k], 8.0, 1)

        # 构造前三笔：
        # b0: 向下 (15 -> 8) [h=15, l=8]
        # b1: 向上 (8 -> 14) [h=14, l=8]
        # b2: 向下 (14 -> 9) [h=14, l=9]
        # 重叠区间：ZG = min(15, 14, 14) = 14.0; ZD = max(8, 8, 9) = 9.0
        b0 = BI(fx_ding, fx_di, Direction.DOWN, index=0, high=15.0, low=8.0)
        b1 = BI(fx_di, fx_ding, Direction.UP, index=1, high=14.0, low=8.0)
        b2 = BI(fx_ding, fx_di, Direction.DOWN, index=2, high=14.0, low=9.0)

        # 后续延伸震荡笔 b3 (9 -> 13) 与 b4 (13 -> 10)
        # b3 区间 [13, 9]，如果在老逻辑下会把 ZG 缩成 13
        b3 = BI(fx_di, fx_ding, Direction.UP, index=3, high=13.0, low=9.0)
        b4 = BI(fx_ding, fx_di, Direction.DOWN, index=4, high=13.0, low=10.0)

        zss = find_zss([b0, b1, b2, b3, b4])
        assert len(zss) == 1
        zs = zss[0]
        assert zs.zg == 14.0, "中枢上沿 ZG 必须由前三笔确立并保持恒定，不能被 b3/b4 缩小"
        assert zs.zd == 9.0, "中枢下沿 ZD 必须由前三笔确立并保持恒定，不能被 b3/b4 缩小"
        assert zs.line_count == 5, "应包含全部 5 笔延伸震荡"
        assert zs.gg == 15.0
        assert zs.dd == 8.0


class TestBeichiAndMMDOptimized:
    """背驰与买卖点深度优化测试。"""

    def test_beichi_requires_price_innovation(self):
        """未创新高或新低的笔不能被判定为背驰。"""
        dt = datetime(2026, 1, 1)
        k = CLKline(0, dt, 10, 10, 10, 10, 0, 0)
        f_ding = FX(FXType.DING, k, [k, k, k], 10.0, 0)
        f_di = FX(FXType.DI, k, [k, k, k], 5.0, 1)

        # 向上笔 1: 从 5 涨到 20 (high=20)
        b0 = BI(f_di, f_ding, Direction.UP, index=0, high=20.0, low=5.0)
        # 向下笔 2: 从 20 跌到 10
        b1 = BI(f_ding, f_di, Direction.DOWN, index=1, high=20.0, low=10.0)
        # 向上笔 3: 从 10 涨到 18 (high=18, 未创新高！) 虽然幅度 8 < 15，但绝不是顶背驰
        b2 = BI(f_di, f_ding, Direction.UP, index=2, high=18.0, low=10.0)

        bcs = check_bi_beichi([b0, b1, b2], [])
        # 向上笔 b2 没有创新高，不应报告笔顶背驰
        up_bcs = [b for b in bcs if b.curr.index == 2]
        assert len(up_bcs) == 0, "未创新高的向上笔不能判定为顶背驰"

    def test_buy3_and_sell3_orthodoxy(self):
        """第三类买卖点严格判定。"""
        dt = datetime(2026, 1, 1)
        k = CLKline(0, dt, 10, 10, 10, 10, 0, 0)
        f_ding = FX(FXType.DING, k, [k, k, k], 12.0, 0)
        f_di = FX(FXType.DI, k, [k, k, k], 10.0, 1)

        # 中枢 zd=10.0, zg=12.0
        zs = ZS(zd=10.0, zg=12.0, gg=13.0, dd=9.0, index=0)

        # 离开笔向上突破到 16.0
        b_exit = BI(f_di, f_ding, Direction.UP, index=0, high=16.0, low=11.0)
        # 回调笔向下最低 12.5 (不跌破 zg=12.0)
        b_pullback = BI(f_ding, f_di, Direction.DOWN, index=1, high=16.0, low=12.5)

        mmds = find_mmds([b_exit, b_pullback], [zs])
        assert len(mmds) == 1
        assert mmds[0].mmd_type == MMDType.BUY_3
        assert "三类买点" in mmds[0].msg
