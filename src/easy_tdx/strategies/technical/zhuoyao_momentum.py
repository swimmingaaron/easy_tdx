"""捉妖大师多周期共振策略。

基于 ZHUOYAO 指标（20/60/120 日涨幅及指数平滑），通过短中长线趋势共振判断买卖时机。
入场条件（三条件全部满足）：
  1. SHORT > 0  — 20 日涨幅为正，短线处于强势
  2. TREND > 0  — 60 日涨幅的 EMA 为正，中期趋势向上
  3. SHORT > MID — 短线强于中线，处于加速阶段（非衰竭）
出场条件（任一触发即卖出）：
  1. SHORT < 0  — 短线转弱
  2. TREND < 0  — 中期趋势转向
严格参考 easy_tdx/strategies/zhuoyao_momentum.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import ZHUOYAO

@register_strategy
class ZhuoyaoStrategy(BaseStrategy):
    name = "zhuoyao_momentum"
    display_name = "捉妖大师多周期共振策略"
    category = "technical"
    description = "基于 ZHUOYAO 指标：SHORT>0 且 TREND>0 且 SHORT>MID 买入；SHORT<0 或 TREND<0 卖出。"
    params_list = [
        Param("n1", int, default=120, min_value=30, max_value=250, step=5, label="长线涨幅周期 (120)", description="长线趋势周期"),
        Param("n2", int, default=60, min_value=15, max_value=120, step=5, label="中线涨幅周期 (60)", description="中线趋势周期"),
        Param("n3", int, default=20, min_value=5, max_value=60, step=1, label="短线涨幅周期 (20)", description="短线加速周期"),
        Param("m", int, default=10, min_value=2, max_value=30, step=1, label="趋势 EMA 平滑周期 (10)", description="趋势平滑指数周期"),
    ]
    params_schema = {"n1": 120, "n2": 60, "n3": 20, "m": 10}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n1 = int(self.params.get("n1", 120))
        n2 = int(self.params.get("n2", 60))
        n3 = int(self.params.get("n3", 20))
        m = int(self.params.get("m", 10))
        
        long_arr, mid_arr, short_arr, trend_arr = ZHUOYAO(res["close"], n1, n2, n3, m)
        short = pd.Series(short_arr, index=res.index)
        mid = pd.Series(mid_arr, index=res.index)
        trend = pd.Series(trend_arr, index=res.index)
        
        res["buy_signal"] = (short > 0) & (trend > 0) & (short > mid)
        res["sell_signal"] = (short < 0) | (trend < 0)
        return res
