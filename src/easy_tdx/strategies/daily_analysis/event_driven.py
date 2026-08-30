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
    params_schema = {"gap_pct": 1.5, "vol_ratio": 1.8}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        gap_pct = self.params.get("gap_pct", 1.5)
        vol_ratio = self.params.get("vol_ratio", 1.8)

        ma5_vol = MA(out["volume"], 5)
        # 跳空高开且收盘守住开盘价
        gap_up = (out["open"] > out["high"].shift(1) * (1 + gap_pct / 100)) & (out["close"] >= out["open"])
        vol_breakout = out["volume"] > (ma5_vol * vol_ratio)

        out["buy_signal"] = gap_up & vol_breakout
        out["sell_signal"] = out["close"] < out["open"].shift(0) * 0.96
        return out
