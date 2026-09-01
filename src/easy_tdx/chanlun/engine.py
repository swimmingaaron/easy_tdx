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
            for mmd in res.mmds:
                mtype = getattr(mmd, "type", "")
                idx = getattr(mmd, "kline_idx", None)
                if idx is None:
                    continue
                if "1B" in str(mtype) or "BUY_1" in str(mtype):
                    points["buy_1"].append(idx)
                elif "2B" in str(mtype) or "BUY_2" in str(mtype):
                    points["buy_2"].append(idx)
                elif "3B" in str(mtype) or "BUY_3" in str(mtype):
                    points["buy_3"].append(idx)
                elif "1S" in str(mtype) or "SELL_1" in str(mtype):
                    points["sell_1"].append(idx)
                elif "2S" in str(mtype) or "SELL_2" in str(mtype):
                    points["sell_2"].append(idx)
                elif "3S" in str(mtype) or "SELL_3" in str(mtype):
                    points["sell_3"].append(idx)
        except Exception:
            for frac in self.find_fractals():
                if frac.fx_type == FXType.BOTTOM:
                    points["buy_1"].append(frac.index)
                else:
                    points["sell_1"].append(frac.index)
                    
        return points

__all__ = ["ChanlunEngine", "FXType", "Direction"]
