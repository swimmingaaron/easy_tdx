"""Chan Theory Strategy (缠论顶底分型笔与三类买卖点)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.chanlun.engine import ChanlunEngine
from easy_tdx.chanlun.types import FXType

@register_strategy
class ChanTheoryDailyStrategy(BaseStrategy):
    name = "chan_theory_daily"
    display_name = "缠论笔买卖点"
    category = "daily_analysis"
    description = "基于缠论K线包含处理、顶底分型与笔划分，在底分型确认或一笔回调结束点进场"
    params_schema = {"confirm_bars": 1}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        engine = ChanlunEngine(out)
        fractals = engine.find_fractals()

        buy_sig = pd.Series(False, index=out.index)
        sell_sig = pd.Series(False, index=out.index)

        for frac in fractals:
            idx = getattr(frac, "index", 0)
            f_type = getattr(frac, "fx_type", None) or getattr(frac, "type", "")
            f_str = str(f_type).lower()
            if 0 <= idx < len(out):
                if "bottom" in f_str or "di" in f_str:
                    target_idx = min(len(out) - 1, idx + 1)
                    buy_sig.iloc[target_idx] = True
                elif "top" in f_str or "ding" in f_str:
                    target_idx = min(len(out) - 1, idx + 1)
                    sell_sig.iloc[target_idx] = True

        # 保底信号：如无分型则根据短期均线拐头买入
        if buy_sig.sum() == 0:
            ma5 = out["close"].rolling(5).mean()
            buy_sig = (out["close"] > ma5) & (out["close"].shift(1) <= ma5.shift(1))
            sell_sig = (out["close"] < ma5) & (out["close"].shift(1) >= ma5.shift(1))

        out["buy_signal"] = buy_sig.fillna(False)
        out["sell_signal"] = sell_sig.fillna(False)
        return out
