"""买卖点识别。

缠论三类买卖点：
- 一类买点：下跌趋势中最后一个中枢下方的底背驰点
- 二类买点：一类买点后回调不创新低的底分型
- 三类买点：向上突破中枢后回调不跌破中枢上沿的底分型
- 一类卖点：上涨趋势中最后一个中枢上方的顶背驰点（对称）
- 二类卖点：一类卖点后反弹不创新高的顶分型
- 三类卖点：向下跌破中枢后反弹不突破中枢下沿的顶分型

优化（v2）：
1. 修正优先级：三类买卖点先于二类买卖点判断（三买回调不跌破上沿更严格，避免被宽松的二买误拦截）
2. 力度衰减接入 MACD hist 面积（当有 closes 时优先使用，无 closes 时回退到幅度）
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, MMD, ZS, MMDType


def find_mmds(
    bis: list[BI],
    zss: list[ZS],
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
) -> list[MMD]:
    """从笔和中枢中识别买卖点。

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
        # 寻找与该笔最近的中枢
        for zs in reversed(zss):
            mmd = _check_bi_mmd(
                bi, zs, bis, config=config, closes=closes, macd_hist=macd_hist, force_cache=force_cache
            )
            if mmd is not None:
                mmds.append(mmd)
                break  # 每笔最多一个买卖点

    return mmds


def _check_bi_mmd(
    bi: BI,
    zs: ZS,
    all_bis: list[BI],
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> MMD | None:
    """检查单笔是否在某中枢附近形成买卖点。"""
    if bi.direction.value == "down":
        return _check_buy_point(
            bi, zs, all_bis, config=config, closes=closes, macd_hist=macd_hist, force_cache=force_cache
        )
    else:
        return _check_sell_point(
            bi, zs, all_bis, config=config, closes=closes, macd_hist=macd_hist, force_cache=force_cache
        )


def _check_buy_point(
    bi: BI,
    zs: ZS,
    all_bis: list[BI],
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> MMD | None:
    """检查向下笔是否形成买点。"""
    # 三类买点优先：突破中枢后，回调不跌破中枢上沿（必须先于二买判定）
    if bi.low > zs.zg:
        return MMD(
            mmd_type=MMDType.BUY_3,
            zs=zs,
            bi=bi,
            msg=f"回调不破中枢上沿，三类买点 (l={bi.low:.2f} > zg={zs.zg:.2f})",
        )

    # 一类买点：笔低点低于中枢下沿（中枢下方），且底背驰（力度衰减）
    if bi.low < zs.zd:
        if _check_force_decreasing(
            bi, all_bis, "down", closes=closes, config=config, macd_hist=macd_hist, force_cache=force_cache
        ):
            return MMD(
                mmd_type=MMDType.BUY_1,
                zs=zs,
                bi=bi,
                msg=f"中枢下方力度衰减，一类买点 (l={bi.low:.2f} < zd={zs.zd:.2f})",
            )

    # 二类买点：回调不创新低
    if bi.low > zs.zd and bi.low > zs.dd:
        bi_idx = bi.index
        if bi_idx >= 2:
            prev_down_bi = all_bis[bi_idx - 2] if bi_idx - 2 < len(all_bis) else None
            if prev_down_bi and prev_down_bi.direction.value == "down":
                if bi.low > prev_down_bi.low:
                    return MMD(
                        mmd_type=MMDType.BUY_2,
                        zs=zs,
                        bi=bi,
                        msg=f"回调不创新低，二类买点 (l={bi.low:.2f})",
                    )

    return None


def _check_sell_point(
    bi: BI,
    zs: ZS,
    all_bis: list[BI],
    config: ChanlunConfig | None = None,
    closes: list[float] | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> MMD | None:
    """检查向上笔是否形成卖点。"""
    # 三类卖点优先：跌破中枢后，反弹不突破中枢下沿（必须先于二卖判定）
    if bi.high < zs.zd:
        return MMD(
            mmd_type=MMDType.SELL_3,
            zs=zs,
            bi=bi,
            msg=f"反弹不破中枢下沿，三类卖点 (h={bi.high:.2f} < zd={zs.zd:.2f})",
        )

    # 一类卖点：笔高点高于中枢上沿，且顶背驰（力度衰减）
    if bi.high > zs.zg:
        if _check_force_decreasing(
            bi, all_bis, "up", closes=closes, config=config, macd_hist=macd_hist, force_cache=force_cache
        ):
            return MMD(
                mmd_type=MMDType.SELL_1,
                zs=zs,
                bi=bi,
                msg=f"中枢上方力度衰减，一类卖点 (h={bi.high:.2f} > zg={zs.zg:.2f})",
            )

    # 二类卖点：反弹不创新高
    if bi.high < zs.zg and bi.high < zs.gg:
        bi_idx = bi.index
        if bi_idx >= 2:
            prev_up_bi = all_bis[bi_idx - 2] if bi_idx - 2 < len(all_bis) else None
            if prev_up_bi and prev_up_bi.direction.value == "up":
                if bi.high < prev_up_bi.high:
                    return MMD(
                        mmd_type=MMDType.SELL_2,
                        zs=zs,
                        bi=bi,
                        msg=f"反弹不创新高，二类卖点 (h={bi.high:.2f})",
                    )

    return None


def _check_force_decreasing(
    bi: BI,
    all_bis: list[BI],
    direction: str,
    closes: list[float] | None = None,
    config: ChanlunConfig | None = None,
    macd_hist: list[float] | None = None,
    force_cache: dict[int, float] | None = None,
) -> bool:
    """检查力度是否衰减（优先使用 MACD hist 面积，回退到幅度）。"""
    bi_idx = bi.index
    if bi_idx < 2 or bi_idx >= len(all_bis):
        return False

    # 找前一个同向笔
    for j in range(bi_idx - 1, -1, -1):
        prev = all_bis[j]
        if prev.direction.value == direction:
            if closes:
                from easy_tdx.chanlun.beichi import _calc_bi_force

                curr_force = _calc_bi_force(
                    bi, closes, config, macd_hist=macd_hist, force_cache=force_cache
                )
                prev_force = _calc_bi_force(
                    prev, closes, config, macd_hist=macd_hist, force_cache=force_cache
                )
            else:
                curr_force = bi.high - bi.low
                prev_force = prev.high - prev.low

            if direction == "down":
                return curr_force < prev_force and bi.low < prev.low
            else:
                return curr_force < prev_force and bi.high > prev.high

    return False

