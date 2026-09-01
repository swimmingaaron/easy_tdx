"""Base Agent class for Multi-Agent Quant System."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
import pandas as pd

class BaseAgent(ABC):
    """Abstract Base Class for domain-specific quant intelligence agents."""
    agent_name: str = "base_agent"
    role_description: str = "Base Quantitative Agent"

    @abstractmethod
    def analyze(self, symbol: str, kline_df: pd.DataFrame, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform agent analysis and return structured evaluation dictionary."""
        raise NotImplementedError
