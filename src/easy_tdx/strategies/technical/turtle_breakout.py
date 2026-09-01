"""海龟交易法（唐安奇通道）策略。

价格突破 N 日最高价买入，跌破 N 日最低价卖出。
严格参考 easy_tdx/strategies/turtle_breakout.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import TAQ

@register_strategy
class TurtleBreakoutStrategy(BaseStrategy):
    name = "turtle_breakout"
    display_name = "海龟交易法（唐安奇通道突破）策略"
    category = "technical"
    description = "价格突破 20 日最高价（唐安奇上轨）买入，跌破 20 日最低价（唐安奇下轨）卖出。"
    params_list = [
        Param("period", int, default=20, min_value=5, max_value=120, step=1, label="唐安奇通道周期 (20)", description="通道最高价/最低价的统计周期"),
    ]
    params_schema = {"period": 20}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        p = int(self.params.get("period", 20))
        upper, _, lower = TAQ(res["high"], res["low"], p)
        res["buy_signal"] = res["close"] >= upper
        res["sell_signal"] = res["close"] <= lower
        return res
