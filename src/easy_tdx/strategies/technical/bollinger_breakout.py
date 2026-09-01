"""布林带突破策略。

收盘价跌破下轨买入，突破上轨卖出。
严格参考 easy_tdx/strategies/bollinger_breakout.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import BOLL

@register_strategy
class BollingerBreakoutStrategy(BaseStrategy):
    name = "bollinger_breakout"
    display_name = "布林带突破策略 (BOLL)"
    category = "technical"
    description = "收盘价跌破下轨买入（超跌反弹），突破上轨卖出。"
    params_list = [
        Param("period", int, default=20, min_value=5, max_value=100, step=1, label="布林带周期 (20)", description="计算中轨均线与标准差的时间周期"),
        Param("std_mult", float, default=2.0, min_value=0.5, max_value=4.0, step=0.1, label="标准差倍数 (2.0)", description="上下轨距离中轨的标准差倍数"),
    ]
    params_schema = {"period": 20, "std_mult": 2.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        p = int(self.params.get("period", 20))
        std_m = float(self.params.get("std_mult", 2.0))
        upper, mid, lower = BOLL(res["close"], p, std_m)
        res["buy_signal"] = res["close"] <= lower
        res["sell_signal"] = res["close"] >= upper
        return res
