"""Bottom Volume Surge Strategy (底部放量突破反转)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class BottomVolumeStrategy(BaseStrategy):
    name = "bottom_volume"
    display_name = "底部放量反转"
    category = "daily_analysis"
    description = "检测长期下跌或深度回调后底部放量企稳信号，捕捉反转第一起爆点"
    params_schema = {"vol_mult": 2.0, "decline_pct": 0.10, "lookback": 20}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        vol_mult = float(self.params.get("vol_mult", 2.0))
        lookback = int(self.params.get("lookback", 20))
        decline_pct = float(self.params.get("decline_pct", 0.10))

        ma5_vol = pd.Series(MA(out["volume"].values, 5), index=out.index)
        ma5_close = pd.Series(MA(out["close"].values, 5), index=out.index)
        high_20 = out["high"].rolling(lookback).max()
        drawdown = (high_20 - out["close"]) / high_20

        # 条件：从阶段高点回落超过10%，当日放量超过5日均量2倍，且K线收阳企稳
        is_rebound = (out["close"] > out["open"]) & (out["close"] > out["close"].shift(1))
        vol_surge = out["volume"] > (ma5_vol * vol_mult)
        was_depressed = drawdown >= decline_pct

        out["buy_signal"] = was_depressed & vol_surge & is_rebound
        out["sell_signal"] = out["close"] < ma5_close
        return out
