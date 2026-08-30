import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import BOLL, CROSS

@register_strategy
class BollingerBreakoutStrategy(BaseStrategy):
    name = "bollinger_breakout"
    display_name = "布林带突破策略"
    category = "technical"
    description = "价格突破布林带上轨强势买入，跌破中轨卖出"
    params_schema = {"period": 20, "std_mult": 2.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        mid, up, low = BOLL(res["close"], self.params["period"], self.params["std_mult"])
        res["buy_signal"] = CROSS(res["close"], up)
        res["sell_signal"] = CROSS(mid, res["close"])
        return res
