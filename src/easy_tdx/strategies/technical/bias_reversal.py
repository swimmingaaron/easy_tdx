"""乖离率反转策略。

6 日乖离率低于 -3%（超跌）买入，高于 3%（超涨）卖出。
严格参考 easy_tdx/strategies/bias_reversal.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import BIAS

@register_strategy
class BiasReversalStrategy(BaseStrategy):
    name = "bias_reversal"
    display_name = "乖离率反转策略 (BIAS)"
    category = "technical"
    description = "6 日乖离率低于超跌阈值（默认 -3%）买入，高于超涨阈值（默认 +3%）卖出。适合震荡市。"
    params_list = [
        Param("period", int, default=6, min_value=2, max_value=30, step=1, label="BIAS 周期 (6)", description="计算乖离率的时间周期"),
        Param("buy_threshold", float, default=-3.0, min_value=-20.0, max_value=0.0, step=0.5, label="超跌买入阈值(%)", description="当 BIAS 低于该值时触发超跌买入"),
        Param("sell_threshold", float, default=3.0, min_value=0.0, max_value=20.0, step=0.5, label="超涨卖出阈值(%)", description="当 BIAS 高于该值时触发超涨卖出"),
    ]
    params_schema = {"period": 6, "buy_threshold": -3.0, "sell_threshold": 3.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        p = int(self.params.get("period", 6))
        buy_th = float(self.params.get("buy_threshold", -3.0))
        sell_th = float(self.params.get("sell_threshold", 3.0))
        
        bias6, _, _ = BIAS(res["close"], p)
        res["buy_signal"] = bias6 < buy_th
        res["sell_signal"] = bias6 > sell_th
        return res
