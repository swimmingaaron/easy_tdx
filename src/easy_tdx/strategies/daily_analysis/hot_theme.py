"""Hot Theme Resonance Strategy (热点题材板块共振策略)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class HotThemeStrategy(BaseStrategy):
    name = "hot_theme_resonance"
    display_name = "热点题材共振"
    category = "daily_analysis"
    description = "捕捉板块热点爆发与个股量比共振，日内强力拉升介入"
    params_schema = {"min_gain_pct": 3.0, "vol_ratio": 1.8}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ma5_vol = MA(out["volume"], 5)
        gain_pct = (out["close"] - out["close"].shift(1)) / out["close"].shift(1) * 100
        vol_ratio = out["volume"] / np.maximum(ma5_vol, 1e-4)

        # 涨幅大于 3%，量比大于 1.8，且创 5 日新高
        is_strong = (gain_pct >= self.params.get("min_gain_pct", 3.0)) & (vol_ratio >= self.params.get("vol_ratio", 1.8))
        break_5d = out["close"] >= out["high"].rolling(5).max()

        out["buy_signal"] = is_strong & break_5d
        out["sell_signal"] = out["close"] < out["open"]
        return out
