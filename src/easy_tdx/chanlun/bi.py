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
    config: ChanlunConfig | None = None,
    cklines: list[CLKline] | None = None,
) -> bool:
    """判断两个分型是否可以构成合法的标准缠论笔。

    标准缠论核心公理（铁律）：
    1. 顶底严格交替（底分型 -> 顶分型 为向上笔；顶分型 -> 底分型 为向下笔）；
    2. 极值方向公理：向上笔顶高于底 (end.val > start.val)，向下笔底低于顶 (end.val < start.val)；
    3. ⚠️ 核心下限：必须以做完包含处理后的缠论 K 线为前提，最少是 5 根 K 线（5 个周期），
       这是绝对下限，不能更少：
       bars_count = abs(end.k.index - start.k.index) + 1 >= 5 （即 index 跨度 >= 4）；
       若配置为 "old"（老笔），则下限为 7 根 K 线（bars_count >= 7）；
    4. 笔内无倒挂公理（扫描两端之间的所有合并处理后 K 线）：
       - 向上笔：起点必须是笔内最低价，终点必须是笔内最高价；
       - 向下笔：起点必须是笔内最高价，终点必须是笔内最低价。
    """
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

    # 3. ⚠️ 核心下限：处理后 K 线最少 5 根（5 个周期）下限
    s_idx = start.k.index
    e_idx = end.k.index
    bars_count = abs(e_idx - s_idx) + 1

    min_bars = 7 if (config and config.bi_type == "old") else 5
    if bars_count < min_bars:
        return False

    return True


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
    """从分型列表中计算标准缠论笔（严格遵循包含处理后至少 5 根 K 线下限）。

    核心原则：
    1. 前提：K 线已提前做完包含处理（merge_klines）；
    2. 下限：一笔最少是 5 根处理后的 K 线（bars_count >= 5），这是下限，不能更少；
    3. 严格连续性：笔序列在几何上首尾相接，bis[i].end == bis[i+1].start；
    4. 延伸性：当最后一笔形成后，若后续同向分型创出更极端价格，直接延伸当前笔；
    5. 无倒挂公理：笔的起始点必须是笔内最高/最低点。

    Args:
        fxs: 分型列表（顶底交替）
        config: 缠论配置
        cklines: 包含处理后的缠论 K 线列表（CLKline 序列）

    Returns:
        笔列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(fxs) < 2:
        return []

    sorted_fxs = sorted(fxs, key=lambda f: f.k.index)
    bis: list[BI] = []

    # 1. 寻找第一笔（起点必须是在成笔之前未被反向击穿的有效分型）
    first_end_idx = -1
    for i in range(len(sorted_fxs)):
        s_fx = sorted_fxs[i]
        found_first = False
        for j in range(i + 1, len(sorted_fxs)):
            e_fx = sorted_fxs[j]
            # 仅在寻找序列第一笔时做截断起点防击穿保护：
            # 若起点在到达终点前已经被反向穿透，说明处于反向趋势半山腰，放弃此起点
            if cklines:
                lo_idx = min(s_fx.k.index, e_fx.k.index)
                hi_idx = max(s_fx.k.index, e_fx.k.index)
                if s_fx.fx_type == FXType.DI:
                    if any(ck.low < s_fx.val * 0.999 for ck in cklines[lo_idx : hi_idx + 1]):
                        break
                else:
                    if any(ck.high > s_fx.val * 1.001 for ck in cklines[lo_idx : hi_idx + 1]):
                        break

            if _can_form_bi(s_fx, e_fx, config, cklines):
                direction = Direction.UP if s_fx.fx_type == FXType.DI else Direction.DOWN
                if cklines:
                    high, low = _calc_bi_range(s_fx, e_fx, cklines)
                else:
                    high = max(s_fx.val, e_fx.val)
                    low = min(s_fx.val, e_fx.val)
                bis.append(BI(start=s_fx, end=e_fx, direction=direction, index=0, high=high, low=low))
                first_end_idx = j
                found_first = True
                break
        if found_first:
            break

    if not bis:
        return []

    # 2. 依次寻找后续笔（保持首尾连续与延伸）
    for k in range(first_end_idx + 1, len(sorted_fxs)):
        fx = sorted_fxs[k]
        last_bi = bis[-1]

        if last_bi.direction == Direction.UP:
            # 当前最后一笔是向上笔：
            # A. 遇到同向顶分型且创新高 -> 向上笔延伸
            if fx.fx_type == FXType.DING:
                if fx.val > last_bi.end.val and _can_form_bi(last_bi.start, fx, config, cklines):
                    last_bi.end = fx
                    if cklines:
                        last_bi.high, last_bi.low = _calc_bi_range(last_bi.start, fx, cklines)
                    else:
                        last_bi.high = max(last_bi.start.val, fx.val)
                        last_bi.low = min(last_bi.start.val, fx.val)

            # B. 遇到反向底分型
            elif fx.fx_type == FXType.DI:
                # 满足成向下笔条件（处理后 >= 5 根且无倒挂） -> 确认向下新笔
                if _can_form_bi(last_bi.end, fx, config, cklines):
                    if cklines:
                        high, low = _calc_bi_range(last_bi.end, fx, cklines)
                    else:
                        high = max(last_bi.end.val, fx.val)
                        low = min(last_bi.end.val, fx.val)
                    new_bi = BI(
                        start=last_bi.end,
                        end=fx,
                        direction=Direction.DOWN,
                        index=len(bis),
                        high=high,
                        low=low,
                    )
                    bis.append(new_bi)

        else:
            # 当前最后一笔是向下笔：
            # A. 遇到同向底分型且创新低 -> 向下笔延伸
            if fx.fx_type == FXType.DI:
                if fx.val < last_bi.end.val and _can_form_bi(last_bi.start, fx, config, cklines):
                    last_bi.end = fx
                    if cklines:
                        last_bi.high, last_bi.low = _calc_bi_range(last_bi.start, fx, cklines)
                    else:
                        last_bi.high = max(last_bi.start.val, fx.val)
                        last_bi.low = min(last_bi.start.val, fx.val)

            # B. 遇到反向顶分型
            elif fx.fx_type == FXType.DING:
                # 满足成向上笔条件（处理后 >= 5 根） -> 确认向上新笔
                if _can_form_bi(last_bi.end, fx, config, cklines):
                    if cklines:
                        high, low = _calc_bi_range(last_bi.end, fx, cklines)
                    else:
                        high = max(last_bi.end.val, fx.val)
                        low = min(last_bi.end.val, fx.val)
                    new_bi = BI(
                        start=last_bi.end,
                        end=fx,
                        direction=Direction.UP,
                        index=len(bis),
                        high=high,
                        low=low,
                    )
                    bis.append(new_bi)

    # 3. 终极一致性校验：过滤任何异常笔，并确保标准缠论 5 根 K 线下限和首尾无缝相接
    min_bars = 7 if (config and config.bi_type == "old") else 5
    filtered_bis: list[BI] = []
    for bi in bis:
        # 必须时间向前，且处理后 K 线数严格达标
        if bi.start.k.index < bi.end.k.index and (abs(bi.end.k.index - bi.start.k.index) + 1 >= min_bars):
            if not filtered_bis:
                filtered_bis.append(bi)
            else:
                # 确保首尾相接
                if filtered_bis[-1].end == bi.start and filtered_bis[-1].direction != bi.direction:
                    filtered_bis.append(bi)

    # 重新编排 index
    for idx, bi in enumerate(filtered_bis):
        bi.index = idx

    return filtered_bis
