"""MACD 金叉死叉策略。

DIF 上穿 DEA（金叉）买入，DIF 下穿 DEA（死叉）卖出。
严格参考 easy_tdx/strategies/macd_cross.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MACD, CROSS

@register_strategy
class MACDCrossStrategy(BaseStrategy):
    name = "macd_cross"
    display_name = "MACD金叉死叉策略"
    category = "technical"
    description = "DIF 上穿 DEA 金叉买入，DIF 下穿 DEA 死叉卖出。"
    params_list = [
        Param("short", int, default=12, min_value=2, max_value=50, step=1, label="短期EMA周期 (12)", description="短期指数移动平均周期"),
        Param("long", int, default=26, min_value=5, max_value=100, step=1, label="长期EMA周期 (26)", description="长期指数移动平均周期"),
        Param("mid", int, default=9, min_value=2, max_value=50, step=1, label="信号平滑周期 (9)", description="DIF 的移动平均 DEA 周期"),
    ]
    params_schema = {"short": 12, "long": 26, "mid": 9}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        short_p = int(self.params.get("short", 12))
        long_p = int(self.params.get("long", 26))
        mid_p = int(self.params.get("mid", 9))
        
        dif, dea, hist = MACD(res["close"], short_p, long_p, mid_p)
        res["buy_signal"] = CROSS(dif, dea)
        res["sell_signal"] = CROSS(dea, dif)
        return res
