"""ETF and National Team ETF Tracker Web API Router for easy_tdx.

Provides endpoints for National Team ETF Tracking (国家队ETF动向追踪):
- /api/etf/data: 获取全部国家队ETF历史净申赎、份额变动、行情、股指期货持仓及基准数据 (基于本地easy_tdx通信接口)
- /api/etf/refresh: 手动强制从easy_tdx本地行情接口刷新最新ETF行情与追踪数据
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/etf", tags=["etf"])

def _find_data_file() -> Path:
    # Look for data/etf_data.json at repo root (parents[4])
    try:
        repo_root = Path(__file__).resolve().parents[4]
        candidate = repo_root / "data" / "etf_data.json"
        if candidate.is_file() or candidate.parent.is_dir():
            return candidate
    except Exception:
        pass
    return Path(__file__).resolve().parent.parent / "data" / "etf_data.json"


_DATA_FILE = _find_data_file()

_ETF_CACHE_LOCK = threading.Lock()
_ETF_MEM_CACHE: Dict[str, Any] | None = None
_ETF_CACHE_TS: float = 0.0
_CACHE_TTL_SEC: float = 300.0  # 5 minutes cache

ETF_CONFIGS: List[Dict[str, str]] = [
    {"code": "510300", "name": "沪深300ETF", "full": "华泰柏瑞沪深300ETF", "exch": "SH", "index": "沪深300", "gjd_note": "汇金系合计持约736亿份，占比82.8%（2025年报）"},
    {"code": "510310", "name": "沪深300ETF易方达", "full": "易方达沪深300ETF发起式", "exch": "SH", "index": "沪深300", "gjd_note": "汇金重仓（2025年报持仓市值超1800亿元）"},
    {"code": "510330", "name": "沪深300ETF华夏", "full": "华夏沪深300ETF", "exch": "SH", "index": "沪深300", "gjd_note": "汇金重仓（2025年报持仓市值超1300亿元）"},
    {"code": "159919", "name": "沪深300ETF嘉实", "full": "嘉实沪深300ETF", "exch": "SZ", "index": "沪深300", "gjd_note": "汇金重仓（2025年报持仓市值超1200亿元）"},
    {"code": "510050", "name": "上证50ETF", "full": "华夏上证50ETF", "exch": "SH", "index": "上证50", "gjd_note": "汇金重仓"},
    {"code": "510180", "name": "上证180ETF", "full": "华安上证180ETF", "exch": "SH", "index": "上证180", "gjd_note": "汇金持仓"},
    {"code": "510500", "name": "中证500ETF", "full": "南方中证500ETF", "exch": "SH", "index": "中证500", "gjd_note": "汇金重仓，2025上半年获增持"},
    {"code": "512500", "name": "中证500ETF华夏", "full": "华夏中证500ETF", "exch": "SH", "index": "中证500", "gjd_note": "华夏-汇金资管计划2025下半年增持约4亿份"},
    {"code": "512100", "name": "中证1000ETF", "full": "南方中证1000ETF", "exch": "SH", "index": "中证1000", "gjd_note": "汇金重仓，2025上半年获增持"},
    {"code": "159845", "name": "中证1000ETF华夏", "full": "华夏中证1000ETF", "exch": "SZ", "index": "中证1000", "gjd_note": "汇金持仓，2025上半年获增持"},
    {"code": "560010", "name": "中证1000ETF广发", "full": "广发中证1000ETF", "exch": "SH", "index": "中证1000", "gjd_note": "汇金持仓，2025上半年获增持"},
    {"code": "159629", "name": "中证1000ETF富国", "full": "富国中证1000ETF", "exch": "SZ", "index": "中证1000", "gjd_note": "汇金持仓，2025上半年获增持"},
    {"code": "588000", "name": "科创50ETF", "full": "华夏上证科创板50ETF", "exch": "SH", "index": "科创50", "gjd_note": "汇金重仓"},
    {"code": "588080", "name": "科创板50ETF易方达", "full": "易方达上证科创板50ETF", "exch": "SH", "index": "科创50", "gjd_note": "汇金持仓，2025上半年获增持"},
    {"code": "159915", "name": "创业板ETF", "full": "易方达创业板ETF", "exch": "SZ", "index": "创业板指", "gjd_note": "汇金持仓，2025上半年获增持"},
    {"code": "159977", "name": "创业板ETF天弘", "full": "天弘创业板ETF", "exch": "SZ", "index": "创业板指", "gjd_note": "汇金投资2025下半年增持2.3亿份（唯一加仓标的）"},
]


def _load_local_etf_data() -> Dict[str, Any] | None:
    """Read local cached ETF data file."""
    if _DATA_FILE.is_file():
        try:
            return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to read local ETF data from %s: %s", _DATA_FILE, e)
    return None


def _refresh_from_easy_tdx() -> Dict[str, Any] | None:
    """Fetch authoritative ETF quotes and daily K-lines purely from local easy_tdx market data interface."""
    try:
        from easy_tdx.market_data import fetch_realtime_pool_quotes, fetch_security_kline, KlineCategory

        local_data = _load_local_etf_data() or {}

        symbols = [f"{cfg['code']}.{cfg['exch']}" for cfg in ETF_CONFIGS]
        quotes = fetch_realtime_pool_quotes(symbols)
        quote_map = {q["code"]: q for q in quotes}
        logger.info("Successfully fetched %d realtime ETF quotes via easy_tdx", len(quote_map))

        # Benchmark K-line for standard trading calendar
        ref_df = fetch_security_kline("510300.SH", category=KlineCategory.DAY, count=132)
        if ref_df is None or ref_df.empty:
            logger.error("Failed to fetch reference K-line for 510300.SH via easy_tdx")
            return local_data if local_data else None

        master_dates = [str(d)[:10] for d in ref_df["datetime"]]

        new_series: Dict[str, Any] = {}
        enriched_etfs: List[Dict[str, Any]] = []

        for cfg in ETF_CONFIGS:
            code = cfg["code"]
            exch = cfg["exch"]
            sym = f"{code}.{exch}"

            # Fetch authentic daily K-line
            df = fetch_security_kline(sym, category=KlineCategory.DAY, count=len(master_dates))
            date_to_close: Dict[str, float] = {}
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    d_str = str(row["datetime"])[:10]
                    c_val = float(row["close"]) if row["close"] is not None else 0.0
                    date_to_close[d_str] = round(c_val, 3)

            closes = [date_to_close.get(d) for d in master_dates]

            # Preserve & align shares
            old_s = local_data.get("series", {}).get(code, {})
            old_shares = old_s.get("shares", [])
            old_dates = local_data.get("dates", [])
            old_date_to_share = {d: s for d, s in zip(old_dates, old_shares)}

            shares: List[float | None] = []
            for d in master_dates:
                shares.append(old_date_to_share.get(d))

            # Update latest share from real-time quote
            q = quote_map.get(code)
            if q and q.get("total_shares"):
                latest_sh = round(float(q["total_shares"]) / 10000.0, 4)
                if shares:
                    shares[-1] = latest_sh

            # Recalculate inflows strictly: (shares[i] - shares[i-1]) * close[i] in 亿元
            flows: List[float | None] = []
            for i in range(len(master_dates)):
                if i == 0 or shares[i] is None or shares[i - 1] is None or closes[i] is None:
                    flows.append(None)
                else:
                    delta_sh = shares[i] - shares[i - 1]
                    flows.append(round(delta_sh * closes[i], 4))

            new_series[code] = {
                "shares": shares,
                "flow": flows,
                "close": closes,
            }

            # Enrich ETF config with real-time metrics for frontend
            etf_entry = dict(cfg)
            if q:
                etf_entry["price"] = q.get("price", closes[-1] if closes else 0.0)
                etf_entry["change_pct"] = q.get("change_pct", 0.0)
                etf_entry["turnover_wan"] = q.get("turnover_wan", 0.0)
                if q.get("total_shares"):
                    etf_entry["total_shares_yi"] = round(float(q["total_shares"]) / 10000.0, 4)
            else:
                etf_entry["price"] = closes[-1] if closes else 0.0
                etf_entry["change_pct"] = 0.0

            enriched_etfs.append(etf_entry)

        now_str = time.strftime("%H:%M")
        data = {
            "sample": False,
            "updated": f"{master_dates[-1]} {now_str} (easy_tdx行情)",
            "baseline": local_data.get("baseline"),
            "etfs": enriched_etfs,
            "dates": master_dates,
            "series": new_series,
            "futures": local_data.get("futures"),
        }

        try:
            _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            _DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Successfully updated and saved ETF data to %s via easy_tdx", _DATA_FILE)
        except Exception as err:
            logger.warning("Failed to save ETF data to disk: %s", err)

        return data
    except Exception as e:
        logger.exception("Failed to refresh ETF data from easy_tdx: %s", e)
        return _load_local_etf_data()


@router.get("/data")
def get_etf_tracking_data(force: bool = Query(False, description="强制从easy_tdx接口拉取最新行情数据")) -> Dict[str, Any]:
    """获取国家队ETF追踪全部结构化数据。基于本地easy_tdx通信接口提供真实K线与行情。"""
    global _ETF_MEM_CACHE, _ETF_CACHE_TS

    now = time.time()
    with _ETF_CACHE_LOCK:
        if not force and _ETF_MEM_CACHE is not None and (now - _ETF_CACHE_TS < _CACHE_TTL_SEC):
            return _ETF_MEM_CACHE

    data: Dict[str, Any] | None = None
    if force:
        data = _refresh_from_easy_tdx()

    if data is None:
        data = _load_local_etf_data()

    if data is None:
        data = _refresh_from_easy_tdx()

    if data is None:
        return {
            "success": False,
            "error": "未能读取国家队ETF追踪数据",
            "updated": "--",
            "dates": [],
            "etfs": ETF_CONFIGS,
            "series": {},
        }

    with _ETF_CACHE_LOCK:
        _ETF_MEM_CACHE = data
        _ETF_CACHE_TS = now

    return data


@router.post("/refresh")
def refresh_etf_tracking_data() -> Dict[str, Any]:
    """手动强制触发国家队ETF动向数据拉取与更新 (基于本地easy_tdx通信接口)。"""
    data = _refresh_from_easy_tdx()
    if data:
        with _ETF_CACHE_LOCK:
            global _ETF_MEM_CACHE, _ETF_CACHE_TS
            _ETF_MEM_CACHE = data
            _ETF_CACHE_TS = time.time()
        return {"success": True, "updated": data.get("updated", ""), "message": "ETF数据刷新成功 (easy_tdx行情)"}
    return {"success": False, "message": "easy_tdx数据源通信暂不可用，继续沿用本地数据"}

