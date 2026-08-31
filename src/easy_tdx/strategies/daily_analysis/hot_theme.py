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
    params_schema = {"min_gain_pct": 2.0, "vol_ratio": 1.3}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ma5_vol = pd.Series(MA(out["volume"].values, 5), index=out.index)
        gain_pct = (out["close"] - out["close"].shift(1)) / np.maximum(out["close"].shift(1), 1e-4) * 100
        vol_ratio = out["volume"] / np.maximum(ma5_vol, 1e-4)

        # 涨幅大于 2%，量比大于 1.3，且突破近 5 日高点
        min_g = float(self.params.get("min_gain_pct", 2.0))
        min_vr = float(self.params.get("vol_ratio", 1.3))
        is_strong = (gain_pct >= min_g) & (vol_ratio >= min_vr)
        break_5d = out["close"] >= out["high"].shift(1).rolling(5).max() * 0.99

        buy_sig = (is_strong & break_5d) | (is_strong & (out["close"] > out["open"]))
        out["buy_signal"] = buy_sig.fillna(False)
        out["sell_signal"] = (out["close"] < out["open"] * 0.98).fillna(False)
        return out
