import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, REF, LLV

@register_strategy
class DragonHeadFirstDropStrategy(BaseStrategy):
    name = "dragon_head_first_drop"
    display_name = "龙头首阴 / 龙回头低吸策略"
    category = "short_term"
    description = "3连板以上高位强势龙头首次收阴线回踩 5日/10日均线企稳低吸"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"]
        ma5, ma10 = MA(c, 5), MA(c, 10)
        ret_3d = (REF(c, 1) / REF(c, 4) - 1) * 100
        was_strong_leader = ret_3d >= 25.0
        
        first_drop = (c < REF(c, 1)) & (res["low"] <= ma5 * 1.01) & (c >= ma10)
        res["buy_signal"] = was_strong_leader & first_drop
        res["sell_signal"] = c < ma10 * 0.97
        return res
