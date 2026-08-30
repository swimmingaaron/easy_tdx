"""Bull Trend Strategy (均线多头排列战法)."""
from __future__ import annotations
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class BullTrendDailyStrategy(BaseStrategy):
    name = "bull_trend"
    display_name = "均线多头排列"
    category = "daily_analysis"
    description = "MA5 > MA10 > MA20 多头排列，顺势回踩 5日/10日 均线低吸"
    params_schema = {
        "fast_period": 5,
        "mid_period": 10,
        "slow_period": 20,
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        fast_p = int(self.params.get("fast_period", 5))
        mid_p = int(self.params.get("mid_period", 10))
        slow_p = int(self.params.get("slow_period", 20))

        ma5 = pd.Series(MA(out["close"].values, fast_p), index=out.index)
        ma10 = pd.Series(MA(out["close"].values, mid_p), index=out.index)
        ma20 = pd.Series(MA(out["close"].values, slow_p), index=out.index)

        bull_alignment = (ma5 > ma10) & (ma10 > ma20)
        ma5_rising = ma5 >= ma5.shift(1)
        pullback = (out["low"] <= ma5 * 1.015) & (out["close"] >= ma10 * 0.99)

        out["buy_signal"] = bull_alignment & ma5_rising & pullback
        out["sell_signal"] = (out["close"] < ma20) & (out["close"].shift(1) >= ma20.shift(1))
        return out
