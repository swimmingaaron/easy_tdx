"""分型识别。

顶分型：中间 K 线的高点和低点均为三根中最高。
底分型：中间 K 线的高点和低点均为三根中最低。

严格模式下不允许相等（使用 > 而非 >=）。

优化（v2）：
1. 加入顶底交替状态机过滤 —— 连续同向分型只保留更极端的一个
2. 正确标记末尾未完成分型（最后一个分型缺少后续 K 线确认时 done=False）
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
        cklines: 合并后的缠论 K 线列表
        config: 缠论配置（默认使用 ChanlunConfig()）

    Returns:
        分型列表，按时间顺序排列，顶底严格交替
    """
    if config is None:
        config = ChanlunConfig()

    if len(cklines) < 3:
        return []

    # Step 1: 扫描原始候选分型（不限制交替）
    raw_candidates: list[FX] = []

    n = len(cklines)
    for i in range(n - 2):
        left = cklines[i]
        mid = cklines[i + 1]
        right = cklines[i + 2]

        if config.fx_strict:
            is_ding = mid.high > left.high and mid.high > right.high
            is_di = mid.low < left.low and mid.low < right.low
        else:
            is_ding = mid.high >= left.high and mid.high >= right.high
            is_di = mid.low <= left.low and mid.low <= right.low

        if is_ding and is_di:
            # 同时满足（如十字星），跳过
            continue
        elif is_ding:
            # 末尾分型：right 是最后一根，right 后面没有更多 K 线，分型未经后续确认
            done = (i + 2) < (n - 1)
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
            done = (i + 2) < (n - 1)
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
            # 同向分型：保留更极端的
            if fx.fx_type == FXType.DING:
                if fx.val > last.val:
                    fxs[-1] = fx  # 顶取更高
            else:
                if fx.val < last.val:
                    fxs[-1] = fx  # 底取更低
        else:
            fxs.append(fx)

    # Step 3: 重新编号
    for idx, fx in enumerate(fxs):
        fx.index = idx

    return fxs
