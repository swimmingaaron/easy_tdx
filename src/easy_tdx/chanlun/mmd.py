"""买卖点识别算法（第一类、第二类、第三类买卖点）。

缠论买卖点核心定义（第14课、第16课、第20课、第53课）：
1. 第一类买卖点（1BUY / 1SELL）：
   - 1BUY：下跌趋势中最后一个中枢下方的底背驰点（走势转折的绝对最低点）；
   - 1SELL：上涨趋势中最后一个中枢上方的顶背驰点（走势转折的绝对最高点）；
2. 第二类买卖点（2BUY / 2SELL）：
   - 2BUY：第一类买点之后，次级别向上反弹后的首次次回踩不破一买最低点（回调不创新低）；
   - 2SELL：第一类卖点之后，次级别向下回调后的首次次反弹不破一卖最高点（反弹不创新高）；
3. 第三类买卖点（3BUY / 3SELL）：
   - 3BUY：中枢向上突破离开段后，随后的次级别回调（向下笔）其最低点不跌破中枢上沿 (bi.low >= zs.zg)；
   - 3SELL：中枢向下跌破离开段后，随后的次级别反弹（向上笔）其最高点不突破中枢下沿 (bi.high <= zs.zd)；
4. 判定优先级与防误判：
   - 3类买卖点具有最高明确度与确定性，严格优先于2类买卖点判定；
   - 杜绝在中枢延伸震荡内部将任意无规律的普通震荡笔误判为2类买卖点。
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, MMD, ZS, Direction, MMDType


def find_mmds(
    bis: list[BI],
    zss: list[ZS],
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
) -> list[MMD]:
    """从笔和中枢中识别标准缠论买卖点。

    Args:
        bis: 笔列表
        zss: 中枢列表
        config: 缠论配置
        closes: 收盘价序列（可选，用于计算 MACD 面积力度）
        macd_hist: 预计算的 MACD hist 序列（可选）

    Returns:
        买卖点列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(bis) < 2 or len(zss) == 0:
        return []

    mmds: list[MMD] = []
    force_cache: dict[int, float] = {}

    for bi in bis:
        # 寻找与该笔生命周期和结构相匹配的中枢
        # 缠论公理：买卖点必须基于已形成的中枢，杜绝由未来尚未开始的中枢产生穿越误判
        best_mmd: MMD | None = None
        for zs in reversed(zss):
            if zs.lines:
                zs_start_bi_idx = zs.lines[0].index
                zs_end_bi_idx = zs.lines[-1].index
                # 笔不能早于中枢产生之前 (杜绝未来中枢穿越)
                if bi.index < zs_start_bi_idx:
                    continue
                # 笔距离中枢结束不能跨越过远（超过6笔已属后续走势）
                if bi.index - zs_end_bi_idx > 6:
                    continue
                # 三类买点初筛：必须发生在中枢突破离开后的第1次回抽 (距中枢结束<=2笔)
                if bi.direction == Direction.DOWN and bi.low >= zs.zg:
                    if bi.index < zs_end_bi_idx or (bi.index - zs_end_bi_idx) > 2:
                        continue
                # 三类卖点初筛：必须发生在中枢跌破离开后的第1次反抽 (距中枢结束<=2笔)
                if bi.direction == Direction.UP and bi.high <= zs.zd:
                    if bi.index < zs_end_bi_idx or (bi.index - zs_end_bi_idx) > 2:
                        continue

            mmd = _check_bi_mmd(
                bi, zs, bis, all_zss=zss, config=config, closes=closes, macd_hist=macd_hist, force_cache=force_cache
            )
            if mmd is not None:
                # 若命中高确定性的三类买卖点（突破回抽确认），具有最高优先权，直接锁定
                if mmd.mmd_type in (MMDType.BUY_3, MMDType.SELL_3):
                    best_mmd = mmd
                    break
                elif best_mmd is None:
                    best_mmd = mmd
                    # 若已命中最近中枢的其他买卖点，且后续不再有3买3卖，则保留并终止
                    break

        if best_mmd is not None:
            mmds.append(best_mmd)

    return mmds


def _check_bi_mmd(
    bi: BI,
    zs: ZS,
    all_bis: list[BI],
    all_zss: list[ZS] | None = None,
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> MMD | None:
    """检查单笔是否在某中枢附近形成买卖点。"""
    if bi.direction == Direction.DOWN:
        return _check_buy_point(
            bi, zs, all_bis, all_zss=all_zss, config=config, closes=closes, macd_hist=macd_hist, force_cache=force_cache
        )
    else:
        return _check_sell_point(
            bi, zs, all_bis, all_zss=all_zss, config=config, closes=closes, macd_hist=macd_hist, force_cache=force_cache
        )


def _check_buy_point(
    bi: BI,
    zs: ZS,
    all_bis: list[BI],
    all_zss: list[ZS] | None = None,
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> MMD | None:
    """检查向下笔是否形成买点。"""
    # ── 1. 三类买点（《教你炒股票20课》走势中枢级别扩张与第三类买卖点定理）：
    # 核心定义：一个次级别走势类型向上离开中枢，然后以一个次级别走势类型回试，其低点不跌破 ZG，则构成第三类买点。
    # 缠中说禅公理与硬性约束：
    # 1) 价格条件：回踩低点不跌破中枢上沿 (bi.low >= zs.zg)；
    # 2) 必须是第一次回试！并不是任何回调回抽都是第三类买卖点，必须是突破离开后的第1次次回调；
    # 3) 中枢接力阻断：离开原中枢后，不能已经形成新的同级别中枢（若已形成新中枢，原中枢历史使命结束）；
    # 4) 非中枢内部笔：当前笔自身绝不能属于任何中枢的构成笔（中枢内部震荡绝非三买）。
    if bi.low >= zs.zg:
        zs_end_idx = zs.lines[-1].index if zs.lines else zs.index
        is_first_pullback = False
        if bi.index == zs_end_idx + 1:
            # 情况 A：中枢最后一笔本身即向上离开中枢
            prev_bi = all_bis[zs_end_idx] if 0 <= zs_end_idx < len(all_bis) else None
            if prev_bi and prev_bi.direction == Direction.UP and prev_bi.high > zs.zg:
                is_first_pullback = True
        elif bi.index == zs_end_idx + 2 and 0 <= zs_end_idx + 1 < len(all_bis):
            # 情况 B：中枢完成后紧接着的一笔向上离开中枢，当前笔是离开后的首次回踩
            out_bi = all_bis[zs_end_idx + 1]
            if out_bi.direction == Direction.UP and out_bi.high > zs.zg:
                is_first_pullback = True

        if is_first_pullback:
            is_valid_3buy = True
            if all_zss:
                for other_zs in all_zss:
                    if other_zs.lines:
                        # 4) 当前笔自身不能是任何中枢的内部构成笔
                        if any(b.index == bi.index for b in other_zs.lines):
                            is_valid_3buy = False
                            break
                        # 3) 离开原中枢后，不能已经形成新的同级别中枢 (新中枢起始于原中枢之后且已在当前笔前形成)
                        other_start_idx = other_zs.lines[0].index
                        if other_start_idx > zs_end_idx and other_start_idx <= bi.index:
                            is_valid_3buy = False
                            break
            if is_valid_3buy:
                return MMD(
                    mmd_type=MMDType.BUY_3,
                    zs=zs,
                    bi=bi,
                    msg=f"中枢上沿强力支撑，三类买点 (low={bi.low:.2f} >= zg={zs.zg:.2f})",
                )

    # ── 2. 一类买点：处于中枢下方 (bi.low < zs.zd)，底背驰衰竭点
    # 缠论公理：一买必须跌破前一个同向向下笔的低点（创新低）！
    # 若未创新低（回踩高于或平于前低），绝不构成底背驰一买，必须留给二类买点判定！
    bi_idx = bi.index
    prev_down_bi = all_bis[bi_idx - 2] if bi_idx >= 2 and bi_idx - 2 < len(all_bis) and all_bis[bi_idx - 2].direction == Direction.DOWN else None
    is_lower_than_prev = (prev_down_bi is None or bi.low < prev_down_bi.low * 0.998)

    if bi.low < zs.zd and is_lower_than_prev:
        if _check_force_decreasing(
            bi, all_bis, Direction.DOWN, closes=closes, config=config, macd_hist=macd_hist, force_cache=force_cache
        ):
            return MMD(
                mmd_type=MMDType.BUY_1,
                zs=zs,
                bi=bi,
                msg=f"中枢下方动力背驰，一类买点 (low={bi.low:.2f} < zd={zs.zd:.2f})",
            )

    # ── 3. 二类买点：一买之后或中枢下方探底后，回踩不创新低（兼容平底/双底）
    # 要求：1) 高于或平于前一个向下笔低点；2) 发生在中枢下沿或中枢建立/突破初期的第一折回踩
    if bi_idx >= 2:
        if prev_down_bi and prev_down_bi.direction == Direction.DOWN:
            prev_up_bi = all_bis[bi_idx - 1] if bi_idx >= 1 else None
            # 缠论公理：二买绝不能是自高位顶背驰/创波段最高点之后的第一笔下杀！
            # 若中间向上笔大幅冲顶创出高位新高（prev_up_bi.high >= zs.gg 且创局部最高），
            # 则当前笔只是见顶下杀第一笔，绝非二买
            is_peak_first_drop = False
            if prev_up_bi and prev_up_bi.direction == Direction.UP:
                if prev_up_bi.high >= zs.gg and prev_up_bi.high > prev_down_bi.high:
                    is_peak_first_drop = True

            if not is_peak_first_drop and bi.low >= prev_down_bi.low * 0.998:
                is_valid_2buy = False
                if prev_down_bi.low <= zs.zd or bi.low >= zs.zd:
                    is_valid_2buy = True
                if is_valid_2buy:
                    return MMD(
                        mmd_type=MMDType.BUY_2,
                        zs=zs,
                        bi=bi,
                        msg=f"次级别回踩不创新低，二类买点 (low={bi.low:.2f} >= prev_low={prev_down_bi.low:.2f})",
                    )

    return None


def _check_sell_point(
    bi: BI,
    zs: ZS,
    all_bis: list[BI],
    all_zss: list[ZS] | None = None,
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> MMD | None:
    """检查向上笔是否形成卖点。"""
    # ── 1. 三类卖点（《教你炒股票20课》走势中枢级别扩张与第三类买卖点定理）：
    # 核心定义：一个次级别走势类型向下离开中枢，然后以一个次级别走势类型回抽，其高点不升破 ZD，则构成第三类卖点。
    # 缠中说禅公理与硬性约束：
    # 1) 价格条件：反抽高点不升破中枢下沿 (bi.high <= zs.zd)；
    # 2) 必须是第一次反抽！并不是任何反弹回抽都是第三类买卖点，必须是跌破离开后的第1次次反弹；
    # 3) 中枢接力阻断：跌破原中枢后，不能已经形成新的同级别中枢；
    # 4) 非中枢内部笔：当前笔自身绝不能属于任何中枢的构成笔。
    if bi.high <= zs.zd:
        zs_end_idx = zs.lines[-1].index if zs.lines else zs.index
        is_first_bounce = False
        if bi.index == zs_end_idx + 1:
            # 情况 A：中枢最后一笔本身即向下跌破中枢
            prev_bi = all_bis[zs_end_idx] if 0 <= zs_end_idx < len(all_bis) else None
            if prev_bi and prev_bi.direction == Direction.DOWN and prev_bi.low < zs.zd:
                is_first_bounce = True
        elif bi.index == zs_end_idx + 2 and 0 <= zs_end_idx + 1 < len(all_bis):
            # 情况 B：中枢完成后紧接着的一笔向下跌破离开，当前笔是离开后的首次反抽
            out_bi = all_bis[zs_end_idx + 1]
            if out_bi.direction == Direction.DOWN and out_bi.low < zs.zd:
                is_first_bounce = True

        if is_first_bounce:
            is_valid_3sell = True
            if all_zss:
                for other_zs in all_zss:
                    if other_zs.lines:
                        # 4) 当前笔自身不能是任何中枢的内部构成笔
                        if any(b.index == bi.index for b in other_zs.lines):
                            is_valid_3sell = False
                            break
                        # 3) 跌破原中枢后，不能已经形成新的同级别中枢
                        other_start_idx = other_zs.lines[0].index
                        if other_start_idx > zs_end_idx and other_start_idx <= bi.index:
                            is_valid_3sell = False
                            break
            if is_valid_3sell:
                return MMD(
                    mmd_type=MMDType.SELL_3,
                    zs=zs,
                    bi=bi,
                    msg=f"反弹受阻于中枢下沿，三类卖点 (high={bi.high:.2f} <= zd={zs.zd:.2f})",
                )

    # ── 2. 一类卖点：处于中枢上方 (bi.high > zs.zg)，顶背驰衰竭点
    # 缠论公理：一卖必须突破前一个同向向上笔的高点（创新高）！
    # 若未创新高（反弹受阻于前高），绝不构成顶背驰一卖，必须留给二类卖点判定！
    bi_idx = bi.index
    prev_up_bi = all_bis[bi_idx - 2] if bi_idx >= 2 and bi_idx - 2 < len(all_bis) and all_bis[bi_idx - 2].direction == Direction.UP else None
    is_higher_than_prev = (prev_up_bi is None or bi.high > prev_up_bi.high * 1.002)

    if bi.high > zs.zg and is_higher_than_prev:
        if _check_force_decreasing(
            bi, all_bis, Direction.UP, closes=closes, config=config, macd_hist=macd_hist, force_cache=force_cache
        ):
            return MMD(
                mmd_type=MMDType.SELL_1,
                zs=zs,
                bi=bi,
                msg=f"中枢上方动力背驰，一类卖点 (high={bi.high:.2f} > zg={zs.zg:.2f})",
            )

    # ── 3. 二类卖点：一卖之后或中枢冲顶后，反弹不创新高（兼容双顶/平顶滞涨受阻）
    if bi_idx >= 2:
        if prev_up_bi and prev_up_bi.direction == Direction.UP:
            prev_down_bi = all_bis[bi_idx - 1] if bi_idx >= 1 else None
            # 缠论公理：二卖绝不能是自低位底背驰/创波段大底之后的第一笔反抽！
            # 若中间向下笔探底创出低位新低（prev_down_bi.low <= zs.dd 且创局部最低），
            # 则当前笔是自底见底反转第一笔，绝非二卖
            is_bottom_first_bounce = False
            if prev_down_bi and prev_down_bi.direction == Direction.DOWN:
                if prev_down_bi.low <= zs.dd and prev_down_bi.low < prev_up_bi.low:
                    is_bottom_first_bounce = True

            if not is_bottom_first_bounce and bi.high <= prev_up_bi.high * 1.002:
                is_valid_2sell = False
                if prev_up_bi.high >= zs.zg or bi.high <= zs.zg:
                    is_valid_2sell = True
                if is_valid_2sell:
                    return MMD(
                        mmd_type=MMDType.SELL_2,
                        zs=zs,
                        bi=bi,
                        msg=f"次级别反弹不创新高，二类卖点 (high={bi.high:.2f} <= prev_high={prev_up_bi.high:.2f})",
                    )

    return None


def _check_force_decreasing(
    bi: BI,
    all_bis: list[BI],
    direction: Direction,
    closes: list[float] | None = None,
    config: ChanlunConfig | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> bool:
    """检查同向走势力度是否衰减（结合 MACD hist 柱面积与波峰/波谷背驰对比）。"""
    bi_idx = bi.index
    if bi_idx < 2 or bi_idx >= len(all_bis):
        return False

    from easy_tdx.chanlun.beichi import _calc_bi_force

    curr_force = _calc_bi_force(
        bi, closes, config, macd_hist=macd_hist, force_cache=force_cache
    )

    # 缠论背驰核心定义：离开段不仅可以和紧邻前一笔比，更要回溯比对中枢进入段及同向峰值笔 (a段与c段比较)
    # 严格约束：不能越过比自身更极端的中间笔去和更早的笔比背驰（即在区间[j, bi_idx)内当前笔必须是最极端的低点/高点）
    for j in range(bi_idx - 1, max(-1, bi_idx - 10), -1):
        prev = all_bis[j]
        if prev.direction == direction:
            prev_force = _calc_bi_force(
                prev, closes, config, macd_hist=macd_hist, force_cache=force_cache
            )

            if direction == Direction.DOWN:
                # 价格创新低且力度衰竭 (底背驰)
                min_intermediate_low = min((all_bis[k].low for k in range(j, bi_idx) if all_bis[k].direction == Direction.DOWN), default=bi.low)
                if bi.low <= prev.low and bi.low <= min_intermediate_low and curr_force < prev_force:
                    return True
            else:
                # 价格创新高且力度衰竭 (顶背驰)
                max_intermediate_high = max((all_bis[k].high for k in range(j, bi_idx) if all_bis[k].direction == Direction.UP), default=bi.high)
                if bi.high >= prev.high and bi.high >= max_intermediate_high and curr_force < prev_force:
                    return True

    return False
