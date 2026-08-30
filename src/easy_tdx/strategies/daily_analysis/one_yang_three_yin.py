"""One Yang Engulfs Three Yin Strategy (一阳穿三阴/洗盘反包)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class OneYangThreeYinStrategy(BaseStrategy):
    name = "one_yang_three_yin"
    display_name = "一阳穿三阴洗盘反包"
    category = "daily_analysis"
    description = "前期连续 2~3 日小阴线缩量洗盘后，当日一根放量大阳线吞没前几日实体"
    params_schema = {"min_yang_pct": 3.5}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        is_yin = out["close"] < out["open"]
        # 前两日均为阴线
        prior_yins = is_yin.shift(1) & is_yin.shift(2)
        # 当日大阳线
        is_big_yang = (out["close"] > out["open"]) & ((out["close"] - out["open"]) / out["open"] * 100 >= self.params.get("min_yang_pct", 3.5))
        # 吞没前两日最高价
        engulf = out["close"] > out["high"].shift(1)

        out["buy_signal"] = prior_yins & is_big_yang & engulf
        out["sell_signal"] = out["close"] < out["open"]
        return out
