"""Daily Stock Analysis Strategies Package."""
import importlib
import pkgutil

# Dynamically import all strategy modules in this package
for _, modname, _ in pkgutil.walk_packages(__path__, f"{__name__}."):
    if not modname.endswith(".specs"):
        try:
            importlib.import_module(modname)
        except Exception:
            pass
