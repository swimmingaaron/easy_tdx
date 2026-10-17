"""Stock metadata lookup, Pinyin initials matching, and autocomplete service for easy_tdx."""
from __future__ import annotations
import re
import urllib.request
import urllib.parse
import logging
from typing import Any

from easy_tdx._http_utils import urlopen_safe

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

# Fast in-memory map: symbol -> name, symbol -> pinyin, and full stock metadata
_SYMBOL_NAME_MAP: dict[str, str] = {s["code"]: s["name"] for s in COMMON_STOCKS + COMMON_INDICES}
_SYMBOL_PINYIN_MAP: dict[str, str] = {s["code"]: s.get("pinyin", "") for s in COMMON_STOCKS + COMMON_INDICES}
_ALL_STOCKS_MAP: dict[str, dict[str, Any]] = {s["code"]: s for s in COMMON_STOCKS + COMMON_INDICES}
_STOCK_NAMES_LOADED = False
_STOCK_NAMES_LOCK = threading.Lock()

_BOARD_MAP: dict[str, dict[str, Any]] = {}
_BOARD_MAP_LOADED = False
_BOARD_MAP_LOCK = threading.Lock()

# GB2312 Table for algorithmic Pinyin initials conversion
GB2312_TABLE = [
    (0xB0A1, 0xB0C4, 'A'), (0xB0C5, 0xB2C0, 'B'), (0xB2C1, 0xB4ED, 'C'),
    (0xB4EE, 0xB6E9, 'D'), (0xB6EA, 0xB7A1, 'E'), (0xB7A2, 0xB8C0, 'F'),
    (0xB8C1, 0xB9FD, 'G'), (0xB9FE, 0xBBF6, 'H'), (0xBBF7, 0xBFA5, 'J'),
    (0xBFA6, 0xC0AB, 'K'), (0xC0AC, 0xC2E7, 'L'), (0xC2E8, 0xC4C2, 'M'),
    (0xC4C3, 0xC5B5, 'N'), (0xC5B6, 0xC5BD, 'O'), (0xC5BE, 0xC6D9, 'P'),
    (0xC6DA, 0xC8BA, 'Q'), (0xC8BB, 0xC8F5, 'R'), (0xC8F6, 0xCBF9, 'S'),
    (0xCBFA, 0xCDD9, 'T'), (0xCDDA, 0xCEF3, 'W'), (0xCEF4, 0xD188, 'X'),
    (0xD189, 0xD4D0, 'Y'), (0xD4D1, 0xD7F9, 'Z')
]

CUSTOM_CHAR_MAP = {
    '鑫': 'X', '钛': 'T', '锂': 'L', '怡': 'Y', '粤': 'Y', '睿': 'R', '恒': 'H',
    '晟': 'S', '祺': 'Q', '泓': 'H', '恺': 'K', '珈': 'J', '珀': 'P', '玺': 'X',
    '澜': 'L', '斐': 'F', '梵': 'F', '淼': 'M', '焱': 'Y', '璟': 'J', '珂': 'K',
    '璞': 'P', '珩': 'H', '旻': 'M', '昊': 'H', '昱': 'Y', '晨': 'C', '瀚': 'H',
    '翔': 'X', '达': 'D', '迪': 'D', '迈': 'M', '逸': 'Y', '逊': 'X', '遵': 'Z',
    '适': 'S', '选': 'X', '硅': 'G', '铂': 'B', '钨': 'W', '锗': 'Z', '钼': 'M',
    '钽': 'T', '铌': 'N', '铍': 'P', '锆': 'Z', '铪': 'H', '钒': 'F', '镓': 'G',
    '锶': 'S', '钡': 'B', '钴': 'G', '镍': 'N', '锌': 'X', '铝': 'L', '镁': 'M',
    '钙': 'G', '钾': 'J', '钠': 'N', '铬': 'G', '锰': 'M', '铁': 'T', '铜': 'T',
    '银': 'Y', '金': 'J', '碳': 'T', '氮': 'D', '氧': 'Y', '氢': 'Q', '氦': 'H',
    '氖': 'N', '氩': 'Y', '氪': 'K', '氙': 'X', '氡': 'D', '硼': 'P', '磷': 'L',
    '硫': 'L', '氯': 'L', '氟': 'F', '碘': 'D', '溴': 'X', '硒': 'X', '砷': 'S'
}

def char_to_pinyin_initial(c: str) -> str:
    """Convert a single Chinese character to uppercase Pinyin initial letter."""
    if not c or c in ('*', ' ', '-', '(', ')'):
        return ''
    if c.isascii():
        return c.upper() if c.isalnum() else ''
    if c in CUSTOM_CHAR_MAP:
        return CUSTOM_CHAR_MAP[c]
    try:
        bs = c.encode('gb2312')
        val = bs[0] * 256 + bs[1]
        for start, end, letter in GB2312_TABLE:
            if start <= val <= end:
                return letter
    except Exception:
        pass
    return ''

def name_to_pinyin_fallback(name: str) -> str:
    """Convert Chinese stock name to uppercase Pinyin initials."""
    return ''.join(char_to_pinyin_initial(c) for c in (name or ''))

def _ensure_stock_names_map():
    """Lazily load all 5,200+ A-share stocks from local repository data and precomputed Pinyin."""
    global _STOCK_NAMES_LOADED, _ALL_STOCKS_MAP, _SYMBOL_PINYIN_MAP
    if _STOCK_NAMES_LOADED:
        return
    with _STOCK_NAMES_LOCK:
        if _STOCK_NAMES_LOADED:
            return
        
        # 1. Load precomputed Pinyin dictionary if available
        pinyin_paths = [
            Path(__file__).resolve().parent.parent.parent / "data" / "stock_pinyin.json",
            Path("c:/Users/aaron/Documents/stock_data/easy_tdx/data/stock_pinyin.json"),
        ]
        pinyin_dict: dict[str, str] = {}
        for pp in pinyin_paths:
            if pp.exists():
                try:
                    pinyin_dict = json.loads(pp.read_text("utf-8"))
                    break
                except Exception as e:
                    logger.debug(f"Failed to read stock pinyin from {pp}: {e}")

        # 2. Load stock names
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
                                py = pinyin_dict.get(c) or pinyin_dict.get(c.lstrip("0")) or name_to_pinyin_fallback(n)
                                _SYMBOL_NAME_MAP[c] = n
                                _SYMBOL_PINYIN_MAP[c] = py
                                _ALL_STOCKS_MAP[c] = {
                                    "symbol": c,
                                    "code": c,
                                    "name": n,
                                    "market": m,
                                    "pinyin": py,
                                    "display": f"{c} {n}"
                                }
                                loaded_count += 1
                    elif isinstance(content, dict):
                        for c, n in content.items():
                            c = str(c).strip().zfill(6)
                            n = str(n).strip()
                            if c and n and not n.startswith("?") and not n.startswith("标的_"):
                                py = pinyin_dict.get(c) or pinyin_dict.get(c.lstrip("0")) or name_to_pinyin_fallback(n)
                                _SYMBOL_NAME_MAP[c] = n
                                _SYMBOL_PINYIN_MAP[c] = py
                                m = "SH" if c.startswith(("60", "68", "99")) else ("BJ" if c.startswith(("8", "4")) else "SZ")
                                _ALL_STOCKS_MAP[c] = {
                                    "symbol": c,
                                    "code": c,
                                    "name": n,
                                    "market": m,
                                    "pinyin": py,
                                    "display": f"{c} {n}"
                                }
                                loaded_count += 1
                    if loaded_count > 1000:
                        break
                except Exception as e:
                    logger.debug(f"Failed to load stock names from {p}: {e}")
        
        # Ensure common stocks & indices have priority
        for s in COMMON_STOCKS + COMMON_INDICES:
            c = s["code"]
            _SYMBOL_NAME_MAP[c] = s["name"]
            _SYMBOL_PINYIN_MAP[c] = s.get("pinyin", "")
            _ALL_STOCKS_MAP[c] = {
                "symbol": c,
                "code": c,
                "name": s["name"],
                "market": s.get("market", "SZ"),
                "pinyin": s.get("pinyin", ""),
                "display": f"{c} {s['name']}"
            }
            
        _STOCK_NAMES_LOADED = True
        logger.info(f"Loaded {len(_SYMBOL_NAME_MAP)} stock name mappings into memory")

def _ensure_board_map():
    """Lazily load all 560+ TDX industry and concept board metadata without blocking."""
    global _BOARD_MAP, _BOARD_MAP_LOADED
    if _BOARD_MAP_LOADED:
        return
    with _BOARD_MAP_LOCK:
        if _BOARD_MAP_LOADED:
            return
        _BOARD_MAP_LOADED = True
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
                        py = name_to_pinyin_fallback(n)
                        _BOARD_MAP[c] = {
                            "symbol": c,
                            "code": c,
                            "name": n,
                            "market": "HY",
                            "pinyin": py,
                            "display": f"{c} {n} [行业板块]"
                        }
                        _SYMBOL_NAME_MAP[c] = n
                        _SYMBOL_PINYIN_MAP[c] = py
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
    if raw_sym in ("999688", "SH000688", "000688SH", "000688.SH"):
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
        with urlopen_safe(req, timeout=2.5) as resp:
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

def get_stock_pinyin(symbol: str) -> str:
    """Resolve Pinyin initials from stock code or symbol."""
    _ensure_stock_names_map()
    clean_sym = str(symbol or "").strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace("HY", "").replace(".", "")
    if clean_sym in _SYMBOL_PINYIN_MAP:
        return _SYMBOL_PINYIN_MAP[clean_sym]
    name = get_stock_name(clean_sym)
    return name_to_pinyin_fallback(name)

def search_stocks(query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Search stocks and industry boards by code, Chinese name, or Pinyin initials."""
    _ensure_stock_names_map()
    if not _BOARD_MAP_LOADED:
        threading.Thread(target=_ensure_board_map, daemon=True).start()
        
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

    # 1. Check local stock cache (contains full 5,200+ A-shares with full Pinyin)
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
            if len(matched_map) >= limit * 3:
                break

    # 2. Check TDX board indices
    for c, b_info in _BOARD_MAP.items():
        b_name = b_info.get("name", "")
        b_py = b_info.get("pinyin", "")
        if q in c or (b_name and q in b_name) or (b_py and q_upper in b_py):
            matched_map[c] = b_info

    # 3. Query Tencent Smartbox as supplemental search if few matches and no exact match
    has_exact = any(x["code"] == q or (x.get("pinyin") and x["pinyin"] == q_upper) for x in matched_map.values())
    if not has_exact and len(matched_map) < min(limit, 5):
        try:
            url = f"https://smartbox.gtimg.cn/s3/?q={urllib.parse.quote(q)}&t=all"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urlopen_safe(req, timeout=1.5) as resp:
                raw_bytes = resp.read()
                content = raw_bytes.decode("utf-8", errors="ignore")
                first = content.find('"')
                last = content.rfind('"')
                if first != -1 and last != -1:
                    raw_str = content[first + 1:last]
                    for item in raw_str.split("^"):
                        parts = item.split("~")
                        if len(parts) >= 4:
                            mkt, code, name_raw, pinyin = parts[0].upper(), parts[1], parts[2], parts[3].upper()
                            try:
                                clean_name = name_raw.encode("utf-8").decode("unicode_escape")
                            except Exception:
                                clean_name = name_raw
                            clean_name = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', clean_name).strip()
                            if mkt in ("SH", "SZ", "BJ") and code:
                                _SYMBOL_NAME_MAP[code] = clean_name
                                _SYMBOL_PINYIN_MAP[code] = pinyin
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
        # 0: Exact code or exact pinyin match
        0 if x["code"] == q or (x.get("pinyin") and x["pinyin"] == q_upper) else (
            # 1: Prefix match
            1 if (x["code"].startswith(q) or (x.get("pinyin") and x["pinyin"].startswith(q_upper)) or x["name"].startswith(q)) else 2
        ),
        len(x["name"]),
        x["code"]
    ))
    return results[:limit]


