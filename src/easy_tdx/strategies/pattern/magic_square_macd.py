import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MACD, MA, CROSS

@register_strategy
class MagicSquareMACDStrategy(BaseStrategy):
    name = "magic_square_macd"
    display_name = "九宫格MACD共振战法"
    category = "pattern"
    description = "九宫格放量平台突破搭配 MACD 零轴上方/附近二次金叉共振"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"].values
        dif, dea, hist = MACD(c)
        ma5_vol = MA(res["volume"].values, 5)
        
        gold = CROSS(dif, dea)
        vol_ok = res["volume"].values >= (ma5_vol * 0.9)
        near_zero = dif >= -0.3
        
        buy_sig = gold & (near_zero | vol_ok)
        sell_sig = CROSS(dea, dif)
        
        res["buy_signal"] = pd.Series(buy_sig, index=res.index).fillna(False)
        res["sell_signal"] = pd.Series(sell_sig, index=res.index).fillna(False)
        return res
