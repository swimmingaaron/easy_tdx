import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MACD, MA, CROSS

@register_strategy
class MagicSquareMACDStrategy(BaseStrategy):
    name = "magic_square_macd"
    display_name = "九宫格MACD共振战法"
    category = "pattern"
    description = "九宫格放量平台突破搭配 MACD 零轴上方二次金叉"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        dif, dea, hist = MACD(res["close"])
        res["buy_signal"] = CROSS(dif, dea) & (dif >= 0) & (res["volume"] > MA(res["volume"], 5))
        res["sell_signal"] = CROSS(dea, dif)
        return res
