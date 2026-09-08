"""Stock Profile Service

Aggregates:
1. Shareholder counts & average shares per holder from TDX Finance / EastMoney / THS
2. Company profile, legal person, main business from F10 survey
3. Belonging sectors and concept theme tags
4. Financial reports: Revenue, Net Profit, YoY, QoQ
"""

import copy
import json
import logging
import re
import time
import urllib.request
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from .client import TdxClient
from .models import Market
from .sina import SinaClient

logger = logging.getLogger(__name__)

# In-memory TTL cache: key -> (timestamp, data)
_PROFILE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = 1800  # 30 minutes
_CACHE_LOCK = Lock()

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "close",
}


def clear_stock_profile_cache(code: Optional[str] = None) -> None:
    """Clear memory cache for a given code or all cached profiles."""
    with _CACHE_LOCK:
        if code:
            clean, _, _, _ = _parse_stock_symbol(code)
            _PROFILE_CACHE.pop(clean, None)
        else:
            _PROFILE_CACHE.clear()


def _parse_stock_symbol(code: str) -> Tuple[str, Market, str, bool]:
    """Parse raw stock code into (clean_6digit_code, Market, pfx, is_index_or_board)."""
    raw = str(code).strip().upper()
    has_sh = raw.startswith("SH") or raw.endswith("SH") or ".SH" in raw
    has_sz = raw.startswith("SZ") or raw.endswith("SZ") or ".SZ" in raw
    has_bj = raw.startswith("BJ") or raw.endswith("BJ") or ".BJ" in raw
    has_bk = raw.startswith(("BK", "HY")) or raw.endswith(("BK", "HY")) or ".BK" in raw

    m = re.search(r"\d{6}", raw)
    if m:
        clean_code = m.group(0)
    else:
        clean_code = re.sub(r"[^0-9]", "", raw)

    is_index_or_board = (
        has_bk
        or clean_code.startswith("88")
        or (
            clean_code
            in (
                "999999",
                "999998",
                "999997",
                "399001",
                "399006",
                "399300",
                "000300",
                "000688",
            )
            and (has_sh or not has_sz)
        )
    )

    if (
        has_bj
        or clean_code.startswith(("4", "83", "87", "92", "899"))
        or (clean_code.startswith("8") and not clean_code.startswith("88"))
    ):
        mkt = Market.BJ
        pfx = "BJ"
    elif has_sz or clean_code.startswith(("00", "30", "399", "08", "03")):
        mkt = Market.SZ
        pfx = "SZ"
    else:
        mkt = Market.SH
        pfx = "SH"

    return clean_code, mkt, pfx, is_index_or_board


def _resolve_quarter_end_date(date_str: str) -> str:
    """Resolve an announcement or updated date to standard quarterly report end date (YYYY-MM-DD)."""
    d = str(date_str).strip()[:10]
    if any(q in d for q in ("-03-31", "-06-30", "-09-30", "-12-31")):
        return d
    try:
        parts = d.split("-")
        if len(parts) == 3:
            year = int(parts[0])
            month = int(parts[1])
            if month in (7, 8, 9):
                return f"{year}-06-30"
            elif month in (10, 11):
                return f"{year}-09-30"
            elif month in (5, 6):
                return f"{year}-03-31"
            elif month in (1, 2, 3, 4):
                return f"{year - 1}-12-31"
    except Exception:
        pass
    return d


def _format_period_title(end_date: str) -> str:
    """Format 'YYYY-MM-DD' into readable report period (e.g. '2024中报')."""
    d = str(end_date)[:10]
    if "-03-31" in d:
        return f"{d[:4]}一季报"
    elif "-06-30" in d:
        return f"{d[:4]}中报"
    elif "-09-30" in d:
        return f"{d[:4]}三季报"
    elif "-12-31" in d:
        return f"{d[:4]}年报"
    # Fallback if announcement date is passed directly:
    try:
        parts = d.split("-")
        if len(parts) == 3:
            year = int(parts[0])
            month = int(parts[1])
            if month in (7, 8, 9):
                return f"{year}中报"
            elif month in (10, 11):
                return f"{year}三季报"
            elif month in (5, 6):
                return f"{year}一季报"
            elif month in (1, 2, 3, 4):
                return f"{year - 1}年报"
    except Exception:
        pass
    return d


def _fetch_shareholder_history_datacenter(clean_code: str) -> List[Dict[str, Any]]:
    """Tier 1: EastMoney DataCenter open API (queries by pure code, works across SH, SZ, BJ)."""
    url = (
        f"https://datacenter.eastmoney.com/securities/api/data/v1/get?"
        f"reportName=RPT_F10_EH_HOLDERNUM&filter=(SECURITY_CODE%3D%22{clean_code}%22)"
        f"&columns=SECUCODE,SECURITY_CODE,END_DATE,HOLDER_TOTAL_NUM,TOTAL_NUM_RATIO,"
        f"AVG_FREE_SHARES,AVG_FREESHARES_RATIO,HOLD_FOCUS,AVG_HOLD_AMT"
        f"&sortColumns=END_DATE&sortTypes=-1&pageNumber=1&pageSize=8"
    )
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        res = data.get("result") or {}
        items = res.get("data") or []
        records = []
        for g in items[:4]:
            end_date = str(g.get("END_DATE", ""))[:10]
            if not end_date:
                continue
            records.append({
                "period": end_date,
                "period_title": _format_period_title(end_date),
                "holder_count": g.get("HOLDER_TOTAL_NUM"),
                "holder_qoq": (
                    round(float(g["TOTAL_NUM_RATIO"]), 2)
                    if g.get("TOTAL_NUM_RATIO") is not None
                    else None
                ),
                "avg_shares": g.get("AVG_FREE_SHARES"),
                "avg_shares_wan": (
                    round(float(g["AVG_FREE_SHARES"]) / 10000.0, 2)
                    if g.get("AVG_FREE_SHARES") is not None
                    else None
                ),
                "avg_shares_qoq": (
                    round(float(g["AVG_FREESHARES_RATIO"]), 2)
                    if g.get("AVG_FREESHARES_RATIO") is not None
                    else None
                ),
                "avg_hold_amt_wan": (
                    round(float(g["AVG_HOLD_AMT"]) / 10000.0, 2)
                    if g.get("AVG_HOLD_AMT") is not None
                    else None
                ),
                "focus": g.get("HOLD_FOCUS") or "--",
            })
        return records


def _fetch_shareholder_history_pageajax(clean_code: str, pfx: str) -> List[Dict[str, Any]]:
    """Tier 2: EastMoney PC_HSF10 PageAjax API."""
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code={pfx}{clean_code}"
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        gdrs = data.get("gdrs") or []
        records = []
        for g in gdrs[:4]:
            end_date = str(g.get("END_DATE", ""))[:10]
            if not end_date:
                continue
            records.append({
                "period": end_date,
                "period_title": _format_period_title(end_date),
                "holder_count": g.get("HOLDER_TOTAL_NUM"),
                "holder_qoq": (
                    round(float(g["TOTAL_NUM_RATIO"]), 2)
                    if g.get("TOTAL_NUM_RATIO") is not None
                    else None
                ),
                "avg_shares": g.get("AVG_FREE_SHARES"),
                "avg_shares_wan": (
                    round(float(g["AVG_FREE_SHARES"]) / 10000.0, 2)
                    if g.get("AVG_FREE_SHARES") is not None
                    else None
                ),
                "avg_shares_qoq": (
                    round(float(g["AVG_FREESHARES_RATIO"]), 2)
                    if g.get("AVG_FREESHARES_RATIO") is not None
                    else None
                ),
                "avg_hold_amt_wan": (
                    round(float(g["AVG_HOLD_AMT"]) / 10000.0, 2)
                    if g.get("AVG_HOLD_AMT") is not None
                    else None
                ),
                "focus": g.get("HOLD_FOCUS") or "--",
            })
        return records


def _fetch_shareholder_history_ths(clean_code: str) -> List[Dict[str, Any]]:
    """Tier 3: Tonghuashun (10jqka) F10 holder table parser (especially resilient for BJ stocks)."""
    url = f"http://basic.10jqka.com.cn/{clean_code}/holder.html"
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=5) as resp:
        html = resp.read().decode("gbk", errors="ignore")

    tbody_idx = html.find('class="data_tbody"')
    if tbody_idx == -1:
        return []
    tbody_str = html[tbody_idx : tbody_idx + 15000]

    dates = re.findall(r'<div class="td_w">(\d{4}-\d{2}-\d{2})</div>', tbody_str)
    tr_matches = re.findall(r"<tr>(.*?)</tr>", tbody_str, re.DOTALL)
    rows_data = []
    for tr in tr_matches:
        td_vals = re.findall(r'<div class="td_w">([^<]*)</div>', tr)
        if td_vals and not re.match(r"^\d{4}-\d{2}-\d{2}$", td_vals[0]):
            rows_data.append(td_vals)

    if not dates or not rows_data:
        return []

    holders_row = rows_data[0] if len(rows_data) > 0 else []
    holders_ratio_row = rows_data[1] if len(rows_data) > 1 else []
    avg_shares_row = rows_data[3] if len(rows_data) > 3 else []
    avg_shares_ratio_row = rows_data[4] if len(rows_data) > 4 else []

    records = []
    for i in range(min(len(dates), 4)):
        d = dates[i]
        h_str = holders_row[i] if i < len(holders_row) else ""
        h_val = None
        if "万" in h_str:
            try:
                h_val = int(float(h_str.replace("万", "")) * 10000)
            except Exception:
                pass
        else:
            try:
                h_val = int(float(h_str))
            except Exception:
                pass

        hr_str = holders_ratio_row[i] if i < len(holders_ratio_row) else ""
        hr_val = None
        try:
            hr_val = round(float(hr_str.replace("%", "")), 2)
        except Exception:
            pass

        ash_str = avg_shares_row[i] if i < len(avg_shares_row) else ""
        ash_val = None
        if "万" in ash_str:
            try:
                ash_val = float(ash_str.replace("万", "")) * 10000
            except Exception:
                pass
        else:
            try:
                ash_val = float(ash_str)
            except Exception:
                pass

        ashr_str = avg_shares_ratio_row[i] if i < len(avg_shares_ratio_row) else ""
        ashr_val = None
        try:
            ashr_val = round(float(ashr_str.replace("%", "")), 2)
        except Exception:
            pass

        records.append({
            "period": d,
            "period_title": _format_period_title(d),
            "holder_count": h_val,
            "holder_qoq": hr_val,
            "avg_shares": ash_val,
            "avg_shares_wan": round(ash_val / 10000.0, 2) if ash_val is not None else None,
            "avg_shares_qoq": ashr_val,
            "avg_hold_amt_wan": None,
            "focus": "--",
        })
    return records


def _fetch_shareholder_history_tdx(
    clean_code: str, mkt: Optional[Market] = None
) -> Optional[Dict[str, Any]]:
    """Tier 1 First Choice: Fetch latest shareholder count directly via easy_tdx native protocol."""
    try:
        if mkt is None:
            _, inferred_mkt, _, _ = _parse_stock_symbol(clean_code)
            mkt = inferred_mkt
        with TdxClient.from_best_host(timeout=2.5) as cli:
            df = cli.get_finance_info(mkt, clean_code)
            if df is not None and not df.empty:
                row = df.iloc[0]
                holders = int(row.get("gudong_renshu", 0))
                if holders <= 0:
                    return None
                zong_guben = float(row.get("zong_guben", 0))
                liutong_guben = float(row.get("liutong_guben", 0))

                shares = liutong_guben if liutong_guben > 0 else zong_guben
                if 0 < shares < 10000000:
                    shares_total = shares * 10000.0
                else:
                    shares_total = shares
                avg_shares = round(shares_total / max(1, holders), 1) if holders > 0 else None

                raw_up_date = str(int(row.get("updated_date", 0)))
                if len(raw_up_date) == 8:
                    up_date_fmt = f"{raw_up_date[:4]}-{raw_up_date[4:6]}-{raw_up_date[6:]}"
                else:
                    up_date_fmt = raw_up_date

                std_period = _resolve_quarter_end_date(up_date_fmt)
                return {
                    "period": std_period,
                    "period_title": _format_period_title(std_period),
                    "holder_count": holders,
                    "holder_qoq": None,
                    "avg_shares": avg_shares,
                    "avg_shares_wan": round(avg_shares / 10000.0, 2) if avg_shares else None,
                    "avg_shares_qoq": None,
                    "avg_hold_amt_wan": None,
                    "focus": "--",
                    "source": "easy_tdx",
                    "raw_updated_date": up_date_fmt,
                }
    except Exception as e:
        logger.debug(f"Shareholder Tier 1 (easy_tdx) failed for {clean_code}: {e}")
    return None


def _fetch_shareholder_history(
    clean_code: str,
    pfx: str,
    mkt: Optional[Market] = None,
    tdx_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """三级弹性容灾获取体系 (3-Tier Resilient Disaster Recovery Architecture):
    - Tier 1 (第一选择 / 本地核心源): 通达信本地最新期（easy_tdx 通信接口）
    - Tier 2 (第二选择 / 历史主通道): 东方财富核心接口（DataCenter API 优先，PageAjax API 兜底）
    - Tier 3 (第三选择 / 极端兜底通道): 同花顺解析接口（10jqka F10 股东表解析）
    """
    # 1. Tier 1: 通达信本地最新期（easy_tdx 通信接口）为第一选择
    tdx_latest: Optional[Dict[str, Any]] = None
    if tdx_data and tdx_data.get("holder_count"):
        up_d = tdx_data.get("updated_date") or ""
        std_period = _resolve_quarter_end_date(up_d)
        tdx_latest = {
            "period": std_period,
            "period_title": _format_period_title(std_period),
            "holder_count": tdx_data.get("holder_count"),
            "holder_qoq": None,
            "avg_shares": tdx_data.get("avg_shares_per_holder"),
            "avg_shares_wan": (
                round(tdx_data["avg_shares_per_holder"] / 10000.0, 2)
                if tdx_data.get("avg_shares_per_holder")
                else None
            ),
            "avg_shares_qoq": None,
            "avg_hold_amt_wan": None,
            "focus": "--",
            "source": "easy_tdx",
            "raw_updated_date": up_d,
        }
    else:
        tdx_latest = _fetch_shareholder_history_tdx(clean_code, mkt)

    # 2. Tier 2: 东方财富接口（DataCenter 优先，PageAjax 兜底）
    ext_records: List[Dict[str, Any]] = []
    try:
        ext_records = _fetch_shareholder_history_datacenter(clean_code)
    except Exception as e:
        logger.debug(f"Shareholder Tier 2 (DataCenter) failed for {clean_code}: {e}")

    if not ext_records:
        try:
            ext_records = _fetch_shareholder_history_pageajax(clean_code, pfx)
        except Exception as e:
            logger.debug(f"Shareholder Tier 2 (PageAjax) failed for {clean_code}: {e}")

    # 3. Tier 3: 同花顺解析接口 (10jqka 兜底容灾)
    if not ext_records:
        try:
            ext_records = _fetch_shareholder_history_ths(clean_code)
        except Exception as e:
            logger.debug(f"Shareholder Tier 3 (THS) failed for {clean_code}: {e}")

    # 4. 融合架构：以通达信本地最新期为第一选择，结合东财/同花顺补齐历史4期并回算环比
    records: List[Dict[str, Any]] = []
    if tdx_latest and ext_records:
        tdx_period = tdx_latest["period"]
        ext_latest_period = ext_records[0]["period"]

        # 判断本地最新期与外部首期是否属于同季
        if tdx_period == ext_latest_period or (
            tdx_period[:4] == ext_latest_period[:4]
            and _format_period_title(tdx_period) == _format_period_title(ext_latest_period)
        ):
            # 报告期一致：以通达信本地最新期为第一选择覆盖人数与均股，保留东财等特色字段
            merged_latest = copy.deepcopy(ext_records[0])
            merged_latest["holder_count"] = tdx_latest["holder_count"]
            if tdx_latest.get("avg_shares"):
                merged_latest["avg_shares"] = tdx_latest["avg_shares"]
                merged_latest["avg_shares_wan"] = tdx_latest["avg_shares_wan"]
            merged_latest["source"] = "easy_tdx"
            records = [merged_latest] + ext_records[1:]
        elif tdx_period > ext_latest_period:
            # 通达信已披露更新一期：通达信最新期置顶作为首选
            records = [tdx_latest] + ext_records
        else:
            # 外部数据源期数更新（如预披露）：保留外部首期，后续期若匹配则首选通达信
            records = ext_records
    elif tdx_latest and not ext_records:
        # 外部网络全断流，通达信本地最新期独立兜底保活
        records = [tdx_latest]
    else:
        # 通达信未获取到，平滑降级至外部源
        records = ext_records

    # 5. 自适应校准与环比重算 (QoQ)
    if records:
        for i in range(len(records)):
            if i + 1 < len(records):
                prev = records[i + 1]
                curr_h = records[i].get("holder_count")
                prev_h = prev.get("holder_count")
                # 重新计算真实环比变动
                if curr_h and prev_h and prev_h > 0:
                    records[i]["holder_qoq"] = round(((curr_h - prev_h) / prev_h) * 100, 2)

                curr_ash = records[i].get("avg_shares")
                prev_ash = prev.get("avg_shares")
                if curr_ash and prev_ash and prev_ash > 0:
                    records[i]["avg_shares_qoq"] = round(((curr_ash - prev_ash) / prev_ash) * 100, 2)

    return records[:4]


def get_stock_full_profile(code: str, use_cache: bool = True) -> Dict[str, Any]:
    """Fetch complete stock profile including shareholders, company info, sectors, and financials."""
    clean_code, mkt, pfx, is_index_or_board = _parse_stock_symbol(code)
    cache_key = clean_code

    if use_cache:
        with _CACHE_LOCK:
            if cache_key in _PROFILE_CACHE:
                ts, cached_result = _PROFILE_CACHE[cache_key]
                if time.time() - ts < _CACHE_TTL:
                    return copy.deepcopy(cached_result)

    result: Dict[str, Any] = {
        "code": clean_code,
        "symbol": f"{clean_code}.{pfx}",
        "is_index_or_board": is_index_or_board,
        "shareholders": {},
        "company_info": {},
        "sectors": [],
        "financials": [],
        "shareholder_history": [],
    }

    # If it's an index or industry/concept board, skip individual stock F10 queries
    if is_index_or_board:
        with _CACHE_LOCK:
            _PROFILE_CACHE[cache_key] = (time.time(), copy.deepcopy(result))
        return result

    # 1. Native TDX Finance Info (Shareholders, Capital, Listing date)
    try:
        with TdxClient.from_best_host(timeout=2.5) as cli:
            f = cli.get_finance_info(mkt, clean_code)
        if f is not None and not f.empty:
            row = f.iloc[0]
            holders = int(row.get("gudong_renshu", 0))
            zong_guben = float(row.get("zong_guben", 0))
            liutong_guben = float(row.get("liutong_guben", 0))
            avg_shares = round(zong_guben / max(1, holders), 1) if holders > 0 else 0

            raw_up_date = str(int(row.get("updated_date", 0)))
            if len(raw_up_date) == 8:
                up_date_fmt = f"{raw_up_date[:4]}-{raw_up_date[4:6]}-{raw_up_date[6:]}"
            else:
                up_date_fmt = raw_up_date

            raw_ipo_date = str(int(row.get("ipo_date", 0)))
            if len(raw_ipo_date) == 8:
                ipo_date_fmt = f"{raw_ipo_date[:4]}-{raw_ipo_date[4:6]}-{raw_ipo_date[6:]}"
            else:
                ipo_date_fmt = raw_ipo_date

            result["shareholders"] = {
                "holder_count": holders,
                "avg_shares_per_holder": avg_shares,
                "total_shares_yi": (
                    round(zong_guben / 100000000.0, 2)
                    if zong_guben >= 100000000
                    else round(zong_guben / 10000.0, 2)
                ),
                "float_shares_yi": (
                    round(liutong_guben / 100000000.0, 2)
                    if liutong_guben >= 100000000
                    else round(liutong_guben / 10000.0, 2)
                ),
                "updated_date": up_date_fmt,
                "ipo_date": ipo_date_fmt,
                "nav_per_share": round(float(row.get("meigujing_zichan", 0)), 2),
            }
    except Exception as e:
        logger.debug(f"Failed to fetch TDX finance info for {clean_code}: {e}")

    # 2. Company Survey & Main Business (EastMoney F10)
    try:
        url_f10 = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={pfx}{clean_code}"
        req = urllib.request.Request(url_f10, headers=_DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            jb = data.get("jbzl")
            if isinstance(jb, list) and jb:
                jb = jb[0]
            if isinstance(jb, dict):
                ind = jb.get("sshy", "") or jb.get("sszjhhy", "")
                business_text = jb.get("gsjj", "") or jb.get("jyfw", "") or ""
                business_clean = " ".join(business_text.strip().split())

                result["company_info"] = {
                    "org_name": jb.get("gsmc", ""),
                    "industry": ind,
                    "province": jb.get("qy", ""),
                    "legal_person": jb.get("frdb", "") or jb.get("dsz", ""),
                    "general_manager": jb.get("zjl", ""),
                    "registered_capital": jb.get("zczb", ""),
                    "main_business": business_clean,
                }
                if ind:
                    result["sectors"].append({"name": ind, "type": "行业"})
    except Exception as e:
        logger.debug(f"Failed to fetch EastMoney company survey for {clean_code}: {e}")

    # 3. Core Concepts / Themes (EastMoney push2 / F10 Datacenter)
    try:
        url_boards = (
            f"https://datacenter.eastmoney.com/securities/api/data/v1/get?"
            f"reportName=RPT_F10_CORETHEME_BOARDTYPE&columns=SECURITY_CODE,BOARD_CODE,BOARD_NAME,BOARD_TYPE"
            f"&filter=(SECURITY_CODE%3D%22{clean_code}%22)"
        )
        req_b = urllib.request.Request(url_boards, headers=_DEFAULT_HEADERS)
        with urllib.request.urlopen(req_b, timeout=5) as resp_b:
            data_b = json.loads(resp_b.read().decode("utf-8"))
            if data_b.get("result") and data_b["result"].get("data"):
                existing_names = {s["name"] for s in result["sectors"]}
                for b_item in data_b["result"]["data"]:
                    b_name = b_item.get("BOARD_NAME", "")
                    if b_name and b_name not in existing_names:
                        existing_names.add(b_name)
                        result["sectors"].append({
                            "name": b_name,
                            "type": b_item.get("BOARD_TYPE") or "概念",
                        })
    except Exception as e:
        logger.debug(f"Failed to fetch concept boards for {clean_code}: {e}")

    # 4. Main Financial Reports (Revenue, Net Profit, Deducted Profit, YoY, QoQ)
    reports: List[Dict[str, Any]] = []
    try:
        url_fin = f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew?type=0&code={pfx}{clean_code}"
        req_fin = urllib.request.Request(url_fin, headers=_DEFAULT_HEADERS)
        with urllib.request.urlopen(req_fin, timeout=5) as resp_fin:
            raw_fin = resp_fin.read().decode("utf-8")
            data_fin = json.loads(raw_fin).get("data", [])
            for d in data_fin[:4]:
                rep_date = str(d.get("REPORT_DATE", ""))[:10]
                rep_title = d.get("REPORT_DATE_NAME") or rep_date

                # Revenue
                rev_val = float(d.get("TOTALOPERATEREVE") or 0.0)
                rev_yoy = (
                    float(d["TOTALOPERATEREVETZ"])
                    if d.get("TOTALOPERATEREVETZ") is not None
                    else None
                )

                # Net Profit
                np_val = float(d.get("PARENTNETPROFIT") or 0.0)
                np_yoy = (
                    float(d["PARENTNETPROFITTZ"])
                    if d.get("PARENTNETPROFITTZ") is not None
                    else None
                )

                # Deducted Net Profit
                kf_val = float(d.get("KCFJCXSYJLR") or 0.0)
                kf_yoy = (
                    float(d["KCFJCXSYJLRTZ"])
                    if d.get("KCFJCXSYJLRTZ") is not None
                    else None
                )

                reports.append({
                    "period": rep_date,
                    "period_title": rep_title,
                    "revenue": rev_val,
                    "revenue_yi": (
                        round(rev_val / 100000000.0, 2)
                        if rev_val >= 100000000
                        else round(rev_val / 10000.0, 2)
                    ),
                    "revenue_unit": "亿" if rev_val >= 100000000 else "万",
                    "revenue_yoy": round(rev_yoy, 2) if rev_yoy is not None else None,
                    "net_profit": np_val,
                    "net_profit_wan": (
                        round(np_val / 10000.0, 2)
                        if abs(np_val) < 100000000
                        else None
                    ),
                    "net_profit_yi": (
                        round(np_val / 100000000.0, 2)
                        if abs(np_val) >= 100000000
                        else None
                    ),
                    "net_profit_yoy": round(np_yoy, 2) if np_yoy is not None else None,
                    "deduct_net_profit": kf_val,
                    "deduct_net_profit_wan": (
                        round(kf_val / 10000.0, 2)
                        if abs(kf_val) < 100000000
                        else None
                    ),
                    "deduct_net_profit_yi": (
                        round(kf_val / 100000000.0, 2)
                        if abs(kf_val) >= 100000000
                        else None
                    ),
                    "deduct_net_profit_yoy": round(kf_yoy, 2) if kf_yoy is not None else None,
                })

            # Calculate QoQ
            for i in range(len(reports)):
                if i + 1 < len(reports):
                    prev = reports[i + 1]
                    if prev["revenue"] > 0:
                        reports[i]["revenue_qoq"] = round(
                            ((reports[i]["revenue"] - prev["revenue"]) / prev["revenue"]) * 100,
                            2,
                        )
                    if prev["net_profit"] != 0:
                        reports[i]["net_profit_qoq"] = round(
                            (
                                (reports[i]["net_profit"] - prev["net_profit"])
                                / abs(prev["net_profit"])
                            )
                            * 100,
                            2,
                        )
                    if prev["deduct_net_profit"] != 0:
                        reports[i]["deduct_net_profit_qoq"] = round(
                            (
                                (reports[i]["deduct_net_profit"] - prev["deduct_net_profit"])
                                / abs(prev["deduct_net_profit"])
                            )
                            * 100,
                            2,
                        )
    except Exception as e:
        logger.debug(f"Failed to fetch EastMoney ZYZB financials for {clean_code}: {e}")

    # Fallback to Sina if EastMoney returns empty
    if not reports:
        try:
            sc = SinaClient(timeout=5.0)
            df_lrb = sc.get_financial_report(clean_code, report_type="lrb")
            if df_lrb is not None and not df_lrb.empty:
                max_reports = min(4, len(df_lrb))
                for i in range(max_reports):
                    r = df_lrb.iloc[i]
                    period = str(r.get("报告期", ""))
                    period_title = _format_period_title(period)

                    rev_col = [c for c in df_lrb.columns if "营业总收入" in c and not c.endswith("_同比")]
                    rev_val = float(r[rev_col[0]]) if rev_col and r[rev_col[0]] is not None else 0.0
                    rev_yoy_col = [c for c in df_lrb.columns if "营业总收入_同比" in c]
                    rev_yoy = (
                        float(r[rev_yoy_col[0]]) * 100
                        if rev_yoy_col and r[rev_yoy_col[0]] is not None
                        else None
                    )

                    np_col = [c for c in df_lrb.columns if "归属于母公司" in c and not c.endswith("_同比")]
                    if not np_col:
                        np_col = [c for c in df_lrb.columns if "净利润" in c and not c.endswith("_同比")]
                    np_val = float(r[np_col[0]]) if np_col and r[np_col[0]] is not None else 0.0
                    np_yoy_col = [c for c in df_lrb.columns if "归属于母公司" in c and c.endswith("_同比")]
                    if not np_yoy_col:
                        np_yoy_col = [c for c in df_lrb.columns if "净利润_同比" in c]
                    np_yoy = (
                        float(r[np_yoy_col[0]]) * 100
                        if np_yoy_col and r[np_yoy_col[0]] is not None
                        else None
                    )

                    reports.append({
                        "period": period,
                        "period_title": period_title,
                        "revenue": rev_val,
                        "revenue_yi": (
                            round(rev_val / 100000000.0, 2)
                            if rev_val >= 100000000
                            else round(rev_val / 10000.0, 2)
                        ),
                        "revenue_unit": "亿" if rev_val >= 100000000 else "万",
                        "revenue_yoy": round(rev_yoy, 2) if rev_yoy is not None else None,
                        "net_profit": np_val,
                        "net_profit_wan": (
                            round(np_val / 10000.0, 2)
                            if abs(np_val) < 100000000
                            else None
                        ),
                        "net_profit_yi": (
                            round(np_val / 100000000.0, 2)
                            if abs(np_val) >= 100000000
                            else None
                        ),
                        "net_profit_yoy": round(np_yoy, 2) if np_yoy is not None else None,
                    })
        except Exception as e:
            logger.debug(f"Failed to fetch Sina financial fallback for {clean_code}: {e}")

    result["financials"] = reports

    # 5. Shareholder Counts History (Recent 4 Quarters, QoQ changes)
    # 三级弹性容灾获取体系：以通达信本地最新期（easy_tdx 通信接口）为第一选择
    sh_list = _fetch_shareholder_history(
        clean_code, pfx, mkt=mkt, tdx_data=result.get("shareholders")
    )
    result["shareholder_history"] = sh_list

    # Cache successful result
    with _CACHE_LOCK:
        _PROFILE_CACHE[cache_key] = (time.time(), copy.deepcopy(result))

    return result
