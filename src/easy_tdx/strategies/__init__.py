import importlib
import pkgutil
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import STRATEGY_REGISTRY, get_strategy, list_all_strategies

# Auto-import all strategy submodules
for pkg in ["technical", "pattern", "short_term", "alpha_quant", "daily_analysis"]:
    pkg_path = f"easy_tdx.strategies.{pkg}"
    try:
        module = importlib.import_module(pkg_path)
        for _, modname, _ in pkgutil.walk_packages(module.__path__, f"{pkg_path}."):
            importlib.import_module(modname)
    except Exception:
        pass

# Import chanlun strategy
try:
    import easy_tdx.strategies.chanlun_strategy
except Exception:
    pass

__all__ = ["BaseStrategy", "STRATEGY_REGISTRY", "get_strategy", "list_all_strategies"]
