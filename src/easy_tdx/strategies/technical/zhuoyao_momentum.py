import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, EMA, HHV, REF

@register_strategy
class ZhuoyaoMomentumStrategy(BaseStrategy):
    name = "zhuoyao_momentum"
    display_name = "捉妖记短线强势战法"
    category = "technical"
    description = "多均线高度粘合后突然放量多头发散，捉短线妖股启动点"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"]
        ma5, ma10, ma20, ma60 = MA(c, 5), MA(c, 10), MA(c, 20), MA(c, 60)
        # 均线粘合条件
        ma_max = pd.concat([ma5, ma10, ma20], axis=1).max(axis=1)
        ma_min = pd.concat([ma5, ma10, ma20], axis=1).min(axis=1)
        adhesive = (ma_max - ma_min) / c < 0.03
        
        # 突破发散
        breakout = (c > ma5) & (ma5 > ma10) & (ma10 > ma20) & (c / REF(c, 1) > 1.05)
        res["buy_signal"] = adhesive.shift(1) & breakout
        res["sell_signal"] = c < ma10
        return res
