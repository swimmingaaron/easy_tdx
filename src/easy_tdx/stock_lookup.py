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
    {"code": "688981", "name": "中芯国际", "market": "SH", "pinyin": "ZXGJ"},
]

# Fast in-memory map: symbol -> name
_SYMBOL_NAME_MAP: dict[str, str] = {s["code"]: s["name"] for s in COMMON_STOCKS}

def get_stock_name(symbol: str) -> str:
    """Resolve Chinese stock name from symbol, with fallback."""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(":", "")
    if clean_sym in _SYMBOL_NAME_MAP:
        return _SYMBOL_NAME_MAP[clean_sym]
    
    # Try quick online search
    results = search_stocks(clean_sym, limit=1)
    if results and results[0]["code"] == clean_sym:
        _SYMBOL_NAME_MAP[clean_sym] = results[0]["name"]
        return results[0]["name"]
        
    return f"标的_{clean_sym}"

def search_stocks(query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Search stocks by code, Chinese name, or Pinyin initials."""
    q = query.strip()
    if not q:
        return [
            {
                "symbol": s["code"],
                "code": s["code"],
                "name": s["name"],
                "market": s["market"],
                "pinyin": s["pinyin"],
                "display": f"{s['code']} {s['name']}"
            }
            for s in COMMON_STOCKS[:limit]
        ]
    
    q_lower = q.lower()
    q_upper = q.upper()
    matched_map: dict[str, dict[str, Any]] = {}

    # 1. Check local cache first
    for s in COMMON_STOCKS:
        if (
            q in s["code"]
            or q_upper in s["pinyin"]
            or q in s["name"]
        ):
            matched_map[s["code"]] = {
                "symbol": s["code"],
                "code": s["code"],
                "name": s["name"],
                "market": s["market"],
                "pinyin": s["pinyin"],
                "display": f"{s['code']} {s['name']}"
            }

    # 2. Query Tencent Smartbox for full market coverage
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
        not (x["code"].startswith(q) or x["pinyin"].startswith(q_upper) or x["name"].startswith(q)),
        len(x["name"])
    ))
    return results[:limit]
