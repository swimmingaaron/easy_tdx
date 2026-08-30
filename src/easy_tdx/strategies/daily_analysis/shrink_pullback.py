"""Shrink Volume Pullback Strategy (缩量回踩强支撑策略)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class ShrinkPullbackStrategy(BaseStrategy):
    name = "shrink_pullback"
    display_name = "缩量回踩强支撑"
    category = "daily_analysis"
    description = "均线多头趋势中，股价缩量回调至 MA5 或 MA10 支撑位，提供低吸买点"
    params_schema = {"vol_shrink_ratio": 0.75}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ma5 = pd.Series(MA(out["close"].values, 5), index=out.index)
        ma10 = pd.Series(MA(out["close"].values, 10), index=out.index)
        ma20 = pd.Series(MA(out["close"].values, 20), index=out.index)
        ma5_vol = pd.Series(MA(out["volume"].values, 5), index=out.index)

        # 多头大背景
        bull_trend = (ma10 > ma20) & (out["close"] > ma20)
        # 缩量回调（成交量小于5日均量 0.75倍）
        shrink_vol = out["volume"] <= (ma5_vol * float(self.params.get("vol_shrink_ratio", 0.75)))
        # 触及 MA5 或 MA10 支撑企稳
        touch_support = (out["low"] <= ma5 * 1.01) & (out["close"] >= ma10 * 0.99)

        out["buy_signal"] = bull_trend & shrink_vol & touch_support
        out["sell_signal"] = out["close"] < ma20
        return out
