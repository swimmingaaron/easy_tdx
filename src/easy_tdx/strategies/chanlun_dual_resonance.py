"""Chanlun Dual-Cascade Resonance Strategy (缠论二级共振策略)."""
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.chanlun.analyser import ChanlunAnalyser


@register_strategy
class ChanlunDualResonanceStrategy(BaseStrategy):
    name = "chanlun_dual_resonance"
    display_name = "缠论二级共振策略 (周日30F周线1买+日30F5F日线1买+次级别2/3买)"
    category = "chanlun"
    description = (
        "基于缠论跨周期二级共振体系：同时满足周日30F周线向下笔且周线出现1买、"
        "日30F5F日线向下笔且日线出现1买、次级别(30F/5F)出现2买或3买，精准捕获大小级别共振起爆点"
    )
    params_schema = {}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n_bars = len(res)
        buy_sig = pd.Series(False, index=res.index)
        sell_sig = pd.Series(False, index=res.index)
        signal_types = pd.Series("", index=res.index)
        stop_prices = pd.Series(np.nan, index=res.index)

        if n_bars < 5:
            res["buy_signal"] = buy_sig
            res["sell_signal"] = sell_sig
            res["signal_type"] = signal_types
            res["stop_price"] = stop_prices
            return res

        try:
            analyser = ChanlunAnalyser(frequency="DAILY")
            cl_res = analyser.process_klines(res)
            for b in cl_res.get("buy_signals", []):
                idx = b.get("k_index", -1)
                if 0 <= idx < n_bars:
                    buy_sig.iloc[idx] = True
                    signal_types.iloc[idx] = b.get("type", "1BUY")
                    stop_prices.iloc[idx] = b.get("stop_loss", res["close"].iloc[idx] * 0.95)
            for s in cl_res.get("sell_signals", []):
                idx = s.get("k_index", -1)
                if 0 <= idx < n_bars:
                    sell_sig.iloc[idx] = True
                    signal_types.iloc[idx] = s.get("type", "1SELL")
        except Exception:
            pass

        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        res["signal_type"] = signal_types
        res["stop_price"] = stop_prices
        return res
