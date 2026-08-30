import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MACD, CROSS

@register_strategy
class MACDCrossStrategy(BaseStrategy):
    name = "macd_cross"
    display_name = "MACD趋势共振策略"
    category = "technical"
    description = "DIF 上穿 DEA 金叉且柱状图转红买入，死叉卖出"
    params_schema = {"short": 12, "long": 26, "mid": 9}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        dif, dea, hist = MACD(res["close"], self.params["short"], self.params["long"], self.params["mid"])
        res["buy_signal"] = CROSS(dif, dea) & (hist > 0)
        res["sell_signal"] = CROSS(dea, dif)
        return res
