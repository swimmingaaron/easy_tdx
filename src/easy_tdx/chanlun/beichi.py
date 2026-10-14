"""背驰判断算法（笔背驰、盘整背驰、趋势背驰）。

缠论背驰核心定义（第24课、第29课）：
1. 背驰的本质：价格创出新高（顶背驰）或新低（底背驰），但驱动该走势的内在动量（MACD面积、黄白线、成交量力度）明显衰竭。
   - 向上笔背驰（顶背驰）：必须创新高 (curr.high > prev.high)，但力度明显小于前一笔 (curr_force < prev_force)；
   - 向下笔背驰（底背驰）：必须创新低 (curr.low < prev.low)，但力度明显小于前一笔 (curr_force < prev_force)；
   - 若未创新高或新低，属于盘整震荡或衰竭未背，绝不可误判为背驰。
2. 盘整背驰（PZ）：
   - 在中枢结构中，离开中枢的笔创出新高/新低，但力度小于进入中枢的同向笔。
3. 趋势背驰（QS）：
   - 在至少包含两个同向且不重叠的中枢趋势走势中 (a + A + b + B + c)；
   - 离开第二个中枢的创出趋势极值的 c 段，力度显著小于离开第一个中枢的 b 段或 a 段。
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.macd import calc_macd_force
from easy_tdx.chanlun.types import BC, BI, XD, ZS, BCType, Direction


def check_bi_beichi(
    bis: list[BI],
    zss: list[ZS],
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
) -> list[BC]:
    """检查笔级别的背驰。

    Args:
        bis: 笔列表
        zss: 中枢列表
        config: 缠论配置
        closes: 完整收盘价序列（用于 MACD 面积计算，可选）
        macd_hist: 预计算的 MACD hist 序列（可选）

    Returns:
        背驰列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(bis) < 2:
        return []

    force_cache: dict[int, float] = {}
    bcs: list[BC] = []

    # 1. 笔背驰检查（必须满足创新高/新低 + 力度衰竭）
    bcs.extend(_check_bi_level_beichi(bis, closes, config, macd_hist, force_cache))

    # 2. 盘整背驰检查
    if len(zss) > 0:
        bcs.extend(_check_pz_beichi(bis, zss, closes, config, macd_hist, force_cache))

    # 3. 趋势背驰检查
    if len(zss) >= 2:
        bcs.extend(_check_qs_beichi(bis, zss, closes, config, macd_hist, force_cache))

    return bcs


def _calc_bi_force(
    bi: BI | XD,
    closes: list[float] | None = None,
    config: ChanlunConfig | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> float:
    """计算笔的力度。

    优先使用 MACD hist 面积（绝对值之和），辅以价格振幅加权；无收盘价序列时回退到纯价格幅度。
    """
    bi_idx = getattr(bi, "index", None)
    if force_cache is not None and bi_idx is not None and bi_idx in force_cache:
        return force_cache[bi_idx]

    price_span = max(0.001, abs(bi.high - bi.low))
    force_val: float

    if closes:
        start_idx = bi.start.k.k_index
        end_idx = bi.end.k.k_index
        if 0 <= start_idx < end_idx < len(closes):
            fast = config.macd_fast if config else 12
            slow = config.macd_slow if config else 26
            signal = config.macd_signal if config else 9
            result = calc_macd_force(
                closes, start_idx, end_idx, fast, slow, signal, macd_hist=macd_hist
            )
            macd_force = result.get("hist_sum", 0.0)
            if macd_force > 0:
                # 缠论经典力度：MACD 柱面积为主，价格幅度为辅
                force_val = macd_force
            else:
                force_val = price_span
        else:
            force_val = price_span
    else:
        force_val = price_span

    if force_cache is not None and bi_idx is not None:
        force_cache[bi_idx] = force_val
    return force_val


def _check_bi_level_beichi(
    bis: list[BI],
    closes: list[float] | None,
    config: ChanlunConfig,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> list[BC]:
    """检查笔级别的力度背驰（严密遵循创新高/新低判定）。"""
    bcs: list[BC] = []

    for i in range(1, len(bis)):
        curr = bis[i]
        # 向前找最近的同向笔
        for j in range(i - 1, -1, -1):
            prev = bis[j]
            if prev.direction == curr.direction:
                # 必须创新高（向上笔）或创新低（向下笔）
                is_price_extreme = False
                if curr.direction == Direction.UP:
                    if curr.high > prev.high:
                        is_price_extreme = True
                else:
                    if curr.low < prev.low:
                        is_price_extreme = True

                if is_price_extreme:
                    curr_force = _calc_bi_force(curr, closes, config, macd_hist, force_cache)
                    prev_force = _calc_bi_force(prev, closes, config, macd_hist, force_cache)

                    # 力度衰减 = 背驰
                    if curr_force < prev_force and curr_force > 0:
                        dir_name = "顶背驰" if curr.direction == Direction.UP else "底背驰"
                        bcs.append(
                            BC(
                                bc_type=BCType.BI,
                                bc=True,
                                zs=None,
                                curr=curr,
                                prev=prev,
                                msg=(
                                    f"笔{dir_name}: 笔[{curr.index}] 力度={curr_force:.2f} "
                                    f"< 笔[{prev.index}] 力度={prev_force:.2f} 且价格创新极值"
                                ),
                            )
                        )
                break  # 只与最近一个同向有效笔比较

    return bcs


def _check_pz_beichi(
    bis: list[BI],
    zss: list[ZS],
    closes: list[float] | None,
    config: ChanlunConfig,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> list[BC]:
    """检查盘整背驰。

    在中枢结构中，离开中枢的笔力度小于进入中枢的第一笔，且突破中枢极值。
    """
    bcs: list[BC] = []

    for zs in zss:
        if zs.line_count < 3 or not zs.lines:
            continue

        first_bi = zs.lines[0]
        last_bi = zs.lines[-1]

        # 首末笔同向比较（奇数笔中枢首末同向）
        if first_bi.direction != last_bi.direction:
            continue

        # 检查是否突破中枢极值
        is_break = False
        if last_bi.direction == Direction.UP:
            if last_bi.high > zs.zg or last_bi.high > first_bi.high:
                is_break = True
        else:
            if last_bi.low < zs.zd or last_bi.low < first_bi.low:
                is_break = True

        if is_break:
            first_force = _calc_bi_force(first_bi, closes, config, macd_hist, force_cache)
            last_force = _calc_bi_force(last_bi, closes, config, macd_hist, force_cache)

            if last_force < first_force and last_force > 0:
                dir_label = "顶盘整背驰" if last_bi.direction == Direction.UP else "底盘整背驰"
                bcs.append(
                    BC(
                        bc_type=BCType.PZ,
                        bc=True,
                        zs=zs,
                        curr=last_bi,
                        prev=first_bi,
                        msg=(
                            f"{dir_label}: 中枢[{zs.index}] 末笔力度={last_force:.2f} "
                            f"< 首笔力度={first_force:.2f}"
                        ),
                    )
                )

    return bcs


def _check_qs_beichi(
    bis: list[BI],
    zss: list[ZS],
    closes: list[float] | None,
    config: ChanlunConfig,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> list[BC]:
    """检查趋势背驰。

    两个同向且不重叠的中枢之间，离开第二个中枢的笔力度小于离开前一中枢的笔。
    """
    bcs: list[BC] = []

    for i in range(1, len(zss)):
        prev_zs = zss[i - 1]
        curr_zs = zss[i]

        if not prev_zs.lines or not curr_zs.lines:
            continue

        # 严格判断两个中枢是否绝对无重叠并形成趋势
        # 1. 向下趋势：前中枢下沿高于后中枢上沿 (prev_zs.zd > curr_zs.zg)
        if prev_zs.zd > curr_zs.zg:
            prev_exit = prev_zs.lines[-1]
            curr_exit = curr_zs.lines[-1]
            if prev_exit.direction == Direction.DOWN and curr_exit.direction == Direction.DOWN:
                if curr_exit.low < prev_exit.low:
                    prev_force = _calc_bi_force(prev_exit, closes, config, macd_hist, force_cache)
                    curr_force = _calc_bi_force(curr_exit, closes, config, macd_hist, force_cache)

                    if curr_force < prev_force and curr_force > 0:
                        bcs.append(
                            BC(
                                bc_type=BCType.QS,
                                bc=True,
                                zs=curr_zs,
                                curr=curr_exit,
                                prev=prev_exit,
                                msg=(
                                    f"趋势底背驰: 中枢[{curr_zs.index}] 离开力度={curr_force:.2f} "
                                    f"< 中枢[{prev_zs.index}] 离开力度={prev_force:.2f} 创新低"
                                ),
                            )
                        )

        # 2. 向上趋势：后中枢下沿高于前中枢上沿 (curr_zs.zd > prev_zs.zg)
        elif curr_zs.zd > prev_zs.zg:
            prev_exit = prev_zs.lines[-1]
            curr_exit = curr_zs.lines[-1]
            if prev_exit.direction == Direction.UP and curr_exit.direction == Direction.UP:
                if curr_exit.high > prev_exit.high:
                    prev_force = _calc_bi_force(prev_exit, closes, config, macd_hist, force_cache)
                    curr_force = _calc_bi_force(curr_exit, closes, config, macd_hist, force_cache)

                    if curr_force < prev_force and curr_force > 0:
                        bcs.append(
                            BC(
                                bc_type=BCType.QS,
                                bc=True,
                                zs=curr_zs,
                                curr=curr_exit,
                                prev=prev_exit,
                                msg=(
                                    f"趋势顶背驰: 中枢[{curr_zs.index}] 离开力度={curr_force:.2f} "
                                    f"< 中枢[{prev_zs.index}] 离开力度={prev_force:.2f} 创新高"
                                ),
                            )
                        )

    return bcs
