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
    """从分型列表中计算笔。

    算法（贪心，带 pending 保护，修复版）：
    1. 遍历分型列表，维护最后一个有效分型（start_fx）
    2. 如果当前分型与 start_fx 可以成笔，形成新笔
    3. 如果当前分型与 start_fx 同类型：
       - 无论是否有 pending_opposite，始终用更极端的值更新 start_fx
         （因为分型层已保证顶底交替，重叠同向分型不应出现，但即使出现也要选更极端）
       - 当有 pending_opposite 时更新 start_fx 后，重置 pending_opposite
         （新的 start_fx 更极端，重新评估之前跳过的异类型）
    4. 如果当前分型与 start_fx 异类型但 gap 不够，记录为 pending_opposite

    注意：分型层（find_fractals）已确保顶底交替，
    因此步骤 3 在正常情况下不会触发，仅作容错处理。

    Args:
        fxs: 分型列表（顶底交替）
        config: 缠论配置
        cklines: 缠论K线列表（可选，用于计算笔内真实高低）

    Returns:
        笔列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(fxs) < 2:
        return []

    bis: list[BI] = []

    # 用一个指针追踪当前笔的起始分型
    start_fx = fxs[0]
    # 记录最近一个因 gap 不足而跳过的异类型分型
    pending_opposite: FX | None = None

    for i in range(1, len(fxs)):
        current_fx = fxs[i]

        # 同类型分型：取更极端的（容错处理，正常情况下已由分型层过滤）
        if current_fx.fx_type == start_fx.fx_type:
            if start_fx.fx_type == FXType.DING and current_fx.val > start_fx.val:
                start_fx = current_fx
                pending_opposite = None  # 重置 pending，重新评估
            elif start_fx.fx_type == FXType.DI and current_fx.val < start_fx.val:
                start_fx = current_fx
                pending_opposite = None  # 重置 pending，重新评估
            continue

        # 异类型分型，检查是否可以成笔
        if _can_form_bi(start_fx, current_fx, config):
            direction = Direction.UP if start_fx.fx_type == FXType.DI else Direction.DOWN

            # 计算笔内真实高低
            if cklines:
                high, low = _calc_bi_range(start_fx, current_fx, cklines)
            else:
                high = max(start_fx.val, current_fx.val)
                low = min(start_fx.val, current_fx.val)

            bi = BI(
                start=start_fx,
                end=current_fx,
                direction=direction,
                index=len(bis),
                high=high,
                low=low,
            )
            bis.append(bi)
            start_fx = current_fx
            pending_opposite = None
        else:
            # gap 不够，记录为 pending
            # 若已有 pending 且当前更极端，更新 pending
            if pending_opposite is None:
                pending_opposite = current_fx
            else:
                if current_fx.fx_type == FXType.DING and current_fx.val > pending_opposite.val:
                    pending_opposite = current_fx
                elif current_fx.fx_type == FXType.DI and current_fx.val < pending_opposite.val:
                    pending_opposite = current_fx

    return bis
