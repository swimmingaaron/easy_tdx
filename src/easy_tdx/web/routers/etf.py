"""ETF and National Team ETF Tracker Web API Router for easy_tdx.

Provides endpoints for National Team ETF Tracking (国家队ETF动向追踪):
- /api/etf/data: 获取全部国家队ETF历史净申赎、份额变动、行情、股指期货持仓及基准数据
- /api/etf/refresh: 手动强制从远端数据源刷新最新ETF追踪数据
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/etf", tags=["etf"])

_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
_DATA_FILE = _BASE_DIR / "data" / "etf_data.json"
_REMOTE_URL = "https://etf.maomaoci-a.com/data/data.json"

_ETF_CACHE_LOCK = threading.Lock()
_ETF_MEM_CACHE: Dict[str, Any] | None = None
_ETF_CACHE_TS: float = 0.0
_CACHE_TTL_SEC: float = 3600.0  # 1 hour cache


def _fetch_remote_etf_data() -> Dict[str, Any] | None:
    """Fetch remote ETF data from upstream."""
    try:
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        }
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(f"{_REMOTE_URL}?t={int(time.time())}")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "etfs" in data:
                    try:
                        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
                        _DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                        logger.info("Successfully refreshed and cached ETF data from remote to %s", _DATA_FILE)
                    except Exception as err:
                        logger.warning("Failed to save ETF data to disk: %s", err)
                    return data
    except Exception as e:
        logger.warning("Failed to fetch remote ETF data from %s: %s", _REMOTE_URL, e)
    return None


def _load_local_etf_data() -> Dict[str, Any] | None:
    """Read local cached ETF data file."""
    if _DATA_FILE.is_file():
        try:
            return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to read local ETF data from %s: %s", _DATA_FILE, e)
    return None


@router.get("/data")
def get_etf_tracking_data(force: bool = Query(False, description="强制从远程拉取最新数据")) -> Dict[str, Any]:
    """获取国家队ETF追踪全部结构化数据。优先命中内存与本地磁盘缓存，支持按需/超时刷新。"""
    global _ETF_MEM_CACHE, _ETF_CACHE_TS

    now = time.time()
    with _ETF_CACHE_LOCK:
        if not force and _ETF_MEM_CACHE is not None and (now - _ETF_CACHE_TS < _CACHE_TTL_SEC):
            return _ETF_MEM_CACHE

    data: Dict[str, Any] | None = None
    if force:
        data = _fetch_remote_etf_data()

    if data is None:
        data = _load_local_etf_data()

    if data is None and not force:
        data = _fetch_remote_etf_data()

    if data is None:
        return {
            "success": False,
            "error": "未能读取国家队ETF追踪数据",
            "updated": "--",
            "dates": [],
            "etfs": [],
            "series": {},
        }

    with _ETF_CACHE_LOCK:
        _ETF_MEM_CACHE = data
        _ETF_CACHE_TS = now

    return data


@router.post("/refresh")
def refresh_etf_tracking_data() -> Dict[str, Any]:
    """手动强制触发国家队ETF动向数据拉取与更新。"""
    data = _fetch_remote_etf_data()
    if data:
        with _ETF_CACHE_LOCK:
            global _ETF_MEM_CACHE, _ETF_CACHE_TS
            _ETF_MEM_CACHE = data
            _ETF_CACHE_TS = time.time()
        return {"success": True, "updated": data.get("updated", ""), "message": "ETF数据刷新成功"}
    return {"success": False, "message": "远程数据源暂时无法访问，继续沿用本地缓存"}
