import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, REF

@register_strategy
class DragonHeadFirstDropStrategy(BaseStrategy):
    name = "dragon_head_first_drop"
    display_name = "龙头首阴 / 龙回头低吸策略"
    category = "short_term"
    description = "强势龙头波段拉升后首次收阴线回踩 5日/10日均线企稳低吸"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"].values
        ma5 = pd.Series(MA(c, 5), index=res.index)
        ma10 = pd.Series(MA(c, 10), index=res.index)
        
        c_series = pd.Series(c, index=res.index)
        ref_c1 = pd.Series(REF(c, 1), index=res.index)
        ref_c4 = pd.Series(REF(c, 4), index=res.index)
        ret_3d = (ref_c1 / np.maximum(ref_c4, 1e-4) - 1) * 100
        was_strong_leader = ret_3d >= 6.0
        
        first_drop = (c_series <= ref_c1) & (res["low"] <= ma5 * 1.015) & (c_series >= ma10 * 0.985)
        buy_sig = was_strong_leader & first_drop
        sell_sig = (c_series < ma10 * 0.97) | (c_series > ma5 * 1.08)
        
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
