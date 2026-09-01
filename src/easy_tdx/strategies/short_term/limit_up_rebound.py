import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import REF

@register_strategy
class LimitUpReboundStrategy(BaseStrategy):
    name = "limit_up_rebound"
    display_name = "炸板次日反包策略"
    category = "short_term"
    description = "昨日炸板或留长上影线，次日阳线迅速吞没昨日上影线强势反包买入"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"].values
        prev_h = pd.Series(REF(res["high"].values, 1), index=res.index)
        prev_c = pd.Series(REF(c, 1), index=res.index)
        prev_c2 = pd.Series(REF(c, 2), index=res.index)
        
        # 昨日冲高回落留下上影线，次日大阳反包
        prev_was_broken = (prev_h / np.maximum(prev_c2, 1e-4) >= 1.03) & (prev_c < prev_h * 0.99)
        rebound_engulf = (res["close"] >= prev_h * 0.995) & (res["close"] > res["open"])
        
        buy_sig = prev_was_broken & rebound_engulf
        sell_sig = (res["close"] < prev_c * 0.97) | (res["close"] < res["open"] * 0.98)
        
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
