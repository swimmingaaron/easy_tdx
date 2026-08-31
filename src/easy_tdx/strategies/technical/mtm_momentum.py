"""MTM 动量策略。

MTM 上穿 0 买入（动量由负转正，下跌动能耗尽）；MTM 下穿 0 卖出（动量由正转负）。
严格参考 easy_tdx/strategies/mtm_momentum.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MTM, CROSS

@register_strategy
class MTMMomentumStrategy(BaseStrategy):
    name = "mtm_momentum"
    display_name = "MTM动量策略"
    category = "technical"
    description = "MTM 上穿 0 轴买入（动量转正），下穿 0 轴卖出（动量转负）。"
    params_list = [
        Param("n", int, default=12, min_value=2, max_value=60, step=1, label="动量计算周期 (12)", description="当前价与 N 日前价格差的周期"),
        Param("m", int, default=6, min_value=1, max_value=30, step=1, label="MTMMA 均线周期 (6)", description="动量平均线周期"),
    ]
    params_schema = {"n": 12, "m": 6}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n = int(self.params.get("n", 12))
        m = int(self.params.get("m", 6))
        
        mtm, mtm_ma = MTM(res["close"], n, m)
        res["buy_signal"] = CROSS(mtm, 0.0)
        res["sell_signal"] = CROSS(0.0, mtm)
        return res
