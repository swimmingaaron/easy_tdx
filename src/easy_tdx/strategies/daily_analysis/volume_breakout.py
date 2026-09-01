"""Volume Price Breakout Strategy (放量突破前高平台)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class VolumeBreakoutStrategy(BaseStrategy):
    name = "volume_breakout_platform"
    display_name = "放量突破前高平台"
    category = "daily_analysis"
    description = "股价突破过去 20 日最高价平台，成交量同步放大至 20 日均量 1.8 倍以上"
    params_schema = {"lookback": 20, "vol_mult": 1.8}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        lookback = self.params.get("lookback", 20)
        vol_mult = self.params.get("vol_mult", 1.8)

        high_prev = out["high"].shift(1).rolling(lookback).max()
        ma20_vol = MA(out["volume"], lookback)

        # 突破前高且放量
        breakout = out["close"] > high_prev
        vol_surge = out["volume"] > (ma20_vol * vol_mult)

        out["buy_signal"] = breakout & vol_surge
        out["sell_signal"] = out["close"] < high_prev * 0.97
        return out
