"""缠论核心计算 单元测试。"""

from __future__ import annotations

from datetime import datetime

from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.types import CLKline, Direction, FXType, Kline
from easy_tdx.chanlun.zs import find_zss

# ── helpers ──────────────────────────────────────────────────────────────


def _k(
    idx: int,
    dt: str,
    o: float,
    c: float,
    h: float,
    l: float,  # noqa: E741
    a: float = 0.0,
) -> Kline:
    """快速构造 Kline。"""
    return Kline(
        index=idx,
        date=datetime.strptime(dt, "%Y-%m-%d"),
        open=o,
        close=c,
        high=h,
        low=l,
        amount=a,
    )


def _ck(
    idx: int,
    dt: str,
    o: float,
    c: float,
    h: float,
    l: float,  # noqa: E741
    merged_count: int = 1,
    direction: str = "",
) -> CLKline:
    """快速构造 CLKline。"""
    return CLKline(
        k_index=idx,
        date=datetime.strptime(dt, "%Y-%m-%d"),
        open=o,
        close=c,
        high=h,
        low=l,
        amount=0.0,
        index=idx,  # 处理后K线在序列中的顺序索引
        merged_count=merged_count,
        direction=direction,
    )


# ── K 线合并测试 ──────────────────────────────────────────────────────────


class TestMergeKlines:
    """merge_klines 测试。"""

    def test_no_merge_needed(self) -> None:
        """K 线无包含关系，应原样返回。"""
        klines = [
            _k(0, "2025-01-02", 10, 12, 13, 9),
            _k(1, "2025-01-03", 11, 16, 17, 11),  # 高于前一根高点、低于前根低点 → 无包含
            _k(2, "2025-01-06", 13, 11, 18, 12),  # 继续新高 → 无包含
        ]
        result = merge_klines(klines)
        assert len(result) == 3
        # 每个 CLKline 没有合并
        assert all(ck.merged_count == 1 for ck in result)

    def test_upward_include(self) -> None:
        """向上趋势中的包含关系应合并。

        K1: h=15 l=10  (向上)
        K2: h=13 l=11  ← K2 被 K1 包含 (15>13 and 10<11 => 15>=13 and 10<=11)
        合并后取高高：h=15, l=11
        """
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),
            _k(1, "2025-01-03", 11, 13, 13, 11),
        ]
        result = merge_klines(klines)
        assert len(result) == 1
        assert result[0].high == 15.0
        assert result[0].low == 11.0
        assert result[0].merged_count == 2

    def test_downward_include(self) -> None:
        """向下趋势中的包含关系应合并。

        K1: h=10 l=5   (向下)
        K2: h=9  l=6   ← K2 被 K1 包含 (10>=9 and 5<=6)
        合并后取低低：h=9, l=5
        """
        klines = [
            _k(0, "2025-01-02", 12, 8, 10, 5),
            _k(1, "2025-01-03", 8, 7, 9, 6),
        ]
        result = merge_klines(klines)
        assert len(result) == 1
        assert result[0].high == 9.0
        assert result[0].low == 5.0
        assert result[0].merged_count == 2

    def test_three_klines_with_two_merges(self) -> None:
        """连续包含：三根 K 线合并为一根。"""
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),  # 大阳线
            _k(1, "2025-01-03", 11, 13, 14, 11),  # 被包含
            _k(2, "2025-01-06", 12, 14, 14, 12),  # 被包含
        ]
        result = merge_klines(klines)
        assert len(result) == 1
        assert result[0].merged_count == 3
        # 向上合并：取高高 => h=15, l=12
        assert result[0].high == 15.0
        assert result[0].low == 12.0

    def test_empty_input(self) -> None:
        """空输入返回空列表。"""
        assert merge_klines([]) == []

    def test_single_kline(self) -> None:
        """单根 K 线返回单个 CLKline。"""
        klines = [_k(0, "2025-01-02", 10, 12, 13, 9)]
        result = merge_klines(klines)
        assert len(result) == 1
        assert result[0].high == 13.0
        assert result[0].low == 9.0

    def test_mixed_merge_and_non_merge(self) -> None:
        """混合场景：部分合并，部分不合并。"""
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),  # 大阳线
            _k(1, "2025-01-03", 11, 13, 14, 11),  # 被包含，合并
            _k(2, "2025-01-06", 16, 18, 19, 15),  # 新高，不合并
            _k(3, "2025-01-07", 17, 15, 18, 14),  # 阴线，不包含
        ]
        result = merge_klines(klines)
        assert len(result) == 3
        assert result[0].merged_count == 2  # K0+K1 合并
        assert result[1].merged_count == 1  # K2 独立
        assert result[2].merged_count == 1  # K3 独立

    def test_index_assignment(self) -> None:
        """CLKline.index 应从 0 递增。"""
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),
            _k(1, "2025-01-03", 14, 16, 17, 13),
            _k(2, "2025-01-06", 16, 12, 17, 11),
        ]
        result = merge_klines(klines)
        for i, ck in enumerate(result):
            assert ck.index == i

    def test_klines_reference_preserved(self) -> None:
        """CLKline.klines 应包含合并前的原始 K 线。"""
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),
            _k(1, "2025-01-03", 11, 13, 14, 11),  # 被包含
        ]
        result = merge_klines(klines)
        assert len(result[0].klines) == 2


# ── 分型识别测试 ──────────────────────────────────────────────────────────


class TestFindFractals:
    """find_fractals 测试。"""

    def test_simple_ding_fx(self) -> None:
        """简单的顶分型：中间高，两边低。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 15, 15, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 1
        assert fxs[0].fx_type == FXType.DING
        assert fxs[0].val == 15.0
        assert fxs[0].k == cks[1]

    def test_simple_di_fx(self) -> None:
        """简单的底分型：中间低，两边高。"""
        cks = [
            _ck(0, "2025-01-02", 15, 12, 16, 12),
            _ck(1, "2025-01-03", 11, 9, 12, 9),
            _ck(2, "2025-01-06", 10, 13, 14, 10),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 1
        assert fxs[0].fx_type == FXType.DI
        assert fxs[0].val == 9.0

    def test_no_fractal(self) -> None:
        """单调序列不应有分型。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 14, 14, 12),
            _ck(2, "2025-01-06", 14, 16, 16, 14),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 0

    def test_alternating_ding_di(self) -> None:
        """交替的顶底分型。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),  # 上升
            _ck(1, "2025-01-03", 12, 15, 15, 11),  # 顶 (12<15, 14<15)
            _ck(2, "2025-01-06", 14, 11, 14, 10),  # 下降
            _ck(3, "2025-01-07", 10, 8, 11, 8),  # 底 (10>8, 9>8)
            _ck(4, "2025-01-08", 9, 13, 16, 9),  # 大幅上升
            _ck(5, "2025-01-09", 15, 10, 15, 10),  # 下降 → ck[4] 成为顶
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 3
        assert fxs[0].fx_type == FXType.DING  # ck[1]
        assert fxs[1].fx_type == FXType.DI  # ck[3]
        assert fxs[2].fx_type == FXType.DING  # ck[4]

    def test_insufficient_klines(self) -> None:
        """少于3根K线不应有分型。"""
        assert find_fractals([]) == []
        assert find_fractals([_ck(0, "2025-01-02", 10, 12, 12, 10)]) == []
        assert (
            find_fractals(
                [
                    _ck(0, "2025-01-02", 10, 12, 12, 10),
                    _ck(1, "2025-01-03", 12, 15, 15, 11),
                ]
            )
            == []
        )

    def test_equal_highs_no_ding(self) -> None:
        """相等高点不应形成顶分型。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 15, 10),
            _ck(1, "2025-01-03", 12, 14, 15, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 0

    def test_equal_lows_no_di(self) -> None:
        """相等低点不应形成底分型。"""
        cks = [
            _ck(0, "2025-01-02", 15, 12, 16, 9),
            _ck(1, "2025-01-03", 11, 10, 12, 9),
            _ck(2, "2025-01-06", 10, 13, 14, 10),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 0


# ── 笔计算测试 ────────────────────────────────────────────────────────────


class TestFindBis:
    """find_bis 测试。"""

    def test_strict_5_bars_minimum(self) -> None:
        """标准缠论铁律：做完包含处理后，一笔最少是 5 根 K 线（5个周期），这是下限，不能更少。"""
        # Case A: 只有 3 根处理后 K 线 (0, 1, 2)，绝对不能成笔
        cks_3 = [
            _ck(0, "2025-01-02", 10, 8, 10, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),  # 顶 (1)
            _ck(2, "2025-01-06", 14, 10, 14, 7),  # 底 (2)
        ]
        fxs_3 = find_fractals(cks_3)
        assert len(find_bis(fxs_3, cklines=cks_3)) == 0

        # Case B: 只有 4 根处理后 K 线 (0, 1, 2, 3)，绝对不能成笔
        cks_4 = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 16, 17, 12),  # 顶 (1)
            _ck(2, "2025-01-06", 14, 11, 14, 11),  # 中间只有 1 根
            _ck(3, "2025-01-07", 10, 8, 10, 7),    # 底 (3)
        ]
        fxs_4 = find_fractals(cks_4)
        assert len(find_bis(fxs_4, cklines=cks_4)) == 0

        # Case C: 达到 5 根处理后 K 线 (1, 2, 3, 4, 5)，满足标准成笔下限
        cks_5 = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 16, 17, 12),  # 顶分型 (1)
            _ck(2, "2025-01-06", 14, 13, 15, 13),  # 独立过渡 K 线 1
            _ck(3, "2025-01-07", 12, 10, 12, 10),  # 独立过渡 K 线 2
            _ck(4, "2025-01-08", 10, 8, 10, 8),    # 独立过渡 K 线 3
            _ck(5, "2025-01-09", 8, 6, 8, 5),      # 底分型 (5)
            _ck(6, "2025-01-10", 6, 9, 10, 6),
        ]
        fxs_5 = find_fractals(cks_5)
        bis_5 = find_bis(fxs_5, cklines=cks_5)
        assert len(bis_5) == 1
        assert bis_5[0].direction == Direction.DOWN
        assert abs(bis_5[0].end.k.index - bis_5[0].start.k.index) + 1 >= 5

    def test_simple_up_down_bi(self) -> None:
        """标准缠论：顶底两笔（向上 + 向下），每笔必须至少 5 根包含处理后 K 线。"""
        cks = [
            # 基础前置 K 线
            _ck(0, "2025-01-02", 11, 10, 11, 9),
            # 向上笔：底(1) -> 顶(5)，从 1 到 5 共 5 根
            _ck(1, "2025-01-03", 9, 8, 9, 7),      # 底分型极值 (1)
            _ck(2, "2025-01-06", 8, 10, 11, 8),
            _ck(3, "2025-01-07", 10, 13, 14, 10),
            _ck(4, "2025-01-08", 13, 16, 17, 13),
            _ck(5, "2025-01-09", 17, 20, 21, 16),  # 顶分型极值 (5)
            # 向下笔：顶(5) -> 底(9)，从 5 到 9 共 5 根
            _ck(6, "2025-01-10", 19, 17, 19, 16),
            _ck(7, "2025-01-13", 16, 14, 16, 13),
            _ck(8, "2025-01-14", 13, 11, 13, 10),
            _ck(9, "2025-01-15", 10, 7, 10, 6),    # 底分型极值 (9)
            _ck(10, "2025-01-16", 8, 10, 11, 7),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs, cklines=cks)
        assert len(bis) >= 2
        assert bis[0].direction == Direction.UP    # 底(1) -> 顶(5)
        assert bis[1].direction == Direction.DOWN  # 顶(5) -> 底(9)
        assert abs(bis[0].end.k.index - bis[0].start.k.index) + 1 >= 5
        assert abs(bis[1].end.k.index - bis[1].start.k.index) + 1 >= 5

    def test_new_bi_rule_needs_gap(self) -> None:
        """新笔规则：分型之间处理后 K 线不足 5 根不能成笔。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 15, 15, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs, cklines=cks)
        assert len(bis) == 0  # 1个分型无法成笔

    def test_ding_di_must_alternate(self) -> None:
        """笔的起止分型必须顶底交替：顶→底 或 底→顶。"""
        cks = [
            _ck(0, "2025-01-02", 9, 8, 10, 7),      # 底
            _ck(1, "2025-01-03", 8, 11, 12, 8),
            _ck(2, "2025-01-06", 11, 14, 15, 11),
            _ck(3, "2025-01-07", 14, 17, 18, 14),
            _ck(4, "2025-01-08", 18, 20, 21, 17),   # 顶
            _ck(5, "2025-01-09", 19, 16, 19, 15),
            _ck(6, "2025-01-10", 15, 13, 15, 12),
            _ck(7, "2025-01-13", 12, 10, 12, 9),
            _ck(8, "2025-01-14", 9, 6, 9, 5),       # 底
            _ck(9, "2025-01-15", 7, 9, 10, 6),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs, cklines=cks)
        for bi in bis:
            if bi.direction == Direction.UP:
                assert bi.start.fx_type == FXType.DI
                assert bi.end.fx_type == FXType.DING
            else:
                assert bi.start.fx_type == FXType.DING
                assert bi.end.fx_type == FXType.DI

    def test_empty_fractals(self) -> None:
        """空分型列表应返回空笔列表。"""
        assert find_bis([]) == []

    def test_bi_high_low(self) -> None:
        """笔的 high/low 应正确反映区间最高最低价。"""
        cks = [
            _ck(0, "2025-01-02", 15, 17, 18, 15),
            _ck(1, "2025-01-03", 17, 21, 22, 17),   # 顶分型 (22)
            _ck(2, "2025-01-06", 20, 17, 20, 16),
            _ck(3, "2025-01-07", 16, 13, 16, 12),
            _ck(4, "2025-01-08", 12, 10, 12, 9),
            _ck(5, "2025-01-09", 9, 6, 9, 5),       # 底分型 (5)
            _ck(6, "2025-01-10", 7, 9, 10, 6),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs, cklines=cks)
        if len(bis) > 0:
            # 顶→底（向下），high=22, low=5
            assert bis[0].high == 22.0
            assert bis[0].low == 5.0

    def test_full_pipeline_merge_to_bi(self) -> None:
        """完整管道测试：原始K线 → 合并 → 分型 → 笔（满足至少 5 根处理后 K 线）。"""
        klines = [
            _k(0, "2025-01-02", 10, 11, 12, 10, 100.0),
            _k(1, "2025-01-03", 12, 16, 17, 12, 100.0),  # 顶 (1)
            _k(2, "2025-01-06", 15, 13, 15, 13, 100.0),
            _k(3, "2025-01-07", 13, 11, 13, 11, 100.0),
            _k(4, "2025-01-08", 11, 9, 11, 9, 100.0),
            _k(5, "2025-01-09", 9, 7, 9, 7, 100.0),
            _k(6, "2025-01-10", 7, 5, 7, 4, 100.0),      # 底 (5)
            _k(7, "2025-01-13", 5, 8, 9, 5, 100.0),
        ]
        merged = merge_klines(klines)
        fxs = find_fractals(merged)
        bis = find_bis(fxs, cklines=merged)
        assert len(bis) >= 1
        assert abs(bis[0].end.k.index - bis[0].start.k.index) + 1 >= 5

    def test_fractal_trap_regression(self) -> None:
        """回归测试：密集交替分型不应卡死笔算法，并遵循标准成笔规则。"""
        cks = [
            _ck(0, "2025-01-02", 145, 145, 150, 140),
            _ck(1, "2025-01-03", 130, 130, 135, 125),  # di
            _ck(2, "2025-01-06", 140, 140, 145, 135),  # ding
            _ck(3, "2025-01-07", 125, 125, 130, 120),  # di
            _ck(4, "2025-01-08", 133, 133, 138, 128),  # ding
            _ck(5, "2025-01-09", 120, 120, 125, 115),  # di
            _ck(6, "2025-01-10", 127, 127, 132, 122),  # ding
            _ck(7, "2025-01-13", 113, 113, 118, 108),  # di
            _ck(8, "2025-01-14", 121, 121, 126, 116),  # ding
            _ck(9, "2025-01-15", 107, 107, 112, 102),  # di (overlap ends)
            _ck(10, "2025-01-16", 103, 103, 108, 98),
            _ck(11, "2025-01-17", 113, 113, 118, 108),  # ding
            _ck(12, "2025-01-20", 101, 101, 106, 96),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) >= 6
        bis = find_bis(fxs, cklines=cks)
        # 算法稳定运行不崩溃、不卡死
        assert isinstance(bis, list)


# ── 中枢计算测试 ──────────────────────────────────────────────────────────


class TestFindZss:
    """find_zss 测试。"""

    def test_three_overlapping_bis_form_zs(self) -> None:
        """标准缠论：三笔重叠（每笔至少 5 根处理后 K 线）形成中枢。"""
        cks = [
            # 前置 K 线
            _ck(0, "2025-01-02", 11, 10, 11, 9),
            # 笔 1 (UP): 底(1) -> 顶(5), 5 根
            _ck(1, "2025-01-03", 9, 8, 9, 7),      # 底 (7)
            _ck(2, "2025-01-06", 8, 11, 12, 8),
            _ck(3, "2025-01-07", 11, 14, 15, 11),
            _ck(4, "2025-01-08", 14, 17, 18, 14),
            _ck(5, "2025-01-09", 18, 20, 21, 17),  # 顶 (21)
            # 笔 2 (DOWN): 顶(5) -> 底(9), 5 根
            _ck(6, "2025-01-10", 19, 16, 19, 15),
            _ck(7, "2025-01-13", 15, 13, 15, 12),
            _ck(8, "2025-01-14", 13, 11, 13, 10),
            _ck(9, "2025-01-15", 11, 9, 11, 8),   # 底 (8)
            # 笔 3 (UP): 底(9) -> 顶(13), 5 根
            _ck(10, "2025-01-16", 9, 12, 13, 9),
            _ck(11, "2025-01-17", 12, 15, 16, 12),
            _ck(12, "2025-01-20", 15, 17, 18, 14),
            _ck(13, "2025-01-21", 17, 19, 20, 16), # 顶 (20)
            # 后置 K 线
            _ck(14, "2025-01-22", 18, 16, 18, 15),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs, cklines=cks)
        assert len(bis) >= 3
        zss = find_zss(bis)
        assert len(zss) >= 1
        zs = zss[0]
        assert zs.zg > zs.zd
        assert zs.gg >= zs.zg
        assert zs.dd <= zs.zd

    def test_no_overlap_no_zs(self) -> None:
        """笔之间无重叠不应形成中枢。"""
        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),
            _ck(2, "2025-01-06", 14, 16, 18, 15),
            _ck(3, "2025-01-07", 16, 20, 22, 16),
            _ck(4, "2025-01-08", 20, 25, 26, 20),
            _ck(5, "2025-01-09", 25, 22, 26, 22),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        zss = find_zss(bis)
        assert len(zss) == 0

    def test_empty_bis_no_zs(self) -> None:
        """空笔列表不应有中枢。"""
        assert find_zss([]) == []

    def test_zs_overlap_properties(self) -> None:
        """中枢应有正确的重叠区间属性。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 13, 10),
            _ck(1, "2025-01-03", 12, 15, 16, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 13, 14, 9),
            _ck(4, "2025-01-08", 12, 14, 15, 11),
            _ck(5, "2025-01-09", 14, 12, 14, 11),
            _ck(6, "2025-01-10", 11, 9, 12, 8),
            _ck(7, "2025-01-13", 10, 11, 12, 9),
            _ck(8, "2025-01-14", 11, 6, 12, 5),
            _ck(9, "2025-01-15", 7, 8, 9, 6),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        zss = find_zss(bis)
        if len(zss) > 0:
            zs = zss[0]
            # 中枢基本属性
            assert zs.zg > zs.zd
            assert zs.gg >= zs.zg
            assert zs.dd <= zs.zd
            assert zs.line_count >= 3


# ── Analyser 集成测试 ────────────────────────────────────────────────────


class TestChanlunAnalyser:
    """ChanlunAnalyser 完整管道测试。"""

    def test_analyse_with_dataframe(self) -> None:
        """使用模拟 DataFrame 测试完整管道。"""
        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        dates = pd.date_range("2025-01-02", periods=20, freq="B")
        data = {
            "datetime": dates,
            "open": [10, 8, 12, 16, 14, 10, 7, 12, 14, 12, 10, 6, 7, 12, 9, 10, 14, 12, 8, 9],
            "close": [8, 12, 16, 14, 10, 7, 12, 14, 12, 10, 6, 7, 12, 9, 10, 14, 12, 8, 9, 11],
            "high": [11, 13, 17, 18, 15, 11, 13, 15, 14, 13, 11, 8, 13, 12, 11, 15, 14, 13, 9, 12],
            "low": [7, 7, 11, 13, 9, 5, 6, 11, 11, 9, 5, 5, 6, 8, 8, 9, 11, 7, 7, 9],
            "vol": [1000] * 20,
        }
        df = pd.DataFrame(data)

        analyser = ChanlunAnalyser(code="SZ000001", frequency="DAILY")
        result = analyser.process_klines(df)

        assert result.code == "SZ000001"
        assert result.frequency == "DAILY"
        assert len(result.klines) == 20
        assert len(result.cklines) > 0
        assert len(result.cklines) <= 20
        assert len(result.fractals) >= 0
        assert len(result.bis) >= 0

    def test_empty_dataframe(self) -> None:
        """空 DataFrame 应返回空结果。"""
        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        df = pd.DataFrame(columns=["datetime", "open", "close", "high", "low", "vol"])
        analyser = ChanlunAnalyser(code="SZ000001")
        result = analyser.process_klines(df)
        assert len(result.klines) == 0
        assert len(result.bis) == 0

    def test_result_to_dict(self) -> None:
        """结果应可序列化为字典。"""
        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        dates = pd.date_range("2025-01-02", periods=10, freq="B")
        data = {
            "datetime": dates,
            "open": [10, 8, 12, 16, 14, 10, 7, 12, 14, 12],
            "close": [8, 12, 16, 14, 10, 7, 12, 14, 12, 10],
            "high": [11, 13, 17, 18, 15, 11, 13, 15, 14, 13],
            "low": [7, 7, 11, 13, 9, 5, 6, 11, 11, 9],
            "vol": [1000] * 10,
        }
        df = pd.DataFrame(data)
        analyser = ChanlunAnalyser(code="SZ000001")
        result = analyser.process_klines(df)
        d = result.to_dict()

        assert "code" in d
        assert "bi_count" in d
        assert "zs_count" in d
        assert "bis" in d
        assert "zss" in d

        # 可视化字段：中枢/买卖点/背驰应携带对应 K 线日期（若该样本产出了它们）
        import re

        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        for zs in d["zss"]:
            assert "start_date" in zs
            assert "end_date" in zs
            if zs["start_date"] is not None:
                assert date_re.match(zs["start_date"])
            if zs["end_date"] is not None:
                assert date_re.match(zs["end_date"])

        for mmd in d["mmds"]:
            assert "date" in mmd
            if mmd["date"] is not None:
                assert date_re.match(mmd["date"])

        for bc in d["bcs"]:
            assert "curr_date" in bc
            assert "prev_date" in bc
            if bc["curr_date"] is not None:
                assert date_re.match(bc["curr_date"])
            if bc["prev_date"] is not None:
                assert date_re.match(bc["prev_date"])

    def test_result_to_dict_with_visual_dates(self) -> None:
        """可视化字段：足够数据下 zss/mmds/bcs 应携带合法 K 线日期。

        用一段振荡+趋势的数据，确保能确定性产出中枢/买卖点/背驰，
        从而真正覆盖 to_dict() 的日期输出分支。
        """
        import math
        import re

        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        dates = pd.date_range("2025-01-02", periods=40, freq="B")
        highs = [15 + 5 * math.sin(i / 2) + i * 0.2 for i in range(40)]
        lows = [highs[i] - 4 for i in range(40)]
        df = pd.DataFrame(
            {
                "datetime": dates,
                "open": [h - 2 for h in highs],
                "close": [h - 1 for h in highs],
                "high": highs,
                "low": lows,
                "vol": [1000] * 40,
            }
        )
        analyser = ChanlunAnalyser(code="SZ000001")
        d = analyser.process_klines(df).to_dict()

        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        # 中枢必须有起止日期
        assert len(d["zss"]) > 0
        for zs in d["zss"]:
            assert zs["start_date"] is not None
            assert zs["end_date"] is not None
            assert date_re.match(zs["start_date"])
            assert date_re.match(zs["end_date"])

        # 买卖点必须有触发日期
        assert len(d["mmds"]) > 0
        for mmd in d["mmds"]:
            assert mmd["date"] is not None
            assert date_re.match(mmd["date"])

        # 背驰必须有当前笔 + 对照笔日期
        assert len(d["bcs"]) > 0
        for bc in d["bcs"]:
            assert bc["curr_date"] is not None
            assert bc["prev_date"] is not None
            assert date_re.match(bc["curr_date"])
            assert date_re.match(bc["prev_date"])

    def test_result_to_dict_minute_frequency_includes_time(self) -> None:
        """分钟级别 frequency 下，日期字段应输出完整时分 YYYY-MM-DD HH:MM。

        对应网友反馈：分钟/低级别也需要时分用于分时可视化。
        覆盖 CLI 原始值（5MIN/30MIN）与 Web 映射值（5min/30min）两种大小写。
        """
        import math
        import re

        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        dates = pd.date_range("2025-01-02 09:30", periods=60, freq="5min")
        highs = [15 + 5 * math.sin(i / 2) + i * 0.01 for i in range(60)]
        lows = [highs[i] - 1.5 for i in range(60)]
        df = pd.DataFrame(
            {
                "datetime": dates,
                "open": [h - 0.5 for h in highs],
                "close": [h - 0.2 for h in highs],
                "high": highs,
                "low": lows,
                "vol": [1000] * 60,
            }
        )
        datetime_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

        # CLI 原始值（大写 5MIN）与 Web 映射值（小写 5min）应行为一致
        for freq in ("5MIN", "5min"):
            d = ChanlunAnalyser(code="SZ000001", frequency=freq).process_klines(df).to_dict()

            # bis 日期应带时分
            assert len(d["bis"]) > 0
            for bi in d["bis"]:
                assert datetime_re.match(bi["start_date"])
                assert datetime_re.match(bi["end_date"])

            # zss/mmds/bcs 若产出，同样应带时分（有就检查）
            for zs in d["zss"]:
                if zs["start_date"] is not None:
                    assert datetime_re.match(zs["start_date"])
                if zs["end_date"] is not None:
                    assert datetime_re.match(zs["end_date"])
            for mmd in d["mmds"]:
                if mmd["date"] is not None:
                    assert datetime_re.match(mmd["date"])
            for bc in d["bcs"]:
                if bc["curr_date"] is not None:
                    assert datetime_re.match(bc["curr_date"])
                if bc["prev_date"] is not None:
                    assert datetime_re.match(bc["prev_date"])

    def test_print_table_with_dates(self) -> None:
        """CLI table 模式应正确消费 zss/mmds/bcs 的日期字段。

        用能确定性产出中枢/买卖点/背驰的数据，调 _print_table 确保不抛异常、
        且输出中包含新增的日期标记（→ 表示日期区间）。
        """
        import contextlib
        import io
        import math

        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser
        from easy_tdx.cli.cmd_chanlun import _print_table

        dates = pd.date_range("2025-01-02", periods=40, freq="B")
        highs = [15 + 5 * math.sin(i / 2) + i * 0.2 for i in range(40)]
        lows = [highs[i] - 4 for i in range(40)]
        df = pd.DataFrame(
            {
                "datetime": dates,
                "open": [h - 2 for h in highs],
                "close": [h - 1 for h in highs],
                "high": highs,
                "low": lows,
                "vol": [1000] * 40,
            }
        )
        d = ChanlunAnalyser(code="SZ000001", frequency="DAILY").process_klines(df).to_dict()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_table(d)
        out = buf.getvalue()

        # 中枢/买卖点/背驰都应出现，且中枢行应含日期区间箭头
        assert "── 中枢 ──" in out
        assert "── 买卖点 ──" in out
        assert "── 背驰 ──" in out
        # 中枢行格式：[idx] <start> → <end> zg=...
        assert "→" in out


class TestChanlunMergedChart:
    """测试缠论多周期引擎严格K线包含合并输出。"""

    def test_merged_chart_structure_and_indicators(self) -> None:
        import pandas as pd
        from easy_tdx.chanlun.resonance import build_merged_chart_data
        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        # 构造含包含关系的 K 线
        dates = [f"2025-01-{i+1:02d}" for i in range(30)]
        opens = [10.0 + i for i in range(30)]
        closes = [10.5 + i for i in range(30)]
        highs = [12.0 + i for i in range(30)]
        lows = [9.0 + i for i in range(30)]
        # 制造几对包含关系
        highs[2] = highs[1] - 0.5
        lows[2] = lows[1] + 0.5
        highs[5] = highs[4] + 1.0
        lows[5] = lows[4] - 1.0

        df = pd.DataFrame({
            "datetime": dates,
            "open": opens,
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": [1000] * 30,
            "amount": [10000] * 30,
        })
        res = ChanlunAnalyser(code="TEST", frequency="DAILY").process_klines(df)
        mc = build_merged_chart_data(
            low_res=res,
            base_df=df,
            dates=dates,
            high_bis=[],
            high_zss=[],
            mid_bis=[],
            mid_zss=[],
            mmd_marks=[],
            res_marks=[],
        )
        assert len(mc["candles"]) < len(df)  # 包含合并后 K 线数量少于原始 K 线
        assert len(mc["candles"]) == len(mc["dates"])
        assert len(mc["volumes"]) == len(mc["dates"])
        assert len(mc["amounts"]) == len(mc["dates"])
        assert len(mc["macd"]["hist"]) == len(mc["dates"])
        assert len(mc["macd"]["dif"]) == len(mc["dates"])
        assert len(mc["macd"]["dea"]) == len(mc["dates"])
        assert len(mc["rsi"]["rsi6"]) == len(mc["dates"])
        assert len(mc["kdj"]["k"]) == len(mc["dates"])
        assert len(mc["expma"]["exp12"]) == len(mc["dates"])

        # 严格验证缠论标准：只有最高和最低，绝无上下影线
        for candle in mc["candles"]:
            o, c, l, h = candle
            upper_shadow = round(h - max(o, c), 4)
            lower_shadow = round(min(o, c) - l, 4)
            assert upper_shadow == 0.0, f"Upper shadow must be 0, got {upper_shadow} for candle {candle}"
            assert lower_shadow == 0.0, f"Lower shadow must be 0, got {lower_shadow} for candle {candle}"
            assert (o == l and c == h) or (o == h and c == l)

    def test_consecutive_included_upward_merge(self) -> None:
        """测试准则2：前面是非包含、向上（前高抬高） → 整串连续包含统一「向上合并：取高高」且方向全程锁定。"""
        from easy_tdx.chanlun.kline_merge import merge_klines

        # K0: [10, 15] 基准非包含
        # K1: [12, 18] 相对K0前高抬高 (18 > 15) -> 确立整串向上合并!
        # K2: [13, 16] 被K1包含 (16 <= 18 且 13 >= 12) -> 向上合并取高高: high=max(18,16)=18, low=max(12,13)=13
        # K3: [14, 17] 被合并后[13, 18]包含 -> 保持向上合并取高高: high=max(18,17)=18, low=max(13,14)=14
        # K4: [15, 20] 与[14, 18]无包含 (20 > 18 且 15 > 14) -> 连续包含结束!
        klines = [
            _k(0, "2025-01-01", 11, 14, 15, 10, 100),
            _k(1, "2025-01-02", 13, 17, 18, 12, 100),
            _k(2, "2025-01-03", 14, 15, 16, 13, 100),
            _k(3, "2025-01-04", 15, 16, 17, 14, 100),
            _k(4, "2025-01-05", 16, 19, 20, 15, 100),
        ]
        res = merge_klines(klines)
        # 应合并为 3 根 K 线: K0, 合并后的(K1+K2+K3), K4
        assert len(res) == 3
        mid = res[1]
        assert mid.merged_count == 3
        assert mid.direction == "up"
        assert mid.high == 18.0  # 高点取最大: max(18, 16, 17) = 18
        assert mid.low == 14.0   # 低点取较高: max(12, 13, 14) = 14

    def test_consecutive_included_downward_merge(self) -> None:
        """测试准则2：前面是非包含、向下（前高降低） → 整串连续包含统一「向下合并：取低低」且方向全程锁定。"""
        from easy_tdx.chanlun.kline_merge import merge_klines

        # K0: [15, 20] 基准非包含
        # K1: [12, 17] 相对K0前高降低 (17 < 20) -> 确立整串向下合并!
        # K2: [13, 16] 被K1包含 (16 <= 17 且 13 >= 12) -> 向下合并取低低: high=min(17,16)=16, low=min(12,13)=12
        # K3: [14, 15] 被合并后[12, 16]包含 -> 保持向下合并取低低: high=min(16,15)=15, low=min(12,14)=12
        # K4: [9, 11] 与[12, 15]无包含 (11 < 15 且 9 < 12) -> 连续包含结束!
        klines = [
            _k(0, "2025-01-01", 16, 19, 20, 15, 100),
            _k(1, "2025-01-02", 13, 16, 17, 12, 100),
            _k(2, "2025-01-03", 14, 15, 16, 13, 100),
            _k(3, "2025-01-04", 14, 14.5, 15, 14, 100),
            _k(4, "2025-01-05", 10, 10.5, 11, 9, 100),
        ]
        res = merge_klines(klines)
        assert len(res) == 3
        mid = res[1]
        assert mid.merged_count == 3
        assert mid.direction == "down"
        assert mid.high == 15.0  # 高点取较低: min(17, 16, 15) = 15
        assert mid.low == 12.0   # 低点取最小: min(12, 13, 14) = 12

    def test_higher_low_after_1buy_is_2buy_not_1buy(self) -> None:
        """测试缠论公理：一买之后回踩不创新低（low >= prev_low）必须判定为二买(2BUY)，绝不能误判为一买(1BUY)。"""
        from easy_tdx.chanlun.types import Direction, MMDType, MMD, ZS
        from easy_tdx.chanlun.mmd import _check_buy_point

        class DummyK:
            def __init__(self, d: str, k_idx: int):
                self.date = d
                self.k_index = k_idx

        class DummyFX:
            def __init__(self, val: float, d: str, k_idx: int):
                self.val = val
                self.k = DummyK(d, k_idx)

        class DummyBI:
            def __init__(self, idx: int, s_val: float, e_val: float, s_d: str, e_d: str, s_idx: int, e_idx: int):
                self.index = idx
                self.direction = Direction.UP if e_val > s_val else Direction.DOWN
                self.start = DummyFX(s_val, s_d, s_idx)
                self.end = DummyFX(e_val, e_d, e_idx)
                self.high = max(s_val, e_val)
                self.low = min(s_val, e_val)

        # 构建一个下跌中枢以及一买后的回踩：
        # bi0: 下跌 (20 -> 14)
        # bi1: 反弹 (14 -> 17)
        # bi2: 回落 (17 -> 15)
        # bi3: 离开中枢跌至一买底背驰 (15 -> 11.60) -> 1BUY
        # bi4: 一买后次级别向上反弹 (11.60 -> 13.00)
        # bi5: 次次回踩不破前低 (13.00 -> 12.00) -> 必须是 2BUY，绝不是 1BUY!
        b0 = DummyBI(0, 20.0, 14.0, "2026-01-01", "2026-01-05", 0, 4)
        b1 = DummyBI(1, 14.0, 17.0, "2026-01-05", "2026-01-10", 4, 8)
        b2 = DummyBI(2, 17.0, 15.0, "2026-01-10", "2026-01-15", 8, 12)
        b3 = DummyBI(3, 15.0, 11.6, "2026-01-15", "2026-01-20", 12, 16)
        b4 = DummyBI(4, 11.6, 13.0, "2026-01-20", "2026-01-25", 16, 20)
        b5 = DummyBI(5, 13.0, 12.0, "2026-01-25", "2026-01-30", 20, 24)

        all_bis = [b0, b1, b2, b3, b4, b5]
        zs = ZS(zd=14.0, zg=17.0, dd=11.6, gg=20.0, lines=[b0, b1, b2])

        mmd = _check_buy_point(b5, zs, all_bis)
        assert mmd is not None
        assert mmd.mmd_type == MMDType.BUY_2
        assert "二类买点" in mmd.msg

    def test_czsc_lesson20_buy3_first_pullback_only(self) -> None:
        """缠论第20课走势中枢级别扩张及第三类买卖点定理：
        向上离开中枢后，以一个次级别走势类型回试，其低点不跌破 ZG，构成第三类买点。
        必须是突破后的【第1次首次回试】！第2次回踩绝不是3买。
        """
        from easy_tdx.chanlun.mmd import find_mmds
        from easy_tdx.chanlun.types import MMDType, ZS

        class DummyK:
            def __init__(self, d: str, k_idx: int):
                self.date = d
                self.k_index = k_idx

        class DummyFX:
            def __init__(self, val: float, d: str, k_idx: int):
                self.val = val
                self.k = DummyK(d, k_idx)

        class DummyBI:
            def __init__(self, idx: int, s_val: float, e_val: float):
                self.index = idx
                self.direction = Direction.UP if e_val > s_val else Direction.DOWN
                self.start = DummyFX(s_val, f"2026-01-{idx:02d}", idx * 5)
                self.end = DummyFX(e_val, f"2026-01-{idx+1:02d}", (idx + 1) * 5)
                self.high = max(s_val, e_val)
                self.low = min(s_val, e_val)

        # 构建中枢：zd=10.0, zg=15.0
        # b0: 10->15 (UP)
        # b1: 15->11 (DOWN)
        # b2: 11->14 (UP)
        b0 = DummyBI(0, 10.0, 15.0)
        b1 = DummyBI(1, 15.0, 11.0)
        b2 = DummyBI(2, 11.0, 14.0)
        zs = ZS(zd=11.0, zg=14.0, dd=10.0, gg=15.0, lines=[b0, b1, b2])

        # b3: 向上离开中枢 (14.0 -> 20.0, UP) 突破 zg=14.0
        b3 = DummyBI(3, 14.0, 20.0)
        # b4: 首次回踩 (20.0 -> 16.0, DOWN) 不破 zg=14.0 -> 这是标准的 3 买！
        b4 = DummyBI(4, 20.0, 16.0)
        # b5: 再次冲高 (16.0 -> 22.0, UP)
        b5 = DummyBI(5, 16.0, 22.0)
        # b6: 第二次回踩 (22.0 -> 15.0, DOWN) 虽然 low=15.0 >= zg=14.0，但绝不是 3 买！
        b6 = DummyBI(6, 22.0, 15.0)

        all_bis = [b0, b1, b2, b3, b4, b5, b6]
        mmds = find_mmds(all_bis, [zs])

        # 检查买点：b4 是 3 买，b6 绝不可被判定为 3 买
        buy_mmds = [m for m in mmds if m.mmd_type == MMDType.BUY_3]
        assert len(buy_mmds) == 1
        assert buy_mmds[0].bi.index == 4  # 仅首次回踩 b4 是 3 买

    def test_czsc_lesson20_buy3_blocked_by_new_zs(self) -> None:
        """逸豪新材周线场景回归：离开原中枢后形成了新的同级别中枢，
        原老中枢使命终结，新中枢内部的回踩绝不可跨中枢被误判为老中枢的 3 买。
        """
        from easy_tdx.chanlun.mmd import find_mmds
        from easy_tdx.chanlun.types import MMDType, ZS

        class DummyK:
            def __init__(self, d: str, k_idx: int):
                self.date = d
                self.k_index = k_idx

        class DummyFX:
            def __init__(self, val: float, d: str, k_idx: int):
                self.val = val
                self.k = DummyK(d, k_idx)

        class DummyBI:
            def __init__(self, idx: int, s_val: float, e_val: float):
                self.index = idx
                self.direction = Direction.UP if e_val > s_val else Direction.DOWN
                self.start = DummyFX(s_val, f"2026-01-{idx:02d}", idx * 5)
                self.end = DummyFX(e_val, f"2026-01-{idx+1:02d}", (idx + 1) * 5)
                self.high = max(s_val, e_val)
                self.low = min(s_val, e_val)

        # 老中枢 ZS0: lines [b0, b1, b2], zd=10, zg=15
        b0 = DummyBI(0, 10.0, 15.0)
        b1 = DummyBI(1, 15.0, 11.0)
        b2 = DummyBI(2, 11.0, 14.0)
        zs0 = ZS(zd=11.0, zg=14.0, dd=10.0, gg=15.0, lines=[b0, b1, b2])

        # 向上离开老中枢并走高
        b3 = DummyBI(3, 14.0, 40.0)

        # 在高位震荡形成新中枢 ZS1: lines [b4, b5, b6]
        b4 = DummyBI(4, 40.0, 25.0)
        b5 = DummyBI(5, 25.0, 35.0)
        b6 = DummyBI(6, 35.0, 26.0)
        zs1 = ZS(zd=26.0, zg=35.0, dd=25.0, gg=40.0, lines=[b4, b5, b6])

        # 走势在 2026-07 回调至 25.0 (b7)
        b7 = DummyBI(7, 35.0, 25.0)

        all_bis = [b0, b1, b2, b3, b4, b5, b6, b7]
        mmds = find_mmds(all_bis, [zs0, zs1])

        # zs0 绝不能在 b7 处产生 3 买
        zs0_3buys = [m for m in mmds if m.zs == zs0 and m.mmd_type == MMDType.BUY_3]
        assert len(zs0_3buys) == 0


