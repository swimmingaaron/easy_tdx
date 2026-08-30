import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import REF

@register_strategy
class LimitUpReboundStrategy(BaseStrategy):
    name = "limit_up_rebound"
    display_name = "炸板次日反包策略"
    category = "short_term"
    description = "昨日炸板放量留长上影线，次日阳线迅速吞没昨日上影线反包买入"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        prev_h = REF(res["high"], 1)
        prev_c = REF(res["close"], 1)
        prev_was_broken = (prev_h / REF(res["close"], 2) >= 1.09) & (prev_c < prev_h * 0.96)
        
        rebound_engulf = res["close"] > prev_h
        res["buy_signal"] = prev_was_broken & rebound_engulf
        res["sell_signal"] = res["close"] < prev_c
        return res
