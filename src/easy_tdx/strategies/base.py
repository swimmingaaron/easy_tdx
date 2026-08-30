"""Unified Strategy Base Class supporting Vectorized Screening & Event Backtesting."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import ClassVar, Any, Type
import pandas as pd
import numpy as np

class BaseStrategy(ABC):
    """Abstract Base Strategy."""
    name: ClassVar[str] = "base_strategy"
    display_name: ClassVar[str] = "基础策略"
    category: ClassVar[str] = "technical"
    description: ClassVar[str] = ""
    params_schema: ClassVar[dict[str, Any]] = {}
    
    def __init__(self, **params):
        self.params = {**self.params_schema, **params}
        
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals for a given OHLCV DataFrame.
        Must return df with boolean columns: 'buy_signal' and 'sell_signal'.
        """
        pass
