"""CCI 区间突破策略。

CCI 上穿 +100 时买入（进入强势区间）；下穿 -100 时卖出（进入弱势区间）。
严格参考 easy_tdx/strategies/cci_breakout.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import CCI

@register_strategy
class CCIBreakoutStrategy(BaseStrategy):
    name = "cci_breakout"
    display_name = "CCI区间突破策略"
    category = "technical"
    description = "CCI 上穿 +100（进入强势区）顺势买入；下穿 -100（弱势区）卖出。"
    params_list = [
        Param("period", int, default=14, min_value=5, max_value=60, step=1, label="CCI 周期 (14)", description="顺势指标的统计周期"),
        Param("buy_threshold", float, default=100.0, min_value=50.0, max_value=200.0, step=5.0, label="强势突破买入阈值 (+100)", description="CCI 突破此阈值代表进入强势拉升区"),
        Param("sell_threshold", float, default=-100.0, min_value=-200.0, max_value=-50.0, step=5.0, label="弱势跌破卖出阈值 (-100)", description="CCI 跌破此阈值代表进入弱势区间"),
    ]
    params_schema = {"period": 14, "buy_threshold": 100.0, "sell_threshold": -100.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        p = int(self.params.get("period", 14))
        buy_th = float(self.params.get("buy_threshold", 100.0))
        sell_th = float(self.params.get("sell_threshold", -100.0))
        
        cci = CCI(res["close"], res["high"], res["low"], p)
        res["buy_signal"] = cci > buy_th
        res["sell_signal"] = cci < sell_th
        return res
