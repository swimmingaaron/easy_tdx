"""Growth Quality Strategy (成长质量多因子量化策略)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class GrowthQualityStrategy(BaseStrategy):
    name = "growth_quality"
    display_name = "成长质量量化"
    category = "daily_analysis"
    description = "综合动量质量、均线支撑与低波动特征，精选稳健上行的白马与成长股"
    params_schema = {"mom_window": 20}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ma20 = pd.Series(MA(out["close"].values, 20), index=out.index)
        ma60 = pd.Series(MA(out["close"].values, 60), index=out.index)
        
        # 动量计算
        mom = (out["close"] - out["close"].shift(20)) / out["close"].shift(20)
        # 波动率计算 (20日收益率标准差)
        ret = out["close"].pct_change()
        volatility = ret.rolling(20).std()

        # 条件：均线多头且动量在前列、波动受控
        trend_ok = (out["close"] > ma20) & (ma20 > ma60)
        healthy_mom = (mom > 0.05) & (volatility < 0.035)

        out["buy_signal"] = trend_ok & healthy_mom
        out["sell_signal"] = out["close"] < ma20
        return out
