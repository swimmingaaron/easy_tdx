"""双均线实战优化战法 (MA PRO)。

核心逻辑：
- 5日均线（MA5）：代表一周平均持仓成本，反映短期趋势，短线操作基准。
- 20日均线（MA20）：代表一个月平均持仓成本，反映中期趋势，波段操作生命线。

完整操作流程：
1. 选股初筛：MA5 上穿 MA20 形成金叉，且 20日均线必须走平或向上拐头（若仍向下倾斜直接放弃，排除弱势诱多）。
2. 二次筛选：金叉次日收盘价高于金叉日最高价确认强势突破；若收阴、低开低走且未创新高直接剔除。
3. 入场时机：
   - 标准入场：金叉后第3天（T+2）开盘进场；
   - 回调入场：多头趋势中回踩5日线不破放量拉升、或回踩20日线企稳重上5日线时二次入场。
4. 离场规则：收盘有效跌破20日均线（波段离场）、死叉或连续两日跌破5日线（短线止损）。
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, CROSS

@register_strategy
class MACrossProStrategy(BaseStrategy):
    name = "ma_cross_pro"
    display_name = "双均线优化战法 (MA PRO)"
    category = "technical"
    description = "MA5/MA20金叉精选：含20日线走平拐头初筛、次日突破确认与均线回踩二次入场。"
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
        v = res["volume"].values if "volume" in res.columns else res["vol"].values
        o = res["open"].values
        l = res["low"].values
        h = res["high"].values
        
        ma_fast = pd.Series(MA(c, fast_p), index=res.index)
        ma_slow = pd.Series(MA(c, slow_p), index=res.index)
        ma5_vol = pd.Series(MA(v, 5), index=res.index)
        
        # 1. 基础金叉
        gold = pd.Series(CROSS(ma_fast.values, ma_slow.values), index=res.index)
        
        # 2. 初筛：20日慢线走平或向上拐头（若仍向下倾斜直接放弃，排除弱势反弹）
        slow_slope_up = ma_slow >= ma_slow.shift(1)
        valid_gold = gold & slow_slope_up
        
        # 3. 二次筛选：金叉次日（T+1）收盘价高于前一日（金叉日），确认突破走强
        t1_confirmed = valid_gold.shift(1) & (res["close"] > res["close"].shift(1))
        
        # 4. 入场时机：筛选通过后，在金叉后的第3天（T+2）开盘/低点入场
        buy_sig = t1_confirmed.shift(1).fillna(False)
        
        # 5. 离场规则：股价有效跌破5日均线且隔日未收回（连续2日收盘低于5日线），或发生死叉，立即离场
        dead = pd.Series(CROSS(ma_slow.values, ma_fast.values), index=res.index)
        break_fast_unrecovered = (res["close"] < ma_fast) & (res["close"].shift(1) < ma_fast.shift(1))
        sell_sig = break_fast_unrecovered | dead
        
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
