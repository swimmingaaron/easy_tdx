"""Event Driven Strategy (事件驱动与公告催化突破)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class EventDrivenStrategy(BaseStrategy):
    name = "event_driven"
    display_name = "事件催化驱动"
    category = "daily_analysis"
    description = "捕捉重大事件催化、突发业绩超预期或政策利好带来的跳空放量突破"
    params_schema = {"gap_pct": 0.8, "vol_ratio": 1.2}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        gap_pct = float(self.params.get("gap_pct", 0.8))
        vol_ratio = float(self.params.get("vol_ratio", 1.2))

        ma5_vol = pd.Series(MA(out["volume"].values, 5), index=out.index)
        prev_c = out["close"].shift(1)
        
        # 跳空高开或强势放量长阳突破
        gap_up = (out["open"] >= prev_c * (1 + gap_pct / 100)) & (out["close"] >= out["open"])
        vol_breakout = out["volume"] >= (ma5_vol * vol_ratio)
        surge_day = (out["close"] >= prev_c * 1.025) & (out["close"] >= out["open"]) & vol_breakout

        buy_sig = (gap_up & vol_breakout) | surge_day
        out["buy_signal"] = buy_sig.fillna(False)
        out["sell_signal"] = (out["close"] < prev_c * 0.97).fillna(False)
        return out
