"""K 线包含处理（合并）。

缠论 K 线合并规则：
1. 包含关系判定：K1.high >= K2.high AND K1.low <= K2.low，或者 K2.high >= K1.high AND K2.low <= K1.low
2. 如果方向向上，当前 K 线被包含时，取「高高」合并：
   - high = max(K1.high, K2.high)
   - low = max(K1.low, K2.low)
3. 如果方向向下，当前 K 线被包含时，取「低低」合并：
   - high = min(K1.high, K2.high)
   - low = min(K1.low, K2.low)
4. 方向判定规则：
   - 比较前两根处理后 K 线：若 K1.high > K0.high 则向上；若 K1.high < K0.high 则向下；
   - 若高点相等，则以低点决定（K1.low >= K0.low 为向上，否则向下）；
   - 连续合并中保持此前确定的走势方向；
   - 仅有第一根时，由首根 K 线的阳阴决定（close >= open 为向上，否则向下）。
5. 开盘价与收盘价规范：
   - 合并 K 线的 open 保持首根 K 线的 open；
   - 合并 K 线的 close 更新为末根 K 线的 close；
   - amount/volume 累加。
"""

from __future__ import annotations

from easy_tdx.chanlun.types import CLKline, Kline


def _is_included(a: CLKline, b: CLKline) -> bool:
    """判断 a 与 b 是否存在包含关系（a 包含 b 或 b 包含 a）。"""
    return (a.high >= b.high and a.low <= b.low) or (b.high >= a.high and b.low <= a.low)


def _to_clkline(k: Kline, index: int) -> CLKline:
    """将原始 Kline 转为 CLKline。"""
    return CLKline(
        k_index=k.index,
        date=k.date,
        open=k.open,
        close=k.close,
        high=k.high,
        low=k.low,
        amount=k.amount,
        index=index,
        merged_count=1,
        direction="",
        klines=[k],
    )


def merge_klines(klines: list[Kline]) -> list[CLKline]:
    """对原始 K 线列表进行严格缠论包含处理，返回缠论 K 线列表。

    Args:
        klines: 原始 K 线列表

    Returns:
        包含处理后的 CLKline 列表，无包含关系
    """
    if not klines:
        return []

    result: list[CLKline] = [_to_clkline(klines[0], index=0)]

    for i in range(1, len(klines)):
        k = klines[i]
        prev = result[-1]
        candidate = CLKline(
            k_index=k.index,
            date=k.date,
            open=k.open,
            close=k.close,
            high=k.high,
            low=k.low,
            amount=k.amount,
            klines=[k],
        )

        # 判断包含关系（双向覆盖）
        if _is_included(prev, candidate):
            # 确定合并方向：若已有连续合并方向则继承，否则由与前一根无包含关系 K 线的趋势决定
            direction = prev.direction
            if not direction:
                if len(result) >= 2:
                    p_prev = result[-2]
                    if prev.high > p_prev.high:
                        direction = "up"
                    elif prev.high < p_prev.high:
                        direction = "down"
                    else:
                        direction = "up" if prev.low >= p_prev.low else "down"
                else:
                    direction = "up" if prev.close >= prev.open else "down"

            if direction == "up":
                # 向上合并：取高高
                merged_high = max(prev.high, candidate.high)
                merged_low = max(prev.low, candidate.low)
            else:
                # 向下合并：取低低
                merged_high = min(prev.high, candidate.high)
                merged_low = min(prev.low, candidate.low)

            prev.high = merged_high
            prev.low = merged_low
            prev.k_index = k.index
            prev.date = k.date
            prev.merged_count += 1
            prev.direction = direction
            prev.klines.append(k)
            # 保持开盘价为合并前第一根 K 线的 open，收盘价更新为最后一根的 close
            prev.close = k.close
            prev.amount += k.amount
        else:
            # 无包含关系，追加新缠论 K 线
            ck = _to_clkline(k, index=len(result))
            result.append(ck)

    return result
