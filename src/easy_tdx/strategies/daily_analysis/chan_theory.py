"""Chan Theory Strategy (缠论顶底分型笔与三类买卖点)."""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.chanlun.engine import ChanlunEngine, FXType

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
            if 0 <= idx < len(out):
                if f_type == FXType.BOTTOM or str(f_type) == "bottom" or str(f_type) == "FXType.BOTTOM":
                    if idx + 1 < len(out):
                        buy_sig.iloc[idx + 1] = True
                    else:
                        buy_sig.iloc[idx] = True
                elif f_type == FXType.TOP or str(f_type) == "top" or str(f_type) == "FXType.TOP":
                    if idx + 1 < len(out):
                        sell_sig.iloc[idx + 1] = True
                    else:
                        sell_sig.iloc[idx] = True

        out["buy_signal"] = buy_sig
        out["sell_signal"] = sell_sig
        return out
