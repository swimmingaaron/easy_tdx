"""Box Oscillation Strategy (箱体震荡高抛低吸)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import RSI, KDJ

@register_strategy
class BoxOscillationStrategy(BaseStrategy):
    name = "box_oscillation"
    display_name = "箱体震荡高抛低吸"
    category = "daily_analysis"
    description = "利用阶段箱体支撑与阻力位，在箱底超卖企稳时低吸，箱顶阻力位高抛"
    params_schema = {"window": 20, "lower_bound_pct": 0.25, "upper_bound_pct": 0.75}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        w = int(self.params.get("window", 20))
        low_box = out["low"].rolling(w).min()
        high_box = out["high"].rolling(w).max()
        box_range = np.maximum(high_box - low_box, 1e-4)

        # 价格在箱体内的相对位置 (0 ~ 1)
        rel_pos = (out["close"] - low_box) / box_range

        k_arr, d_arr, j_arr = KDJ(out["close"].values, out["high"].values, out["low"].values)
        k = pd.Series(k_arr, index=out.index)
        d = pd.Series(d_arr, index=out.index)
        rsi = pd.Series(RSI(out["close"].values, 14), index=out.index)

        # 箱底支撑买入信号：位于箱体下部 25%，且 KDJ 金叉或 RSI < 40 拐头向上
        kdj_cross = (k > d) & (k.shift(1) <= d.shift(1))
        out["buy_signal"] = (rel_pos <= self.params.get("lower_bound_pct", 0.25)) & (kdj_cross | (rsi < 40))
        # 箱顶阻力卖出信号：触及箱体上部 75% 或超买
        out["sell_signal"] = (rel_pos >= self.params.get("upper_bound_pct", 0.75)) | (rsi > 75)
        return out
