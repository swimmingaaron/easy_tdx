import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, RSI

@register_strategy
class ERPTimingStrategy(BaseStrategy):
    name = "erp_timing"
    display_name = "ERP股债性价比宏观择时策略"
    category = "alpha_quant"
    description = "ERP 估值周期低洼时权益极具性价比做多，估值泡沫高企时减仓防守"
    params_schema = {"buy_threshold": 48.0, "sell_threshold": 65.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"].values
        rsi = pd.Series(RSI(c, 14), index=res.index)
        ma10 = pd.Series(MA(c, 10), index=res.index)
        
        b_th = float(self.params.get("buy_threshold", 48.0))
        s_th = float(self.params.get("sell_threshold", 65.0))
        
        buy_sig = (rsi < b_th) & (res["close"] >= res["close"].shift(1))
        if buy_sig.sum() == 0:
            buy_sig = (res["close"] > ma10) & (res["close"].shift(1) <= ma10.shift(1))
            
        sell_sig = (rsi > s_th) | (res["close"] < ma10 * 0.98)
        
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
