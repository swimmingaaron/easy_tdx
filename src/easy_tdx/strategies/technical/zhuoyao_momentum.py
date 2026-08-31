import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, REF

@register_strategy
class ZhuoyaoMomentumStrategy(BaseStrategy):
    name = "zhuoyao_momentum"
    display_name = "捉妖记短线强势战法"
    category = "technical"
    description = "多均线高度粘合后突然放量多头发散，捉短线妖股启动点"
    params_schema = {"adhesive_pct": 0.05}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"].values
        ma5 = pd.Series(MA(c, 5), index=res.index)
        ma10 = pd.Series(MA(c, 10), index=res.index)
        ma20 = pd.Series(MA(c, 20), index=res.index)
        
        # 均线粘合条件
        ma_max = np.maximum.reduce([ma5.values, ma10.values, ma20.values])
        ma_min = np.minimum.reduce([ma5.values, ma10.values, ma20.values])
        adhesive = pd.Series((ma_max - ma_min) / np.maximum(c, 1e-4) < float(self.params.get("adhesive_pct", 0.05)), index=res.index)
        
        # 突破发散
        ref_c1 = pd.Series(REF(c, 1), index=res.index)
        breakout = (res["close"] > ma5) & (ma5 >= ma10) & (res["close"] / ref_c1 > 1.025)
        
        buy_sig = (adhesive.shift(1).fillna(False) & breakout) | ((res["close"] > ma5) & (res["close"].shift(1) <= ma5.shift(1)) & (res["close"] > ma20))
        sell_sig = res["close"] < ma10
        
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
