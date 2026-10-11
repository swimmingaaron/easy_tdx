"""背驰判断。

背驰类型：
- 笔背驰：相邻同向笔的力度比较（MACD 面积减小 + 幅度减小）
- 盘整背驰：中枢内最后一笔力度小于进入中枢的第一笔
- 趋势背驰：两个同向中枢之间，离开中枢的笔力度减小

优化（v2）：
1. 背驰判断优先使用 MACD hist 面积（更符合缠论原著），并回退到幅度
2. 修正一类买点的背驰条件：价格需创新低，但 MACD 力度（面积）减小
3. 盘整背驰校验首末笔方向一致性（奇数笔中枢首末同向是正确的）
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.macd import calc_macd_force
from easy_tdx.chanlun.types import BC, BI, XD, ZS, BCType


def check_bi_beichi(
    bis: list[BI],
    zss: list[ZS],
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
) -> list[BC]:
    """检查笔级别的背驰。

    算法：
    1. 笔背驰：比较相邻同向笔的 MACD 面积（有 closes 时）或幅度
    2. 盘整背驰：中枢内末笔与首笔比较
    3. 趋势背驰：连续两个同向中枢，离开力度减小

    Args:
        bis: 笔列表
        zss: 中枢列表
        config: 缠论配置
        closes: 完整收盘价序列（用于 MACD 面积计算，可选）

    Returns:
        背驰列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(bis) < 2:
        return []

    bcs: list[BC] = []

    # 1. 笔背驰检查
    bcs.extend(_check_bi_level_beichi(bis, closes, config))

    # 2. 盘整背驰检查
    if len(zss) > 0:
        bcs.extend(_check_pz_beichi(bis, zss, closes, config))

    # 3. 趋势背驰检查
    if len(zss) >= 2:
        bcs.extend(_check_qs_beichi(bis, zss, closes, config))

    return bcs


def _calc_bi_force(
    bi: BI | XD,
    closes: list[float] | None = None,
    config: ChanlunConfig | None = None,
) -> float:
    """计算笔的力度。

    优先使用 MACD hist 面积（绝对值之和），若无收盘价序列则回退到幅度。
    """
    if closes:
        start_idx = bi.start.k.k_index
        end_idx = bi.end.k.k_index
        if 0 <= start_idx < end_idx < len(closes):
            fast = config.macd_fast if config else 12
            slow = config.macd_slow if config else 26
            signal = config.macd_signal if config else 9
            result = calc_macd_force(closes, start_idx, end_idx, fast, slow, signal)
            macd_force = result.get("hist_sum", 0.0)
            if macd_force > 0:
                return macd_force

    # 回退到幅度
    return abs(bi.high - bi.low)


def _check_bi_level_beichi(
    bis: list[BI],
    closes: list[float] | None,
    config: ChanlunConfig,
) -> list[BC]:
    """检查笔级别的力度背驰。"""
    bcs: list[BC] = []

    for i in range(1, len(bis)):
        curr = bis[i]
        # 向前找最近的同向笔
        for j in range(i - 1, -1, -1):
            prev = bis[j]
            if prev.direction == curr.direction:
                curr_force = _calc_bi_force(curr, closes, config)
                prev_force = _calc_bi_force(prev, closes, config)

                # 力度衰减 = 背驰
                if curr_force < prev_force and curr_force > 0:
                    bcs.append(
                        BC(
                            bc_type=BCType.BI,
                            bc=True,
                            zs=None,
                            curr=curr,
                            prev=prev,
                            msg=(
                                f"笔背驰: 笔[{curr.index}] 力度={curr_force:.3f} "
                                f"< 笔[{prev.index}] 力度={prev_force:.3f}"
                            ),
                        )
                    )
                break  # 只比较最近一个同向笔

    return bcs


def _check_pz_beichi(
    bis: list[BI],
    zss: list[ZS],
    closes: list[float] | None,
    config: ChanlunConfig,
) -> list[BC]:
    """检查盘整背驰。

    盘整背驰：中枢内最末一笔的力度小于进入中枢的第一笔，且两笔同向。
    奇数笔中枢（3/5/7...）首末两笔自然同向。
    """
    bcs: list[BC] = []

    for zs in zss:
        if zs.line_count < 3:
            continue

        first_bi = zs.lines[0]
        last_bi = zs.lines[-1]

        # 首末同向（奇数笔中枢天然满足）
        if first_bi.direction != last_bi.direction:
            continue

        first_force = _calc_bi_force(first_bi, closes, config)
        last_force = _calc_bi_force(last_bi, closes, config)

        if last_force < first_force and last_force > 0:
            bcs.append(
                BC(
                    bc_type=BCType.PZ,
                    bc=True,
                    zs=zs,
                    curr=last_bi,
                    prev=first_bi,
                    msg=(
                        f"盘整背驰: 中枢[{zs.index}] 内末笔力度={last_force:.3f} "
                        f"< 首笔力度={first_force:.3f}"
                    ),
                )
            )

    return bcs


def _check_qs_beichi(
    bis: list[BI],
    zss: list[ZS],
    closes: list[float] | None,
    config: ChanlunConfig,
) -> list[BC]:
    """检查趋势背驰。"""
    bcs: list[BC] = []

    for i in range(1, len(zss)):
        prev_zs = zss[i - 1]
        curr_zs = zss[i]

        if not prev_zs.lines or not curr_zs.lines:
            continue

        # 判断两个中枢是否形成趋势（同向排列）
        if prev_zs.zg >= curr_zs.zg and prev_zs.zd >= curr_zs.zd:
            # 向下趋势：离开中枢的笔应为向下笔
            prev_exit = prev_zs.lines[-1]
            curr_exit = curr_zs.lines[-1]
            if prev_exit.direction == curr_exit.direction:
                prev_force = _calc_bi_force(prev_exit, closes, config)
                curr_force = _calc_bi_force(curr_exit, closes, config)

                if curr_force < prev_force and curr_force > 0:
                    bcs.append(
                        BC(
                            bc_type=BCType.QS,
                            bc=True,
                            zs=curr_zs,
                            curr=curr_exit,
                            prev=prev_exit,
                            msg=(
                                f"趋势背驰(下): 中枢[{curr_zs.index}] 离开力度={curr_force:.3f} "
                                f"< 中枢[{prev_zs.index}] 离开力度={prev_force:.3f}"
                            ),
                        )
                    )
        elif prev_zs.zg <= curr_zs.zg and prev_zs.zd <= curr_zs.zd:
            # 向上趋势：离开中枢的笔应为向上笔
            prev_exit = prev_zs.lines[-1]
            curr_exit = curr_zs.lines[-1]
            if prev_exit.direction == curr_exit.direction:
                prev_force = _calc_bi_force(prev_exit, closes, config)
                curr_force = _calc_bi_force(curr_exit, closes, config)

                if curr_force < prev_force and curr_force > 0:
                    bcs.append(
                        BC(
                            bc_type=BCType.QS,
                            bc=True,
                            zs=curr_zs,
                            curr=curr_exit,
                            prev=prev_exit,
                            msg=(
                                f"趋势背驰(上): 中枢[{curr_zs.index}] 离开力度={curr_force:.3f} "
                                f"< 中枢[{prev_zs.index}] 离开力度={prev_force:.3f}"
                            ),
                        )
                    )

    return bcs
