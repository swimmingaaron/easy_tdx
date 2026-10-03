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
    params_schema = {"surge_pct": 7.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        c = out["close"].values
        v = out["volume"].values if "volume" in out.columns else out["vol"].values
        c_series = pd.Series(c, index=out.index)
        v_series = pd.Series(v, index=out.index)

        ref_c1 = c_series.shift(1)
        pct = (c_series - ref_c1) / np.maximum(ref_c1, 1e-4) * 100
        surge_threshold = float(self.params.get("surge_pct", 7.0))
        is_surge = pct >= surge_threshold
        has_limit_up = (pct >= 9.5).rolling(5).max() == 1
        
        # 龙头特征：前1~2日曾出现大阳或涨停
        had_surge = (is_surge.shift(1) == True) | (is_surge.shift(2) == True) | (has_limit_up.shift(1) == True)
        ma5 = pd.Series(MA(c, 5), index=out.index)
        ma5_vol = pd.Series(MA(v, 5), index=out.index)
        
        # 缩量回踩 MA5 企稳（首阴/调整）
        pullback_support = (
            (out["low"] <= ma5 * 1.02)
            & (c_series >= ma5 * 0.99)
            & (v_series <= ma5_vol * 1.3)
            & (c_series < ref_c1)
        )
        # 强势放量接力突破
        relay_break = is_surge & (v_series >= ma5_vol * 1.1) & had_surge

        buy_sig = (had_surge & pullback_support) | relay_break
        out["buy_signal"] = buy_sig.fillna(False)
        out["sell_signal"] = (c_series < ma5).fillna(False)
        return out
