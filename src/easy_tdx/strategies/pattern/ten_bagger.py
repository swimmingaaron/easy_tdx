import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, HHV, REF

@register_strategy
class TenBaggerStrategy(BaseStrategy):
    name = "ten_bagger"
    display_name = "十倍牛股共振选股战法"
    category = "pattern"
    description = "高景气成长特征 + 股价放量突破阶段大平台、均线多头大均线向上"
    params_schema = {"platform_period": 30}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"].values
        ma20 = pd.Series(MA(c, 20), index=res.index)
        ma60 = pd.Series(MA(c, 60), index=res.index)
        is_bull_align = (res["close"] >= ma20) & (ma20 >= ma60)
        
        p_len = int(self.params.get("platform_period", 30))
        h_platform = pd.Series(REF(HHV(res["high"].values, p_len), 1), index=res.index)
        ma5_vol = pd.Series(MA(res["volume"].values, 5), index=res.index)
        
        breakout = (res["close"] >= h_platform * 0.99) & (res["volume"] >= ma5_vol * 1.1)
        buy_sig = (is_bull_align & breakout) | ((res["close"] > ma20) & (res["close"].shift(1) <= ma20.shift(1)) & (res["close"] > ma60))
        sell_sig = res["close"] < ma60
        
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
