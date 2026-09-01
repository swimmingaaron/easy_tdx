"""MA Golden Cross Strategy (均线金叉策略)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class MAGoldenCrossDailyStrategy(BaseStrategy):
    name = "ma_golden_cross_daily"
    display_name = "均线多周期金叉"
    category = "daily_analysis"
    description = "MA5 上穿 MA10 形成黄金交叉，伴随量能放大确认买点"
    params_schema = {"fast_period": 5, "slow_period": 10}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        fast = pd.Series(MA(out["close"].values, self.params.get("fast_period", 5)), index=out.index)
        slow = pd.Series(MA(out["close"].values, self.params.get("slow_period", 10)), index=out.index)

        # 金叉判定
        golden_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        # 死叉判定
        death_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))

        out["buy_signal"] = golden_cross
        out["sell_signal"] = death_cross
        return out
