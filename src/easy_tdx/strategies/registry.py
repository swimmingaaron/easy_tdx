"""Global Strategy Registry and Discovery Hub."""
from __future__ import annotations
from typing import Type, Any
from easy_tdx.strategies.base import BaseStrategy

STRATEGY_REGISTRY: dict[str, Type[BaseStrategy]] = {}

def register_strategy(cls: Type[BaseStrategy]) -> Type[BaseStrategy]:
    if cls.name != "base_strategy":
        STRATEGY_REGISTRY[cls.name] = cls
    return cls

def get_strategy(name: str, **kwargs) -> BaseStrategy:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY.keys())}")
    return STRATEGY_REGISTRY[name](**kwargs)

def list_all_strategies() -> list[dict[str, Any]]:
    return [
        {
            "name": cls.name,
            "display_name": cls.display_name,
            "category": cls.category,
            "description": cls.description,
            "params_schema": cls.params_schema,
        }
        for cls in STRATEGY_REGISTRY.values()
    ]

list_strategies = list_all_strategies
