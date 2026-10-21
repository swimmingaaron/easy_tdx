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
    strategies = [
        {
            "name": cls.name,
            "display_name": cls.display_name,
            "category": cls.category,
            "description": cls.description,
            "params_schema": cls.params_schema,
            "params": cls.get_params_schema() if hasattr(cls, "get_params_schema") else [],
        }
        for cls in STRATEGY_REGISTRY.values()
    ]
    # 置顶 chanlun_resonance (缠论共振策略) 为系统默认首选策略，其次为 chanlun_strategy
    priority_order = {"chanlun_resonance": 0, "chanlun_strategy": 1}
    strategies.sort(key=lambda s: (priority_order.get(s["name"], 99), s.get("category", ""), s["name"]))
    return strategies

list_strategies = list_all_strategies
