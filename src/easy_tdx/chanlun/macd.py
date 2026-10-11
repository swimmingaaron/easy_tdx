"""MACD 指标计算（纯 numpy 实现）。

MACD 由三部分组成：
- DIF（快线）: EMA(fast) - EMA(slow)
- DEA（慢线）: EMA(DIF, signal)
- HIST（柱状图）: 2 * (DIF - DEA)
"""

from __future__ import annotations


def calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, list[float]]:
    """计算 MACD 指标。

    Args:
        closes: 收盘价序列
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期

    Returns:
        {"dif": [...], "dea": [...], "hist": [...]}
    """
    n = len(closes)
    if n == 0:
        return {"dif": [], "dea": [], "hist": []}

    # EMA 计算
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)

    # DIF = EMA(fast) - EMA(slow)
    dif = [ema_fast[i] - ema_slow[i] for i in range(n)]

    # DEA = EMA(DIF, signal)
    dea = _calc_ema(dif, signal)

    # HIST = 2 * (DIF - DEA)
    hist = [2.0 * (dif[i] - dea[i]) for i in range(n)]

    return {"dif": dif, "dea": dea, "hist": hist}


def _calc_ema(data: list[float], period: int) -> list[float]:
    """计算指数移动平均线。

    EMA(t) = price(t) * k + EMA(t-1) * (1 - k)
    k = 2 / (period + 1)
    """
    n = len(data)
    if n == 0:
        return []

    k = 2.0 / (period + 1)
    result = [0.0] * n

    # 初始值：第一个数据点
    result[0] = data[0]

    for i in range(1, n):
        result[i] = data[i] * k + result[i - 1] * (1 - k)

    return result


# 全局单对象 MACD 缓存（避免反复计算同一组 closes 的 EMA）
_LAST_MACD_CACHE: tuple[int, int, int, int, list[float]] | None = None


def calc_macd_force(
    closes: list[float],
    start_idx: int,
    end_idx: int,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    macd_hist: list[float] | None = None,
) -> dict[str, float]:
    """计算区间内的 MACD 力度（用于背驰判断）。

    Args:
        closes: 完整收盘价序列
        start_idx: 起始索引
        end_idx: 结束索引（含）
        fast, slow, signal: MACD 参数
        macd_hist: 可选已预先计算好的 MACD hist 序列，若提供则无需重新计算 MACD

    Returns:
        {"hist_sum": 总柱子面积, "hist_up_sum": 红柱总和, "hist_down_sum": 绿柱总和}
    """
    if start_idx > end_idx or end_idx >= len(closes):
        return {"hist_sum": 0.0, "hist_up_sum": 0.0, "hist_down_sum": 0.0}

    global _LAST_MACD_CACHE
    if macd_hist is not None:
        hist_series = macd_hist
    else:
        # 检查是否匹配最近一次缓存 (id, len, fast, slow, signal)
        c_id = id(closes)
        c_len = len(closes)
        if (
            _LAST_MACD_CACHE is not None
            and _LAST_MACD_CACHE[0] == c_id
            and _LAST_MACD_CACHE[1] == c_len
            and _LAST_MACD_CACHE[2] == fast
            and _LAST_MACD_CACHE[3] == slow
        ):
            hist_series = _LAST_MACD_CACHE[4]
        else:
            macd = calc_macd(closes, fast, slow, signal)
            hist_series = macd["hist"]
            _LAST_MACD_CACHE = (c_id, c_len, fast, slow, hist_series)

    hist_slice = hist_series[start_idx : end_idx + 1]

    hist_abs = [abs(h) for h in hist_slice]
    hist_up = [h for h in hist_slice if h > 0]
    hist_down = [h for h in hist_slice if h < 0]

    return {
        "hist_sum": sum(hist_abs),
        "hist_up_sum": sum(hist_up),
        "hist_down_sum": abs(sum(hist_down)),
    }

