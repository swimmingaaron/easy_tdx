"""Chanlun Engine compatibility wrapper."""
from __future__ import annotations
from typing import Any
import pandas as pd
from easy_tdx.chanlun.analyser import ChanlunAnalyser
from easy_tdx.chanlun.types import FXType, Direction

class SimpleFractal:
    def __init__(self, index: int, fx_type: FXType):
        self.index = index
        self.fx_type = fx_type
        self.type = fx_type

class ChanlunEngine:
    """Wrapper around ChanlunAnalyser to provide unified buy/sell points & fractals."""
    
    def __init__(self, df: pd.DataFrame, symbol: str = "000001", period: str = "DAILY"):
        self.df = df
        self.symbol = symbol
        self.period = period
        self.analyser = ChanlunAnalyser(symbol, period)

    def find_fractals(self) -> list[SimpleFractal]:
        fractals: list[SimpleFractal] = []
        if len(self.df) < 5:
            return fractals
            
        lows = self.df["low"].values
        highs = self.df["high"].values
        n = len(self.df)
        for i in range(2, n - 2):
            if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] and lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
                fractals.append(SimpleFractal(i, FXType.BOTTOM))
            elif highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
                fractals.append(SimpleFractal(i, FXType.TOP))
        return fractals

    def find_buy_sell_points(self) -> dict[str, list[int]]:
        points: dict[str, list[int]] = {
            "buy_1": [],
            "buy_2": [],
            "buy_3": [],
            "sell_1": [],
            "sell_2": [],
            "sell_3": []
        }
        if self.df.empty:
            return points
            
        try:
            res = self.analyser.process_klines(self.df)
            n_bars = len(self.df)
            for mmd in res.mmds:
                mtype = mmd.mmd_type.value if hasattr(mmd, "mmd_type") else str(getattr(mmd, "type", "")).lower()
                idx = None
                if mmd.bi and mmd.bi.end and mmd.bi.end.k:
                    idx = mmd.bi.end.k.k_index
                    if hasattr(mmd.bi.end.k, "klines") and mmd.bi.end.k.klines:
                        is_end_high = (mmd.bi.end.fx_type == FXType.DING)
                        for raw_k in mmd.bi.end.k.klines:
                            raw_target = raw_k.high if is_end_high else raw_k.low
                            if abs(raw_target - mmd.bi.end.val) < 1e-4:
                                idx = raw_k.index
                                break
                if idx is None or idx < 0 or idx >= n_bars:
                    continue

                if "1buy" in mtype or "buy_1" in mtype:
                    points["buy_1"].append(idx)
                elif "2buy" in mtype or "buy_2" in mtype:
                    points["buy_2"].append(idx)
                elif "3buy" in mtype or "buy_3" in mtype:
                    points["buy_3"].append(idx)
                elif "1sell" in mtype or "sell_1" in mtype:
                    points["sell_1"].append(idx)
                elif "2sell" in mtype or "sell_2" in mtype:
                    points["sell_2"].append(idx)
                elif "3sell" in mtype or "sell_3" in mtype:
                    points["sell_3"].append(idx)
        except Exception:
            pass
                    
        return points

__all__ = ["ChanlunEngine", "FXType", "Direction"]
