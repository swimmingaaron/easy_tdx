"""笔计算。

笔的定义：
- 由相邻的顶底分型连接而成
- 顶→底 = 向下笔，底→顶 = 向上笔
- 新笔规则：分型之间至少有 1 根独立缠论 K 线（即分型中间 K 线的 index 差 > 2）
- 老笔规则：分型之间至少有 3 根缠论 K 线
- 简单笔规则：只要顶底交替即可

优化（v2）：
1. 修复 pending_opposite 时同向极值更新逻辑：有 pending 时仍应更新 start_fx 为更极端值
   （否则会固定在一个不够极端的位置，让后续笔的 gap 判断失准）
2. 正确计算 bi.high / bi.low：扫描区间内全部缠论 K 线取真实极值，而非仅用分型端点值
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, FX, CLKline, Direction, FXType


def _can_form_bi(
    start: FX,
    end: FX,
    config: ChanlunConfig,
) -> bool:
    """判断两个分型是否可以构成一笔。"""
    # 顶底必须交替
    if start.fx_type == end.fx_type:
        return False

    # 分型之间缠论 K 线的间距
    # 独立 K 线数 = end.left.index - start.right.index + 1（如果 >0）
    gap = end.klines[0].index - start.klines[2].index + 1

    if config.bi_type == "new":
        # 新笔：至少1根独立K线
        return gap >= 1
    elif config.bi_type == "old":
        # 老笔：至少3根缠论K线在分型之间
        return gap >= 3
    else:
        # simple：只要顶底交替即可
        return True


def _calc_bi_range(
    start: FX,
    end: FX,
    all_cklines: list[CLKline],
) -> tuple[float, float]:
    """计算笔内区间的真实最高/最低价（扫描区间内所有缠论K线）。

    仅使用分型端点值会遗漏区间内中间缠论K线的极值，
    例如向上笔的途中可能有合并K线产生更低的 low。

    Returns:
        (high, low) 区间内真实极值
    """
    # 取笔起始和结束分型中间 K 线的缠论K线 index
    start_ck_idx = start.k.index
    end_ck_idx = end.k.index

    if not all_cklines or start_ck_idx > end_ck_idx:
        # 回退到分型端点值
        h = max(start.val, end.val)
        l = min(start.val, end.val)
        return h, l

    lo = min(start_ck_idx, end_ck_idx)
    hi = max(start_ck_idx, end_ck_idx)

    high_val = max(ck.high for ck in all_cklines[lo: hi + 1])
    low_val = min(ck.low for ck in all_cklines[lo: hi + 1])
    return high_val, low_val


def find_bis(
    fxs: list[FX],
    config: ChanlunConfig | None = None,
    cklines: list[CLKline] | None = None,
) -> list[BI]:
    """从分型列表中计算笔（严格连续折线状态机）。

    核心原则（连续性公理）：
    1. 笔序列在几何上必须构成首尾无缝相接的连续折线 (bis[i].end == bis[i+1].start)，绝不允许断层。
    2. 当最后一笔形成后，若后续同向分型创出更极端价格（未确立反向笔前），
       属于前一笔的延伸，直接更新前一笔的 end 为该更极端分型。
    3. 只有当反向分型与前一笔终点满足成笔条件时，才确认生成下一笔，且新笔的 start 严格等于前一笔的 end。

    Args:
        fxs: 分型列表（顶底交替）
        config: 缠论配置
        cklines: 缠论K线列表（可选，用于计算笔内真实高低）

    Returns:
        笔列表（首尾绝对无缝连续）
    """
    if config is None:
        config = ChanlunConfig()

    if len(fxs) < 2:
        return []

    bis: list[BI] = []

    # 1. 寻找第一笔
    i = 0
    start_fx = fxs[0]
    while i < len(fxs) - 1:
        i += 1
        cur = fxs[i]
        if cur.fx_type == start_fx.fx_type:
            # 同向更极端，更新起始点
            if (start_fx.fx_type == FXType.DING and cur.val > start_fx.val) or \
               (start_fx.fx_type == FXType.DI and cur.val < start_fx.val):
                start_fx = cur
            continue

        if _can_form_bi(start_fx, cur, config):
            direction = Direction.UP if start_fx.fx_type == FXType.DI else Direction.DOWN
            if cklines:
                high, low = _calc_bi_range(start_fx, cur, cklines)
            else:
                high = max(start_fx.val, cur.val)
                low = min(start_fx.val, cur.val)
            bis.append(BI(start=start_fx, end=cur, direction=direction, index=0, high=high, low=low))
            break

    if not bis:
        return []

    # 2. 依次寻找后续笔（保持首尾连续）
    for fx in fxs[i:]:
        last_bi = bis[-1]
        expected_type = FXType.DI if last_bi.direction == Direction.UP else FXType.DING
        same_type = FXType.DING if last_bi.direction == Direction.UP else FXType.DI

        if fx.fx_type == same_type:
            # 同类型分型：检查是否是前一笔的延伸（创出更极端价格）
            if (last_bi.direction == Direction.UP and fx.val > last_bi.end.val) or \
               (last_bi.direction == Direction.DOWN and fx.val < last_bi.end.val):
                last_bi.end = fx
                if cklines:
                    last_bi.high, last_bi.low = _calc_bi_range(last_bi.start, fx, cklines)
                else:
                    last_bi.high = max(last_bi.start.val, fx.val)
                    last_bi.low = min(last_bi.start.val, fx.val)
            continue

        elif fx.fx_type == expected_type:
            # 反向分型：检查与当前最后一笔终点能否构成新笔
            if _can_form_bi(last_bi.end, fx, config):
                direction = Direction.DOWN if last_bi.direction == Direction.UP else Direction.UP
                if cklines:
                    high, low = _calc_bi_range(last_bi.end, fx, cklines)
                else:
                    high = max(last_bi.end.val, fx.val)
                    low = min(last_bi.end.val, fx.val)
                new_bi = BI(
                    start=last_bi.end,
                    end=fx,
                    direction=direction,
                    index=len(bis),
                    high=high,
                    low=low,
                )
                bis.append(new_bi)

    return bis

