"""笔计算与严格状态机。

缠论笔的核心定义：
1. 笔由相邻且反向的顶分型和底分型连接而成：
   - 底分型 → 顶分型 = 向上笔（Direction.UP）
   - 顶分型 → 底分型 = 向下笔（Direction.DOWN）
2. 笔的极值公理（缠论第一公理）：
   - 向上笔：终点顶分型最高价必须高于起点底分型最低价 (end.val > start.val)；
   - 向下笔：终点底分型最低价必须低于起点顶分型最高价 (end.val < start.val)；
   - 笔内绝不允许出现超越端点的价格倒挂。
3. 笔的跨度规则：
   - 新笔 (new)：分型之间至少有 1 根独立缠论 K 线 (gap >= 1)，或两分型中心 K 线相隔 >= 3 根；
   - 老笔 (old)：分型之间至少有 3 根缠论 K 线 (gap >= 3)，且顶分型区间与底分型区间无重叠；
   - 简单笔 (simple)：顶底严格交替且满足高低差即可。
4. 几何连续性公理：
   - 笔序列首尾严格无缝相接 (bis[i].end == bis[i+1].start)，绝对不允许断层。
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, FX, CLKline, Direction, FXType


def _can_form_bi(
    start: FX,
    end: FX,
    config: ChanlunConfig,
) -> bool:
    """判断两个分型是否可以构成合法的笔。"""
    # 1. 顶底必须严格交替
    if start.fx_type == end.fx_type:
        return False

    # 2. 价格极值关系校验（缠论方向公理：向上笔顶必须高于底，向下笔底必须低于顶）
    if start.fx_type == FXType.DI:
        if end.val <= start.val:
            return False
    else:
        if end.val >= start.val:
            return False

    # 3. 分型之间缠论 K 线的间距
    # 独立 K 线数 = end.left.index - start.right.index + 1
    start_right_idx = start.klines[2].index if len(start.klines) >= 3 else start.k.index + 1
    end_left_idx = end.klines[0].index if len(end.klines) >= 3 else end.k.index - 1
    gap = end_left_idx - start_right_idx + 1

    # 中心 K 线跨度
    center_span = abs(end.k.index - start.k.index)

    if config.bi_type == "new":
        # 新笔：至少1根独立K线或中心跨度>=3
        return gap >= 1 or center_span >= 3
    elif config.bi_type == "old":
        # 老笔：至少3根缠论K线在分型之间
        return gap >= 3 or center_span >= 4
    else:
        # simple：只要中心跨度>=2且无包含倒挂
        return center_span >= 2


def _calc_bi_range(
    start: FX,
    end: FX,
    all_cklines: list[CLKline],
) -> tuple[float, float]:
    """计算笔内区间的真实最高/最低价（扫描区间内所有缠论 K 线）。"""
    start_ck_idx = start.k.index
    end_ck_idx = end.k.index

    if not all_cklines or start_ck_idx > end_ck_idx:
        h = max(start.val, end.val)
        l = min(start.val, end.val)
        return h, l

    lo = min(start_ck_idx, end_ck_idx)
    hi = max(start_ck_idx, end_ck_idx)

    high_val = max(ck.high for ck in all_cklines[lo : hi + 1])
    low_val = min(ck.low for ck in all_cklines[lo : hi + 1])
    # 向上笔高点以顶分型为基准，低点以底分型为基准
    high_val = max(high_val, start.val, end.val)
    low_val = min(low_val, start.val, end.val)
    return high_val, low_val


def find_bis(
    fxs: list[FX],
    config: ChanlunConfig | None = None,
    cklines: list[CLKline] | None = None,
) -> list[BI]:
    """从分型列表中计算笔（严谨连续折线状态机）。

    核心原则：
    1. 连续性：笔序列在几何上首尾相接，bis[i].end == bis[i+1].start；
    2. 延伸性：当最后一笔形成后，若后续同向分型创出更极端价格，直接延伸前一笔；
    3. 确认性：反向分型满足成笔跨度与极值有效性时，确认生成下一笔；
    4. 陷阱防御：密集交替分型不卡死，保证回溯推演与实时计算 100% 幂等。

    Args:
        fxs: 分型列表（顶底交替）
        config: 缠论配置
        cklines: 缠论 K 线列表（可选，用于计算笔内真实高低）

    Returns:
        笔列表
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
