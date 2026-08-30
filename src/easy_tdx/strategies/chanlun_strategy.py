import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.chanlun.engine import ChanlunEngine

@register_strategy
class ChanlunBuySellStrategy(BaseStrategy):
    name = "chanlun_strategy"
    display_name = "缠论1/2/3类买卖点与笔背驰策略"
    category = "chanlun"
    description = "基于缠论分型、笔、线段与中枢算法，捕捉一买底背驰与二/三买突破"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        engine = ChanlunEngine(res)
        pts = engine.find_buy_sell_points()
        
        buy_sig = pd.Series(False, index=res.index)
        sell_sig = pd.Series(False, index=res.index)
        
        for b_idx in pts.get("buy_1", []) + pts.get("buy_2", []) + pts.get("buy_3", []):
            if b_idx < len(buy_sig):
                buy_sig.iloc[b_idx] = True
                
        for s_idx in pts.get("sell_1", []) + pts.get("sell_2", []):
            if s_idx < len(sell_sig):
                sell_sig.iloc[s_idx] = True
                
        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        return res
