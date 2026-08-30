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
    description = "强势涨停板后缩量回踩 MA5 或强势接力突破，捕捉超额连板溢价"
    params_schema = {"limit_up_pct": 9.5}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        pct = (out["close"] - out["close"].shift(1)) / out["close"].shift(1) * 100
        is_limit_up = pct >= float(self.params.get("limit_up_pct", 9.5))
        
        # 前1~2日曾涨停
        had_limit_up = (is_limit_up.shift(1) == True) | (is_limit_up.shift(2) == True)
        ma5 = pd.Series(MA(out["close"].values, 5), index=out.index)
        ma5_vol = pd.Series(MA(out["volume"].values, 5), index=out.index)
        
        # 缩量回踩 MA5 企稳，或接力连板突破
        pullback_support = (out["low"] <= ma5 * 1.02) & (out["close"] >= ma5) & (out["volume"] < ma5_vol * 1.2)
        relay_break = is_limit_up & (out["volume"] > ma5_vol)

        out["buy_signal"] = (had_limit_up & pullback_support) | relay_break
        out["sell_signal"] = out["close"] < ma5 * 0.97
        return out
