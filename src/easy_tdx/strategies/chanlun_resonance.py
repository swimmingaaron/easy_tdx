"""Chanlun Multi-Tier Cascade Resonance Strategy (缠论共振策略)."""
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.chanlun.analyser import ChanlunAnalyser


@register_strategy
class ChanlunResonanceStrategy(BaseStrategy):
    name = "chanlun_resonance"
    display_name = "缠论共振策略 (三级联共振)"
    category = "chanlun"
    description = (
        "基于缠论多级别区间套与买卖点共振体系：同时满足月周日大买+月线升势+日线1买、"
        "周日30M大买+周线升势+30M1买、日30M5F大买+5M2买，精准捕捉大级别转折与次级别精确进场点"
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
                    signal_types.iloc[idx] = b.get("type", "2BUY")
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
