"""Expectation Repricing Strategy (预期差重估突破)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class ExpectationRepricingStrategy(BaseStrategy):
    name = "expectation_repricing"
    display_name = "预期差重估"
    category = "daily_analysis"
    description = "长期估值低洼或横盘蓄势后，机构资金大举重估流入，突破60日均线"
    params_schema = {"ma_long": 60, "vol_mult": 1.6}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ma60 = pd.Series(MA(out["close"].values, int(self.params.get("ma_long", 60))), index=out.index)
        ma20_vol = pd.Series(MA(out["volume"].values, 20), index=out.index)

        # 股价突破60日均线，且成交量明显放大
        cross_ma60 = (out["close"] > ma60) & (out["close"].shift(1) <= ma60.shift(1))
        vol_surge = out["volume"] > (ma20_vol * float(self.params.get("vol_mult", 1.6)))

        out["buy_signal"] = cross_ma60 & vol_surge
        out["sell_signal"] = out["close"] < ma60 * 0.96
        return out
