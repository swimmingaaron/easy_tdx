"""Emotion Cycle Timing Strategy (短线情绪周期顺势战法)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import RSI, MA

@register_strategy
class EmotionCycleDailyStrategy(BaseStrategy):
    name = "emotion_cycle_daily"
    display_name = "短线情绪周期顺势"
    category = "daily_analysis"
    description = "识别市场情绪从冰点转暖、主升浪展开阶段，顺应赚钱效应进场"
    params_schema = {"rsi_warm_threshold": 48.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        rsi = pd.Series(RSI(out["close"].values, 6), index=out.index)
        ma5 = pd.Series(MA(out["close"].values, 5), index=out.index)
        ma10 = pd.Series(MA(out["close"].values, 10), index=out.index)
        
        # 情绪转暖标志：RSI从低位上穿中轴，伴随MA5拐头向上，量能同步放大
        rsi_warm = (rsi > self.params.get("rsi_warm_threshold", 48.0)) & (rsi.shift(1) <= 48.0)
        trend_ok = (out["close"] > ma5) & (ma5 >= ma5.shift(1))

        out["buy_signal"] = rsi_warm & trend_ok
        out["sell_signal"] = (rsi > 85) | (out["close"] < ma10)
        return out
