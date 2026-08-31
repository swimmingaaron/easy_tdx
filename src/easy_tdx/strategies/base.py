"""Unified Strategy Base Class supporting Vectorized Screening & Event Backtesting."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Any, Type
import pandas as pd
import numpy as np

@dataclass(frozen=True)
class Param:
    """Strategy Parameter Definition Schema."""
    name: str
    type: type
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    label: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": "int" if self.type is int else "float" if self.type is float else "str",
            "default": self.default,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "step": self.step if self.step is not None else (1 if self.type is int else 0.1),
            "label": self.label or self.name,
            "description": self.description,
        }

class BaseStrategy(ABC):
    """Abstract Base Strategy."""
    name: ClassVar[str] = "base_strategy"
    display_name: ClassVar[str] = "基础策略"
    category: ClassVar[str] = "technical"
    description: ClassVar[str] = ""
    params_schema: ClassVar[dict[str, Any]] = {}
    params_list: ClassVar[list[Param]] = []
    
    def __init__(self, **params):
        defaults = {}
        if self.params_list:
            defaults = {p.name: p.default for p in self.params_list}
        elif self.params_schema:
            defaults = self.params_schema.copy()
        self.params = {**defaults, **params}

    @classmethod
    def get_params_schema(cls) -> list[dict[str, Any]]:
        if cls.params_list:
            return [p.to_dict() for p in cls.params_list]
        if cls.params_schema:
            return [
                {
                    "name": k,
                    "type": type(v).__name__,
                    "default": v,
                    "min_value": None,
                    "max_value": None,
                    "step": 1 if isinstance(v, int) else 0.1,
                    "label": k,
                    "description": "",
                }
                for k, v in cls.params_schema.items()
            ]
        return []
        
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate buy/sell signals for a given OHLCV DataFrame.
        Must return df with boolean columns: 'buy_signal' and 'sell_signal'.
        """
        pass
