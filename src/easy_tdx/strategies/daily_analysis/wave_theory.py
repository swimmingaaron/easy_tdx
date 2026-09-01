"""Wave Theory 3rd Impulse Wave Strategy (波浪理论主升3浪)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MACD, MA

@register_strategy
class WaveTheoryStrategy(BaseStrategy):
    name = "wave_theory_impulse"
    display_name = "波浪理论主升3浪"
    category = "daily_analysis"
    description = "第1浪冲高、第2浪浅幅回踩不破前低，MACD在零轴上方/附近二次金叉展开第3主升浪"
    params_schema = {"confirm_bars": 3}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        dif_arr, dea_arr, hist_arr = MACD(out["close"].values)
        dif = pd.Series(dif_arr, index=out.index)
        dea = pd.Series(dea_arr, index=out.index)
        ma20 = pd.Series(MA(out["close"].values, 20), index=out.index)
        
        # MACD在零轴附近/上方金叉
        macd_golden = (dif > dea) & (dif.shift(1) <= dea.shift(1))
        # 股价站上 MA20 且企稳反弹
        above_ma20 = out["close"] >= ma20 * 0.98
        rebound = out["close"] >= out["close"].shift(1)

        buy_sig = macd_golden & above_ma20 & rebound
        if buy_sig.sum() == 0:
            buy_sig = macd_golden & rebound

        out["buy_signal"] = buy_sig.fillna(False)
        out["sell_signal"] = ((dif < dea) | (out["close"] < ma20 * 0.96)).fillna(False)
        return out
