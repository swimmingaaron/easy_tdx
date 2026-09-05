"""Watchlist persistent storage for easy_tdx."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST = [
    "000001", "600000", "002415", "601318", "300750", 
    "600519", "002594", "601899", "300059", "600036", 
    "000858", "881287"
]

def _get_run_dir() -> Path:
    """定位 run.py 所在的主工程根目录。"""
    cur = Path(__file__).resolve()
    for p in cur.parents:
        if (p / "run.py").is_file():
            return p
    cwd = Path.cwd().resolve()
    if (cwd / "run.py").is_file():
        return cwd
    # 默认回退到 easy_tdx 仓库根目录 (src/easy_tdx 的上两级)
    return cur.parents[2]


def _get_watchlist_paths() -> list[Path]:
    paths = []
    # 1. run.py 同目录下 (最高优先级)
    run_file = _get_run_dir() / "watchlist.json"
    paths.append(run_file)
    # 2. Config dir ~/.easy_tdx/watchlist.json
    cfg_dir = Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))
    paths.append(cfg_dir / "watchlist.json")
    return paths


_lock = threading.Lock()


def load_watchlist() -> list[str]:
    """Load persisted watchlist from disk, falling back to defaults if not found."""
    with _lock:
        for p in _get_watchlist_paths():
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list) and len(data) > 0:
                            clean = [str(s).strip() for s in data if str(s).strip()]
                            if clean:
                                return clean
                except Exception as e:
                    logger.warning(f"Failed to read watchlist from {p}: {e}")
        return list(DEFAULT_WATCHLIST)

def save_watchlist(symbols: list[str]) -> list[str]:
    """Persist watchlist symbols to all configuration paths."""
    clean = []
    seen = set()
    for s in symbols:
        sym = str(s).strip()
        if sym and sym not in seen:
            seen.add(sym)
            clean.append(sym)
            
    if not clean:
        clean = list(DEFAULT_WATCHLIST)
    
    with _lock:
        for p in _get_watchlist_paths():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(clean, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save watchlist to {p}: {e}")
    return clean

def reset_watchlist() -> list[str]:
    """Reset watchlist to factory default and persist to disk."""
    return save_watchlist(DEFAULT_WATCHLIST)
