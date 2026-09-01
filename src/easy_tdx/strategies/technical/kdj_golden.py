"""KDJ 金叉策略。

K 上穿 D 且 J < 20（低位金叉）买入，K 下穿 D 且 J > 80（高位死叉）卖出。
严格参考 easy_tdx/strategies/kdj_golden.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import KDJ, CROSS

@register_strategy
class KDJGoldenStrategy(BaseStrategy):
    name = "kdj_golden"
    display_name = "KDJ金叉策略"
    category = "technical"
    description = "K 上穿 D 且 J < 20（低位金叉）买入，K 下穿 D 且 J > 80（高位死叉）卖出。"
    params_list = [
        Param("n", int, default=9, min_value=2, max_value=30, step=1, label="RSV 计算周期 (9)", description="未成熟随机值周期"),
        Param("m1", int, default=3, min_value=1, max_value=10, step=1, label="K 平滑周期 (3)", description="K 线移动平均周期"),
        Param("m2", int, default=3, min_value=1, max_value=10, step=1, label="D 平滑周期 (3)", description="D 线移动平均周期"),
        Param("j_low", float, default=20.0, min_value=0.0, max_value=40.0, step=1.0, label="J 线超卖低位阈值 (20)", description="金叉时 J 线需低于此值方可入场"),
        Param("j_high", float, default=80.0, min_value=60.0, max_value=100.0, step=1.0, label="J 线超买高位阈值 (80)", description="死叉时 J 线高于此值触发止盈"),
    ]
    params_schema = {"n": 9, "m1": 3, "m2": 3, "j_low": 20.0, "j_high": 80.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n = int(self.params.get("n", 9))
        m1 = int(self.params.get("m1", 3))
        m2 = int(self.params.get("m2", 3))
        j_low = float(self.params.get("j_low", 20.0))
        j_high = float(self.params.get("j_high", 80.0))
        
        k, d, j = KDJ(res["close"], res["high"], res["low"], n, m1, m2)
        res["buy_signal"] = CROSS(k, d) & (j < j_low)
        res["sell_signal"] = CROSS(d, k) & (j > j_high)
        return res
