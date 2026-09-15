"""Stock metadata lookup, Pinyin initials matching, and autocomplete service for easy_tdx."""
from __future__ import annotations
import re
import urllib.request
import urllib.parse
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Common baseline dictionary for offline / instant fast lookup
COMMON_STOCKS = [
    {"code": "000001", "name": "平安银行", "market": "SZ", "pinyin": "PAYH"},
    {"code": "000002", "name": "万科A", "market": "SZ", "pinyin": "WKA"},
    {"code": "000063", "name": "中兴通讯", "market": "SZ", "pinyin": "ZXTX"},
    {"code": "000333", "name": "美的集团", "market": "SZ", "pinyin": "MDJT"},
    {"code": "000651", "name": "格力电器", "market": "SZ", "pinyin": "GLDQ"},
    {"code": "000725", "name": "京东方A", "market": "SZ", "pinyin": "JDFA"},
    {"code": "000858", "name": "五粮液", "market": "SZ", "pinyin": "WLY"},
    {"code": "002230", "name": "科大讯飞", "market": "SZ", "pinyin": "KDXF"},
    {"code": "002345", "name": "潮宏基", "market": "SZ", "pinyin": "CHJ"},
    {"code": "002415", "name": "海康威视", "market": "SZ", "pinyin": "HKWS"},
    {"code": "002421", "name": "达实智能", "market": "SZ", "pinyin": "DSZN"},
    {"code": "002475", "name": "立讯精密", "market": "SZ", "pinyin": "LXJM"},
    {"code": "002594", "name": "比亚迪", "market": "SZ", "pinyin": "BYD"},
    {"code": "300059", "name": "东方财富", "market": "SZ", "pinyin": "DFCF"},
    {"code": "300223", "name": "北京君正", "market": "SZ", "pinyin": "BJJZ"},
    {"code": "300750", "name": "宁德时代", "market": "SZ", "pinyin": "NDSD"},
    {"code": "300760", "name": "迈瑞医疗", "market": "SZ", "pinyin": "MRYL"},
    {"code": "600000", "name": "浦发银行", "market": "SH", "pinyin": "PFYH"},
    {"code": "600028", "name": "中国石化", "market": "SH", "pinyin": "ZGSH"},
    {"code": "600030", "name": "中信证券", "market": "SH", "pinyin": "ZXZQ"},
    {"code": "600036", "name": "招商银行", "market": "SH", "pinyin": "ZSYH"},
    {"code": "600123", "name": "兰花科创", "market": "SH", "pinyin": "LHKC"},
    {"code": "600519", "name": "贵州茅台", "market": "SH", "pinyin": "GZMT"},
    {"code": "600887", "name": "伊利股份", "market": "SH", "pinyin": "YLGF"},
    {"code": "601318", "name": "中国平安", "market": "SH", "pinyin": "ZGPA"},
    {"code": "601857", "name": "中国石油", "market": "SH", "pinyin": "ZGSY"},
    {"code": "601888", "name": "中国中免", "market": "SH", "pinyin": "ZGZM"},
    {"code": "601899", "name": "紫金矿业", "market": "SH", "pinyin": "ZJKY"},
    {"code": "603259", "name": "药明康德", "market": "SH", "pinyin": "YMKD"},
    {"code": "603986", "name": "兆易创新", "market": "SH", "pinyin": "ZYCX"},
    {"code": "688981", "name": "中芯国际", "market": "SH", "pinyin": "ZXGJ"},
]

COMMON_INDICES = [
    {"code": "999999", "name": "上证指数", "market": "SH", "pinyin": "SZZS"},
    {"code": "000001.SH", "name": "上证指数", "market": "SH", "pinyin": "SZZS"},
    {"code": "SH000001", "name": "上证指数", "market": "SH", "pinyin": "SZZS"},
    {"code": "399001", "name": "深证成指", "market": "SZ", "pinyin": "SZCZ"},
    {"code": "399001.SZ", "name": "深证成指", "market": "SZ", "pinyin": "SZCZ"},
    {"code": "399006", "name": "创业板指", "market": "SZ", "pinyin": "CYBZ"},
    {"code": "399006.SZ", "name": "创业板指", "market": "SZ", "pinyin": "CYBZ"},
    {"code": "000688.SH", "name": "科创50", "market": "SH", "pinyin": "KC50"},
    {"code": "SH000688", "name": "科创50", "market": "SH", "pinyin": "KC50"},
    {"code": "000688SH", "name": "科创50", "market": "SH", "pinyin": "KC50"},
    {"code": "999688", "name": "科创50", "market": "SH", "pinyin": "KC50"},
    {"code": "000300.SH", "name": "沪深300", "market": "SH", "pinyin": "HS300"},
    {"code": "SH000300", "name": "沪深300", "market": "SH", "pinyin": "HS300"},
    {"code": "399300", "name": "沪深300", "market": "SZ", "pinyin": "HS300"},
    {"code": "399300.SZ", "name": "沪深300", "market": "SZ", "pinyin": "HS300"},
    {"code": "899050", "name": "北证50", "market": "BJ", "pinyin": "BZ50"},
    {"code": "899050.BJ", "name": "北证50", "market": "BJ", "pinyin": "BZ50"},
]

import json
import threading
from pathlib import Path

# Fast in-memory map: symbol -> name
_SYMBOL_NAME_MAP: dict[str, str] = {s["code"]: s["name"] for s in COMMON_STOCKS + COMMON_INDICES}
_ALL_STOCKS_MAP: dict[str, dict[str, Any]] = {s["code"]: s for s in COMMON_STOCKS + COMMON_INDICES}
_STOCK_NAMES_LOADED = False
_STOCK_NAMES_LOCK = threading.Lock()

_BOARD_MAP: dict[str, dict[str, Any]] = {}
_BOARD_MAP_LOADED = False
_BOARD_MAP_LOCK = threading.Lock()

def _ensure_stock_names_map():
    """Lazily load all 5,200+ A-share stocks from local repository data or cache."""
    global _STOCK_NAMES_LOADED, _ALL_STOCKS_MAP
    if _STOCK_NAMES_LOADED:
        return
    with _STOCK_NAMES_LOCK:
        if _STOCK_NAMES_LOADED:
            return
        
        possible_paths = [
            Path(__file__).resolve().parent.parent.parent / "data" / "stock_names.json",
            Path.home() / ".easy_tdx" / "cache" / "security_list_all.json",
            Path("c:/Users/aaron/Documents/stock_data/easy_tdx/data/stock_names.json"),
        ]
        loaded_count = 0
        for p in possible_paths:
            if p.exists():
                try:
                    content = json.loads(p.read_text("utf-8"))
                    if isinstance(content, dict) and "data" in content:
                        for item in content["data"]:
                            c = str(item.get("code", "")).strip().zfill(6)
                            n = str(item.get("name", "")).strip()
                            m = "SH" if item.get("market") == 1 else "SZ"
                            if c and n and not n.startswith("?") and not n.startswith("标的_"):
                                _SYMBOL_NAME_MAP[c] = n
                                _ALL_STOCKS_MAP[c] = {"code": c, "name": n, "market": m}
                                loaded_count += 1
                    elif isinstance(content, dict):
                        for c, n in content.items():
                            c = str(c).strip().zfill(6)
                            n = str(n).strip()
                            if c and n and not n.startswith("?") and not n.startswith("标的_"):
                                _SYMBOL_NAME_MAP[c] = n
                                m = "SH" if c.startswith(("60", "68", "99")) else ("BJ" if c.startswith(("8", "4")) else "SZ")
                                _ALL_STOCKS_MAP[c] = {"code": c, "name": n, "market": m}
                                loaded_count += 1
                    if loaded_count > 1000:
                        break
                except Exception as e:
                    logger.debug(f"Failed to load stock names from {p}: {e}")
        
        # Ensure common stocks & indices have priority
        for s in COMMON_STOCKS + COMMON_INDICES:
            _SYMBOL_NAME_MAP[s["code"]] = s["name"]
            _ALL_STOCKS_MAP[s["code"]] = s
            
        _STOCK_NAMES_LOADED = True
        logger.info(f"Loaded {len(_SYMBOL_NAME_MAP)} stock name mappings into memory")

def _ensure_board_map():
    """Lazily load all 560+ TDX industry and concept board metadata."""
    global _BOARD_MAP, _BOARD_MAP_LOADED
    if _BOARD_MAP_LOADED:
        return
    with _BOARD_MAP_LOCK:
        if _BOARD_MAP_LOADED:
            return
        try:
            from easy_tdx.mac.client import MacClient
            from easy_tdx.mac.enums import BoardType
            mac = MacClient.from_best_host()
            mac.connect()
            df = mac.get_board_list(BoardType.ALL)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    c = str(row.get("code", "")).strip()
                    n = str(row.get("name", "")).strip()
                    if c and n:
                        _BOARD_MAP[c] = {
                            "symbol": c,
                            "code": c,
                            "name": n,
                            "market": "HY",
                            "pinyin": "",
                            "display": f"{c} {n} [行业板块]"
                        }
                        _SYMBOL_NAME_MAP[c] = n
                _BOARD_MAP_LOADED = True
        except Exception as e:
            logger.debug(f"Failed to pre-load TDX board map: {e}")

def get_stock_name(symbol: str) -> str:
    """Resolve Chinese stock or board name from symbol, with multi-tier fallback."""
    raw_sym = str(symbol or "").strip().upper().replace(":", "")
    if not raw_sym:
        return ""
        
    _ensure_stock_names_map()

    # 1. Exact raw symbol check
    if raw_sym in _SYMBOL_NAME_MAP and not _SYMBOL_NAME_MAP[raw_sym].startswith("标的_"):
        return _SYMBOL_NAME_MAP[raw_sym]

    clean_sym = raw_sym.replace("SH", "").replace("SZ", "").replace("BJ", "").replace("HY", "").replace(".", "")
    if ("SH" in raw_sym) and f"{clean_sym}.SH" in _SYMBOL_NAME_MAP and not _SYMBOL_NAME_MAP[f"{clean_sym}.SH"].startswith("标的_"):
        return _SYMBOL_NAME_MAP[f"{clean_sym}.SH"]
    if ("SZ" in raw_sym) and f"{clean_sym}.SZ" in _SYMBOL_NAME_MAP and not _SYMBOL_NAME_MAP[f"{clean_sym}.SZ"].startswith("标的_"):
        return _SYMBOL_NAME_MAP[f"{clean_sym}.SZ"]
    if raw_sym in ("000688", "999688", "SH000688"):
        return "科创50"
    if clean_sym in _SYMBOL_NAME_MAP and not _SYMBOL_NAME_MAP[clean_sym].startswith("标的_"):
        return _SYMBOL_NAME_MAP[clean_sym]
    
    # 2. Check board map
    if clean_sym.startswith("88") or clean_sym.startswith("BK") or clean_sym.startswith("HY"):
        _ensure_board_map()
        if clean_sym in _SYMBOL_NAME_MAP and not _SYMBOL_NAME_MAP[clean_sym].startswith("标的_"):
            return _SYMBOL_NAME_MAP[clean_sym]

    # 3. Direct Tencent quote lookup (fast, single symbol query)
    try:
        pfx = "sh" if clean_sym.startswith(("6", "9")) else ("bj" if clean_sym.startswith(("8", "4")) else "sz")
        url = f"https://qt.gtimg.cn/q=s_{pfx}{clean_sym}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            text = resp.read().decode("gbk", errors="ignore")
            if "~" in text:
                parts = text.split("~")
                if len(parts) > 2 and parts[1]:
                    name = parts[1].strip()
                    if name and not name.startswith("?"):
                        _SYMBOL_NAME_MAP[clean_sym] = name
                        return name
    except Exception:
        pass

    # 4. Try quick online search (Smartbox)
    results = search_stocks(clean_sym, limit=1)
    if results and results[0]["code"] == clean_sym and not results[0]["name"].startswith("标的_"):
        _SYMBOL_NAME_MAP[clean_sym] = results[0]["name"]
        return results[0]["name"]
        
    return f"标的_{clean_sym}"

def search_stocks(query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Search stocks and industry boards by code, Chinese name, or Pinyin initials."""
    _ensure_stock_names_map()
    _ensure_board_map()
    q = query.strip()
    if not q:
        sample_boards = list(_BOARD_MAP.values())[:3]
        return [
            {
                "symbol": s["code"],
                "code": s["code"],
                "name": s["name"],
                "market": s.get("market", "SZ"),
                "pinyin": s.get("pinyin", ""),
                "display": f"{s['code']} {s['name']}"
            }
            for s in COMMON_STOCKS[:limit - len(sample_boards)]
        ] + sample_boards
    
    q_lower = q.lower()
    q_upper = q.upper()
    matched_map: dict[str, dict[str, Any]] = {}

    # 1. Check local stock cache (contains full 5,200+ A-shares)
    for c, s in _ALL_STOCKS_MAP.items():
        name_val = s.get("name", "")
        pinyin_val = s.get("pinyin", "")
        if (
            q in c
            or (pinyin_val and q_upper in pinyin_val)
            or (name_val and q in name_val)
        ):
            matched_map[c] = {
                "symbol": c,
                "code": c,
                "name": name_val,
                "market": s.get("market", "SZ"),
                "pinyin": pinyin_val,
                "display": f"{c} {name_val}"
            }
            if len(matched_map) >= limit * 2:
                break

    # 2. Check TDX board indices
    for c, b_info in _BOARD_MAP.items():
        if q in c or q in b_info["name"]:
            matched_map[c] = b_info

    # 3. Query Tencent Smartbox as supplemental search if few matches
    if len(matched_map) < limit:
        try:
            url = f"https://smartbox.gtimg.cn/s3/?q={urllib.parse.quote(q)}&t=all"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=1.8) as resp:
                raw_bytes = resp.read()
                content = raw_bytes.decode("unicode_escape", errors="ignore")
                first = content.find('"')
                last = content.rfind('"')
                if first != -1 and last != -1:
                    raw_str = content[first + 1:last]
                    for item in raw_str.split("^"):
                        parts = item.split("~")
                        if len(parts) >= 4:
                            mkt, code, name, pinyin = parts[0].upper(), parts[1], parts[2], parts[3].upper()
                            clean_name = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', name).strip()
                            if mkt in ("SH", "SZ", "BJ") and code:
                                _SYMBOL_NAME_MAP[code] = clean_name
                                matched_map[code] = {
                                    "symbol": code,
                                    "code": code,
                                    "name": clean_name,
                                    "market": mkt,
                                    "pinyin": pinyin,
                                    "display": f"{code} {clean_name}"
                                }
        except Exception as e:
            logger.debug(f"Smartbox search error: {e}")

    results = list(matched_map.values())
    results.sort(key=lambda x: (
        not (x["code"].startswith(q) or (x.get("pinyin") and x["pinyin"].startswith(q_upper)) or x["name"].startswith(q)),
        len(x["name"])
    ))
    return results[:limit]

