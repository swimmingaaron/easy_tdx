"""周线大阳横盘起爆策略 (Weekly Big Bull Consolidation Strategy).

形态逻辑（基于 300741 华宝新能、605058 澳弘电子 等经典大牛股周线复盘）：
------------------------------------------------------------------------
1. 前期深幅回调 (Prior Drop)：
   在出现标志性大阳线之前，周线级别经历充分调整，前期波段跌幅超过 20%（排除高位加速或出货形态）。
2. 周线标志性突破大阳 (Big Bull Candle)：
   单周涨幅超过 7%（通常伴随明显放量），长阳拔起宣告阶段探底结束或多头第一波强攻。
3. 平台横盘强势洗盘 (Horizontal Consolidation)：
   大阳线出现后，连续 2 根及以上周 K 线（2 ~ 6 周）维持横盘缩量蓄势：
   - 防守铁律：横盘期间各周最低价不能跌破大阳线最低价（底线不破）；
   - 收盘坚挺：收盘价基本保持在大阳线开盘价上方（甚至大阳线实体中轴上方）；
   - 振幅收敛：横盘箱体收盘极差通常在 15% 以内，筹码高度锁定；
   - 缩量洗盘：横盘周期均量明显低于起爆大阳线周量（无主力出货迹象）。
4. 后续主升浪拉升 (Subsequent Markup)：
   蓄势充沛后，在横盘末期或突破横盘箱体上沿时迎来第二波主升浪爆发！
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, HHV, LLV


@register_strategy
class WeeklyBigBullConsolidationStrategy(BaseStrategy):
    name = "weekly_big_bull_consolidation"
    display_name = "周线大阳横盘起爆策略"
    category = "technical"
    description = "前期周线跌幅超20%，单周收出7%以上大阳线，随后2周及以上横盘缩量蓄势不破大阳低点，捕捉主升浪起爆点。"

    params_list = [
        Param("prior_drop_pct", float, default=20.0, min_value=10.0, max_value=60.0, step=5.0, label="前期跌幅阈值(%)", description="大阳线前波段最大跌幅要求"),
        Param("prior_lookback", int, default=20, min_value=8, max_value=50, step=2, label="前期跌幅统计周数", description="大阳线前寻找高低点的回溯周数"),
        Param("big_bull_min_pct", float, default=7.0, min_value=5.0, max_value=20.0, step=0.5, label="大阳线涨幅阈值(%)", description="标志性大阳线的单周涨幅下限"),
        Param("min_consolidation_weeks", int, default=2, min_value=2, max_value=10, step=1, label="最小横盘周数", description="大阳线后连续横盘的最少周数"),
        Param("max_consolidation_weeks", int, default=8, min_value=3, max_value=15, step=1, label="最大横盘周数", description="大阳线后横盘考察的最长周数"),
        Param("max_consolidation_amplitude", float, default=1.16, min_value=1.05, max_value=1.35, step=0.01, label="横盘收盘振幅上限", description="横盘期间最高收盘与最低收盘比值"),
        Param("volume_shrink_ratio", float, default=1.15, min_value=0.5, max_value=1.5, step=0.05, label="横盘均量容差上限", description="横盘期均量相对于大阳周成交量的倍数上限"),
    ]

    params_schema = {
        "prior_drop_pct": 20.0,
        "prior_lookback": 20,
        "big_bull_min_pct": 7.0,
        "min_consolidation_weeks": 2,
        "max_consolidation_weeks": 8,
        "max_consolidation_amplitude": 1.16,
        "volume_shrink_ratio": 1.15,
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n = len(res)
        if n < 20:
            res["buy_signal"] = False
            res["sell_signal"] = False
            return res

        prior_drop_pct = float(self.params.get("prior_drop_pct", 20.0)) / 100.0
        prior_lookback = int(self.params.get("prior_lookback", 20))
        big_bull_min_pct = float(self.params.get("big_bull_min_pct", 7.0))
        min_cons = int(self.params.get("min_consolidation_weeks", 2))
        max_cons = int(self.params.get("max_consolidation_weeks", 8))
        max_amp = float(self.params.get("max_consolidation_amplitude", 1.16))
        vol_tol = float(self.params.get("volume_shrink_ratio", 1.15))

        opens = res["open"].values
        highs = res["high"].values
        lows = res["low"].values
        closes = res["close"].values
        volumes = res["volume"].values if "volume" in res.columns else res["vol"].values

        # Calculate percentage change if not already present
        pcts = np.zeros(n)
        for i in range(1, n):
            prev = closes[i - 1]
            pcts[i] = (closes[i] - prev) / prev * 100.0 if prev > 0 else 0.0

        buy_signal = np.zeros(n, dtype=bool)
        sell_signal = np.zeros(n, dtype=bool)
        is_pattern = np.zeros(n, dtype=bool)

        # Vectorized / loop evaluation for each bar
        # For bar i: is bar i currently at a valid consolidation stage?
        for i in range(min_cons + 10, n):
            # Check if there is an anchor big bull candle at i - N
            for N in range(min_cons, max_cons + 1):
                big_idx = i - N
                if big_idx < 5:
                    continue

                b_pct = pcts[big_idx]
                b_open = opens[big_idx]
                b_close = closes[big_idx]
                b_low = lows[big_idx]
                b_vol = volumes[big_idx]

                # 1. Big bull candle criteria
                if b_pct < big_bull_min_pct or b_close <= b_open:
                    continue

                # 2. Prior drop check
                look_start = max(0, big_idx - prior_lookback)
                prior_h = np.max(highs[look_start:big_idx])
                prior_l = min(np.min(lows[look_start:big_idx]), b_low)
                if prior_h <= 0:
                    continue
                drop = (prior_h - prior_l) / prior_h
                if drop < prior_drop_pct:
                    continue

                # 3. Consolidation bars: big_idx + 1 to i
                cons_l = lows[big_idx + 1 : i + 1]
                cons_c = closes[big_idx + 1 : i + 1]
                cons_v = volumes[big_idx + 1 : i + 1]

                # Low defense: cannot break big candle low (with 1.5% margin)
                if np.min(cons_l) < b_low * 0.985:
                    continue

                # Close defense: cannot sink below big candle open (with 3% margin)
                if np.min(cons_c) < b_open * 0.97:
                    continue

                # Amplitude defense
                c_max = np.max(cons_c)
                c_min = np.min(cons_c)
                if c_min > 0 and (c_max / c_min) > max_amp:
                    continue

                # Volume contraction
                if np.mean(cons_v) > b_vol * vol_tol:
                    continue

                # Qualified consolidation!
                is_pattern[i] = True
                # Trigger buy signal on the bars of consolidation (especially at N == min_cons or on all active cons bars)
                buy_signal[i] = True
                break

            # Sell signal: if previously in pattern, but current close falls below MA5 or breaks anchor low
            if i >= 1 and is_pattern[i - 1] and not is_pattern[i]:
                if closes[i] < closes[i - 1] * 0.95 or (i >= 5 and closes[i] < np.mean(closes[i - 5 : i])):
                    sell_signal[i] = True

        res["buy_signal"] = buy_signal
        res["sell_signal"] = sell_signal
        res["is_pattern"] = is_pattern
        return res
