"""双均线交叉策略。

MA5 上穿 MA20（金叉）全仓买入，MA5 下穿 MA20（死叉）全部卖出。
严格参考 easy_tdx/strategies/ma_cross.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, CROSS

@register_strategy
class MACrossStrategy(BaseStrategy):
    name = "ma_cross"
    display_name = "双均线交叉策略 (MA)"
    category = "technical"
    description = "快线上穿慢线金叉买入，快线下穿慢线死叉卖出。经典趋势跟踪策略。"
    params_list = [
        Param("fast_period", int, default=5, min_value=1, max_value=60, step=1, label="快线周期 (MA5)", description="短期移动平均线周期，通常为 5 日"),
        Param("slow_period", int, default=20, min_value=5, max_value=250, step=1, label="慢线周期 (MA20)", description="长期移动平均线周期，通常为 20 日"),
    ]
    params_schema = {"fast_period": 5, "slow_period": 20}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        fast_p = int(self.params.get("fast_period", 5))
        slow_p = int(self.params.get("slow_period", 20))
        c = res["close"].values
        
        ma_fast = pd.Series(MA(c, fast_p), index=res.index)
        ma_slow = pd.Series(MA(c, slow_p), index=res.index)
        
        # 1. 基础金叉 + 20日线走平/向上拐头初筛
        gold = pd.Series(CROSS(ma_fast.values, ma_slow.values), index=res.index)
        slow_slope_up = ma_slow >= ma_slow.shift(1)
        valid_gold = gold & slow_slope_up
        
        # 2. 金叉次日（T+1）收盘价高于前一日（金叉日），走强确认
        t1_confirmed = valid_gold.shift(1) & (res["close"] > res["close"].shift(1))
        
        # 3. 第3日（T+2）入场买入
        res["buy_signal"] = t1_confirmed.shift(1).fillna(False)
        
        # 4. 卖出：有效跌破5日均线且隔日未收回（连续2日低于5日线），或死叉离场
        dead = pd.Series(CROSS(ma_slow.values, ma_fast.values), index=res.index)
        break_fast_unrecovered = (res["close"] < ma_fast) & (res["close"].shift(1) < ma_fast.shift(1))
        res["sell_signal"] = (break_fast_unrecovered | dead).fillna(False)
        return res
