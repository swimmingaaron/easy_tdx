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
    """Load persisted watchlist from disk as stock code strings, falling back to defaults if not found."""
    with _lock:
        for p in _get_watchlist_paths():
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list) and len(data) > 0:
                            clean = []
                            for s in data:
                                if isinstance(s, dict):
                                    c = str(s.get("code") or s.get("symbol") or "").strip()
                                    if c:
                                        clean.append(c)
                                elif isinstance(s, str) and s.strip():
                                    clean.append(s.strip())
                            if clean:
                                return clean
                except Exception as e:
                    logger.warning(f"Failed to read watchlist from {p}: {e}")
        return list(DEFAULT_WATCHLIST)


def load_watchlist_items() -> list[dict[str, str]]:
    """Load persisted watchlist items with code and name from disk."""
    from easy_tdx.stock_lookup import get_stock_name
    with _lock:
        for p in _get_watchlist_paths():
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list) and len(data) > 0:
                            items = []
                            seen = set()
                            for s in data:
                                if isinstance(s, dict):
                                    c = str(s.get("code") or s.get("symbol") or "").strip()
                                    n = str(s.get("name") or "").strip()
                                    if not n or n.startswith("标的_"):
                                        n = get_stock_name(c) or n
                                    if c and c not in seen:
                                        seen.add(c)
                                        items.append({"code": c, "name": n or get_stock_name(c) or c})
                                elif isinstance(s, str) and s.strip():
                                    c = s.strip()
                                    if c not in seen:
                                        seen.add(c)
                                        items.append({"code": c, "name": get_stock_name(c) or c})
                            if items:
                                return items
                except Exception as e:
                    logger.warning(f"Failed to read watchlist from {p}: {e}")
        from easy_tdx.stock_lookup import get_stock_name
        return [{"code": c, "name": get_stock_name(c) or c} for c in DEFAULT_WATCHLIST]


def save_watchlist(symbols: list[Any], allow_empty: bool = False) -> list[str]:
    """Persist watchlist symbols and names to all configuration paths."""
    from easy_tdx.stock_lookup import get_stock_name
    items = []
    clean_codes = []
    seen = set()
    for s in symbols:
        if isinstance(s, dict):
            sym = str(s.get("code") or s.get("symbol") or "").strip()
            name = str(s.get("name") or "").strip()
        else:
            sym = str(s).strip()
            name = ""
        if sym and sym not in seen:
            seen.add(sym)
            clean_codes.append(sym)
            if not name or name.startswith("标的_"):
                name = get_stock_name(sym) or sym
            items.append({"code": sym, "name": name})

    if not items and not allow_empty:
        for c in DEFAULT_WATCHLIST:
            clean_codes.append(c)
            items.append({"code": c, "name": get_stock_name(c) or c})

    with _lock:
        for p in _get_watchlist_paths():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save watchlist to {p}: {e}")
    return clean_codes


def reset_watchlist() -> list[str]:
    """Reset watchlist to factory default and persist to disk."""
    return save_watchlist(DEFAULT_WATCHLIST)


def parse_watchlist_data(raw_data: Any) -> list[dict[str, str]]:
    """将任意输入（文件路径、JSON字符串、字典列表、字符串列表）解析为标准的 [{"code": "...", "name": "..."}] 列表。"""
    from easy_tdx.stock_lookup import get_stock_name

    if isinstance(raw_data, (str, Path)):
        p = Path(raw_data)
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            except Exception as e:
                logger.warning(f"读取自选股文件 {p} 失败: {e}")
                return []
        else:
            try:
                raw_data = json.loads(str(raw_data))
            except Exception:
                raw_data = [s.strip() for s in str(raw_data).replace("\n", ",").split(",") if s.strip()]

    items: list[dict[str, str]] = []
    seen = set()
    if isinstance(raw_data, list):
        for s in raw_data:
            if isinstance(s, dict):
                c = str(s.get("code") or s.get("symbol") or "").strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
                n = str(s.get("name") or "").strip()
            elif isinstance(s, str):
                c = s.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
                n = ""
            else:
                continue

            if c and c not in seen and len(c) == 6 and c.isdigit():
                seen.add(c)
                if not n or n.startswith("标的_"):
                    n = get_stock_name(c) or c
                items.append({"code": c, "name": n})
    return items


def merge_watchlist_items(base_items: list[Any], incoming_items: list[Any]) -> list[dict[str, str]]:
    """将两组自选股智能无损合并并去重，保留全部并集，并按代码去重补全名称。"""
    from easy_tdx.stock_lookup import get_stock_name

    base_list = parse_watchlist_data(base_items)
    inc_list = parse_watchlist_data(incoming_items)

    merged: list[dict[str, str]] = []
    seen = set()

    for it in base_list:
        c = it["code"]
        n = it["name"]
        if c not in seen:
            seen.add(c)
            if not n or n == c or n.startswith("标的_"):
                n = get_stock_name(c) or n
            merged.append({"code": c, "name": n})

    for it in inc_list:
        c = it["code"]
        n = it["name"]
        if c not in seen:
            seen.add(c)
            if not n or n == c or n.startswith("标的_"):
                n = get_stock_name(c) or n
            merged.append({"code": c, "name": n})
        else:
            if n and n != c and not n.startswith("标的_"):
                for m in merged:
                    if m["code"] == c and (not m["name"] or m["name"] == c or m["name"].startswith("标的_")):
                        m["name"] = n
                        break

    return merged


def merge_watchlist_file(target_file: str | Path, source_file_or_data: Any) -> list[dict[str, str]]:
    """将源数据（文件/列表）合并至目标 watchlist.json 文件中，并写回保存。"""
    t_path = Path(target_file)
    existing = []
    if t_path.is_file():
        existing = parse_watchlist_data(t_path)
    incoming = parse_watchlist_data(source_file_or_data)
    merged = merge_watchlist_items(existing, incoming)

    with _lock:
        t_path.parent.mkdir(parents=True, exist_ok=True)
        with open(t_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        logger.info(f"✓ 已将自选股安全合并至 {t_path.resolve()} (总计 {len(merged)} 只)")

    return merged

