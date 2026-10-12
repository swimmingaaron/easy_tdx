import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.chanlun.engine import ChanlunEngine

@register_strategy
class ChanlunBuySellStrategy(BaseStrategy):
    name = "chanlun_strategy"
    display_name = "缠论1/2/3类买卖点与笔背驰策略"
    category = "chanlun"
    description = "以【日线 30F 5F】区间套为大中小周期，筛选出最近最后大周期为大级别买点(大级别1买/2买/3买)的优质标的"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        engine = ChanlunEngine(res)
        pts = engine.find_buy_sell_points()
        
        buy_sig = pd.Series(False, index=res.index)
        sell_sig = pd.Series(False, index=res.index)
        
        for b_idx in pts.get("buy_1", []) + pts.get("buy_2", []) + pts.get("buy_3", []):
            if 0 <= b_idx < len(buy_sig):
                buy_sig.iloc[b_idx] = True
                
        for s_idx in pts.get("sell_1", []) + pts.get("sell_2", []) + pts.get("sell_3", []):
            if 0 <= s_idx < len(sell_sig):
                sell_sig.iloc[s_idx] = True
                
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
