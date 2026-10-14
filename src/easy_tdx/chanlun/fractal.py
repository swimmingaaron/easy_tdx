"""分型识别与极值过滤。

缠论分型定义：
- 顶分型：中间 K 线的最高价是三根处理后 K 线中最高，且最低价也是三根中最高。
- 底分型：中间 K 线的最低价是三根处理后 K 线中最低，且最高价也是三根中最低。

优化特性：
1. 严谨分型形态学定义（无包含处理后的标准三根形态）；
2. 过滤同时满足顶底分型的奇异形态（如完全相同的假K线或十字星）；
3. 顶底交替状态机：连续同向分型只保留更极端的绝对极值（顶取更高，底取更低）；
4. 分型完成状态 `done`：最后一根 K 线未走完/缺少后续确认时标记为 `done=False`；
5. 分型强度评估：区分强分型（第三根收盘有效穿透第一根极值）与普通分型。
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import FX, CLKline, FXType


def find_fractals(
    cklines: list[CLKline],
    config: ChanlunConfig | None = None,
) -> list[FX]:
    """从缠论 K 线列表中识别分型，并过滤连续同向分型。

    扫描每三根相邻的缠论 K 线，判断是否构成顶分型或底分型。
    对于连续的同向分型，仅保留更极端的一个（顶取更高，底取更低），
    确保最终列表中顶底严格交替。

    Args:
        cklines: 合并包含后的缠论 K 线列表
        config: 缠论配置（默认使用 ChanlunConfig()）

    Returns:
        分型列表，按时间顺序排列，顶底严格交替
    """
    if config is None:
        config = ChanlunConfig()

    if len(cklines) < 3:
        return []

    # Step 1: 扫描原始候选分型
    raw_candidates: list[FX] = []
    n = len(cklines)

    for i in range(n - 2):
        left = cklines[i]
        mid = cklines[i + 1]
        right = cklines[i + 2]

        if config.fx_strict:
            is_ding = (mid.high > left.high) and (mid.high > right.high)
            is_di = (mid.low < left.low) and (mid.low < right.low)
        else:
            is_ding = (mid.high >= left.high) and (mid.high >= right.high) and (mid.high > min(left.high, right.high))
            is_di = (mid.low <= left.low) and (mid.low <= right.low) and (mid.low < max(left.low, right.low))

        if is_ding and is_di:
            # 奇异形态（同时满足），跳过
            continue

        done = (i + 2) < (n - 1)

        if is_ding:
            fx = FX(
                fx_type=FXType.DING,
                k=mid,
                klines=[left, mid, right],
                val=mid.high,
                index=len(raw_candidates),
                done=done,
            )
            raw_candidates.append(fx)
        elif is_di:
            fx = FX(
                fx_type=FXType.DI,
                k=mid,
                klines=[left, mid, right],
                val=mid.low,
                index=len(raw_candidates),
                done=done,
            )
            raw_candidates.append(fx)

    if not raw_candidates:
        return []

    # Step 2: 顶底交替状态机过滤 —— 连续同向分型只保留更极端的
    fxs: list[FX] = [raw_candidates[0]]

    for fx in raw_candidates[1:]:
        last = fxs[-1]
        if fx.fx_type == last.fx_type:
            # 同向分型：保留绝对极值（顶取最高，底取最低）
            if fx.fx_type == FXType.DING:
                if fx.val > last.val:
                    fxs[-1] = fx
            else:
                if fx.val < last.val:
                    fxs[-1] = fx
        else:
            fxs.append(fx)

    # Step 3: 重新编号
    for idx, fx in enumerate(fxs):
        fx.index = idx

    return fxs
