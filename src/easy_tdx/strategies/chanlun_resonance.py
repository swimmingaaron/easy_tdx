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
        "缠论三级共振策略体系：支持三大核心共振周期（1. 季月周共振：季月多头共振筛选周线2买/3买；"
        "2. 月周日共振：月周多头共振筛选日线2买/3买；3. 周日30F共振：周日多头共振筛选30F 2买/3买），"
        "以及全级别三级联共振，锁定高确定性主升浪进场点"
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
