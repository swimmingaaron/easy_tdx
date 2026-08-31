"""Dragon Head Momentum Strategy (龙头战法/首板接力/缩量首阴)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class DragonHeadStrategy(BaseStrategy):
    name = "dragon_head_momentum"
    display_name = "龙头战法接力"
    category = "daily_analysis"
    description = "强势涨停或大阳突破后缩量回踩 MA5 或强势接力突破，捕捉超额连板溢价"
    params_schema = {"surge_pct": 3.5}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        pct = (out["close"] - out["close"].shift(1)) / np.maximum(out["close"].shift(1), 1e-4) * 100
        is_surge = pct >= float(self.params.get("surge_pct", 3.5))
        
        # 前1~2日曾大涨/涨停
        had_surge = (is_surge.shift(1) == True) | (is_surge.shift(2) == True)
        ma5 = pd.Series(MA(out["close"].values, 5), index=out.index)
        ma5_vol = pd.Series(MA(out["volume"].values, 5), index=out.index)
        
        # 缩量回踩 MA5 企稳，或接力突破
        pullback_support = (out["low"] <= ma5 * 1.02) & (out["close"] >= ma5 * 0.99) & (out["volume"] <= ma5_vol * 1.3)
        relay_break = is_surge & (out["volume"] >= ma5_vol * 0.9)

        buy_sig = (had_surge & pullback_support) | relay_break
        out["buy_signal"] = buy_sig.fillna(False)
        out["sell_signal"] = (out["close"] < ma5 * 0.97).fillna(False)
        return out
