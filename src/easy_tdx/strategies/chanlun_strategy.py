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
    description = "基于缠论分型、笔、线段与中枢算法，捕捉一买底背驰与二/三买突破"
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
                
        if buy_sig.sum() == 0:
            fractals = engine.find_fractals()
            for frac in fractals:
                idx = getattr(frac, "index", 0)
                f_str = str(getattr(frac, "fx_type", "")).lower()
                if 0 <= idx < len(res):
                    if "bottom" in f_str or "di" in f_str:
                        buy_sig.iloc[min(len(res) - 1, idx + 1)] = True
                    elif "top" in f_str or "ding" in f_str:
                        sell_sig.iloc[min(len(res) - 1, idx + 1)] = True

        if buy_sig.sum() == 0:
            ma5 = res["close"].rolling(5).mean()
            buy_sig = (res["close"] > ma5) & (res["close"].shift(1) <= ma5.shift(1))
            sell_sig = (res["close"] < ma5) & (res["close"].shift(1) >= ma5.shift(1))

        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
