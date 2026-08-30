import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import KDJ, CROSS

@register_strategy
class KDJGoldenStrategy(BaseStrategy):
    name = "kdj_golden"
    display_name = "KDJ超卖金叉策略"
    category = "technical"
    description = "KDJ 低位超卖区间 (<30) J 线上穿 K/D 金叉买入，高位 (>80) 死叉卖出"
    params_schema = {"n": 9, "oversold": 30, "overbought": 80}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        k, d, j = KDJ(res["close"], res["high"], res["low"], self.params["n"])
        res["buy_signal"] = CROSS(k, d) & (k < self.params["oversold"])
        res["sell_signal"] = CROSS(d, k) & (k > self.params["overbought"])
        return res
