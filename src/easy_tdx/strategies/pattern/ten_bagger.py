import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, HHV, REF

@register_strategy
class TenBaggerStrategy(BaseStrategy):
    name = "ten_bagger"
    display_name = "十倍牛股共振选股战法"
    category = "pattern"
    description = "高景气成长特征 + 股价放量突破 120 日历史大平台、均线多头大均线向上"
    params_schema = {"platform_period": 120}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"]
        ma20, ma60, ma120 = MA(c, 20), MA(c, 60), MA(c, 120)
        is_bull_align = (c > ma20) & (ma20 > ma60) & (ma60 > ma120)
        h_platform = REF(HHV(res["high"], self.params["platform_period"]), 1)
        
        breakout = (c > h_platform) & (res["volume"] > MA(res["volume"], 5) * 1.5)
        res["buy_signal"] = is_bull_align & breakout
        res["sell_signal"] = c < ma60
        return res
