"""Stock Profile Service

Aggregates complete stock financial & profile data with a resilient 4-tier multi-source fallback:
1. Shareholder counts & average shares per holder:
   - Tier 1: Native TDX get_finance_info (Primary local source)
   - Tier 2: EastMoney DataCenter open API & PageAjax API (with compliant Referer)
   - Tier 3: Tonghuashun (10jqka) F10 holder table parser
2. Company survey, legal person, main business, registered capital:
   - Tier 1: EastMoney CompanySurveyAjax (with compliant Referer)
   - Tier 2: Tonghuashun (10jqka) F10 company.html parser
   - Tier 3: Sina CorpInfo parser
   - Tier 4: Native TDX F10 text & get_finance_info
3. Belonging sectors and concept theme tags:
   - Tier 1: EastMoney CoreTheme BoardType API (with compliant Referer)
   - Tier 2: Tonghuashun (10jqka) concept.html parser
   - Tier 3: Native TDX F10 concept section parser
4. Financial reports (Recent 4~8 quarters: Revenue, Net Profit, Deducted Profit, YoY, QoQ):
   - Tier 1: EastMoney ZYZBAjaxNew API (with compliant Referer)
   - Tier 2: SinaClient get_financial_report (LRB income statement with YoY/QoQ)
   - Tier 3: Trading system engine fetch_stock_financials
   - Tier 4: Native TDX get_finance_info with unit-scale correction
"""

from __future__ import annotations

import copy
import gzip
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

# In-memory TTL cache: key -> (timestamp, data, is_rich)
_PROFILE_CACHE: Dict[str, Tuple[float, Dict[str, Any], bool]] = {}
_CACHE_TTL = 1800  # 30 minutes for complete rich profiles
_CACHE_TTL_DEGRADED = 10  # 10 seconds for degraded profiles to allow quick retry
_CACHE_LOCK = Lock()

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "close",
}

_EASTMONEY_EMWEB_HEADERS = {
    **_DEFAULT_HEADERS,
    "Referer": "https://emweb.securities.eastmoney.com/",
}

_EASTMONEY_DATA_HEADERS = {
    **_DEFAULT_HEADERS,
    "Referer": "https://data.eastmoney.com/",
}

_SINA_HEADERS = {
    **_DEFAULT_HEADERS,
    "Referer": "https://finance.sina.com.cn/",
}

_THS_HEADERS = {
    **_DEFAULT_HEADERS,
    "Referer": "http://basic.10jqka.com.cn/",
}


def _read_response_text(resp, default_encoding: str = "utf-8") -> str:
    """Safely read HTTP response bytes with automatic gzip decompression support."""
    raw = resp.read()
    if raw[:2] == b"\x1f\x8b" or resp.headers.get("Content-Encoding") == "gzip":
        try:
            return gzip.decompress(raw).decode(default_encoding, errors="replace")
        except Exception:
            return raw.decode(default_encoding, errors="replace")
    return raw.decode(default_encoding, errors="replace")


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
    """Format 'YYYY-MM-DD' into readable report period (e.g. '2026中报')."""
    d = str(end_date)[:10]
    if "-03-31" in d:
        return f"{d[:4]}一季报"
    elif "-06-30" in d:
        return f"{d[:4]}中报"
    elif "-09-30" in d:
        return f"{d[:4]}三季报"
    elif "-12-31" in d:
        return f"{d[:4]}年报"
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


# ==================== 1. 股东户数历史四级容灾 ====================

def _fetch_shareholder_history_datacenter(clean_code: str) -> List[Dict[str, Any]]:
    """Tier 1: EastMoney DataCenter open API (with compliant Referer)."""
    url = (
        f"https://datacenter.eastmoney.com/securities/api/data/v1/get?"
        f"reportName=RPT_F10_EH_HOLDERNUM&filter=(SECURITY_CODE%3D%22{clean_code}%22)"
        f"&columns=SECUCODE,SECURITY_CODE,END_DATE,HOLDER_TOTAL_NUM,TOTAL_NUM_RATIO,"
        f"AVG_FREE_SHARES,AVG_FREESHARES_RATIO,HOLD_FOCUS,AVG_HOLD_AMT"
        f"&sortColumns=END_DATE&sortTypes=-1&pageNumber=1&pageSize=8"
    )
    req = urllib.request.Request(url, headers=_EASTMONEY_DATA_HEADERS)
    with urllib.request.urlopen(req, timeout=4) as resp:
        data = json.loads(_read_response_text(resp))
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
    """Tier 2: EastMoney PC_HSF10 PageAjax API (with compliant Referer)."""
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code={pfx}{clean_code}"
    req = urllib.request.Request(url, headers=_EASTMONEY_EMWEB_HEADERS)
    with urllib.request.urlopen(req, timeout=4) as resp:
        data = json.loads(_read_response_text(resp))
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
    """Tier 3: Tonghuashun (10jqka) F10 holder table parser."""
    url = f"http://basic.10jqka.com.cn/{clean_code}/holder.html"
    req = urllib.request.Request(url, headers=_THS_HEADERS)
    with urllib.request.urlopen(req, timeout=4) as resp:
        html = _read_response_text(resp, default_encoding="gbk")

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
        try:
            from easy_tdx.market_data import _get_or_create_client, _CLIENT_LOCK
            with _CLIENT_LOCK:
                cli = _get_or_create_client()
                df = cli.get_finance_info(mkt, clean_code)
        except Exception:
            with TdxClient.from_best_host(timeout=2.0) as cli:
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
    """四级弹性容灾股东户数历史架构：
    - Tier 1 (本地首选源): 通达信本地最新期（easy_tdx 通信接口）
    - Tier 2 (官方开放源): 东方财富 DataCenter / PageAjax API
    - Tier 3 (综合资讯源): 同花顺 10jqka 股东变动解析
    - 智能融合：保留最新期，重算真实 QoQ 环比变动
    """
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

    if not ext_records:
        try:
            ext_records = _fetch_shareholder_history_ths(clean_code)
        except Exception as e:
            logger.debug(f"Shareholder Tier 3 (THS) failed for {clean_code}: {e}")

    records: List[Dict[str, Any]] = []
    if tdx_latest and ext_records:
        tdx_period = tdx_latest["period"]
        ext_latest_period = ext_records[0]["period"]

        if tdx_period == ext_latest_period or (
            tdx_period[:4] == ext_latest_period[:4]
            and _format_period_title(tdx_period) == _format_period_title(ext_latest_period)
        ):
            merged_latest = copy.deepcopy(ext_records[0])
            merged_latest["holder_count"] = tdx_latest["holder_count"]
            if tdx_latest.get("avg_shares"):
                merged_latest["avg_shares"] = tdx_latest["avg_shares"]
                merged_latest["avg_shares_wan"] = tdx_latest["avg_shares_wan"]
            merged_latest["source"] = "easy_tdx"
            records = [merged_latest] + ext_records[1:]
        elif tdx_period > ext_latest_period:
            records = [tdx_latest] + ext_records
        else:
            records = ext_records
    elif tdx_latest and not ext_records:
        records = [tdx_latest]
    else:
        records = ext_records

    # 重算 QoQ 环比
    if records:
        for i in range(len(records)):
            if i + 1 < len(records):
                prev = records[i + 1]
                curr_h = records[i].get("holder_count")
                prev_h = prev.get("holder_count")
                if curr_h and prev_h and prev_h > 0:
                    records[i]["holder_qoq"] = round(((curr_h - prev_h) / prev_h) * 100, 2)

                curr_ash = records[i].get("avg_shares")
                prev_ash = prev.get("avg_shares")
                if curr_ash and prev_ash and prev_ash > 0:
                    records[i]["avg_shares_qoq"] = round(((curr_ash - prev_ash) / prev_ash) * 100, 2)

    return records[:4]


# ==================== 2. 公司档案与主营业务多源补全 ====================

def _fetch_company_info(
    clean_code: str,
    pfx: str,
    mkt: Market,
    tdx_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """四级弹性容灾获取公司档案与主营业务：
    - Tier 1: 东方财富 PC_HSF10 CompanySurveyAjax (带合规 Referer)
    - Tier 2: 同花顺 10jqka company.html (公司资料深度解析)
    - Tier 3: 新浪财经 vCI_CorpInfo (公司概况解析)
    - Tier 4: 通达信本地 F10 文本及财务基础库
    """
    comp: Dict[str, Any] = {}

    # Tier 1: EastMoney CompanySurveyAjax
    try:
        url_f10 = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={pfx}{clean_code}"
        req = urllib.request.Request(url_f10, headers=_EASTMONEY_EMWEB_HEADERS)
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(_read_response_text(resp))
            jb = data.get("jbzl")
            if isinstance(jb, list) and jb:
                jb = jb[0]
            if isinstance(jb, dict) and jb.get("gsmc"):
                ind = jb.get("sshy", "") or jb.get("sszjhhy", "")
                business_text = jb.get("gsjj", "") or jb.get("jyfw", "") or ""
                comp = {
                    "org_name": jb.get("gsmc", ""),
                    "industry": ind,
                    "province": jb.get("qy", ""),
                    "legal_person": jb.get("frdb", "") or jb.get("dsz", ""),
                    "general_manager": jb.get("zjl", ""),
                    "registered_capital": jb.get("zczb", ""),
                    "main_business": " ".join(business_text.strip().split()),
                }
    except Exception as e:
        logger.debug(f"Company Info Tier 1 (EastMoney) failed for {clean_code}: {e}")

    # Tier 2: THS Company Info Fallback
    if not comp or not comp.get("main_business"):
        try:
            url_ths = f"http://basic.10jqka.com.cn/{clean_code}/company.html"
            req_ths = urllib.request.Request(url_ths, headers=_THS_HEADERS)
            with urllib.request.urlopen(req_ths, timeout=4) as resp:
                html = _read_response_text(resp, default_encoding="gbk")

            org_m = re.search(r"公司名称：</strong><span>([^<]+)</span>", html)
            prov_m = re.search(r"所属地域：</strong><span>([^<]+)</span>", html)
            ind_m = re.search(r"所属申万行业：</strong><span>([^<]+)</span>", html)
            biz_m = re.search(r"主营业务：</strong>\s*<span>([^<]+)</span>", html)
            legal_m = re.search(r"法人代表：</strong>\s*<span>\s*(?:<[^>]+>)?([^<]+)", html)

            if org_m or biz_m:
                comp = {
                    "org_name": org_m.group(1).strip() if org_m else comp.get("org_name", ""),
                    "industry": ind_m.group(1).strip().replace(" — ", "/") if ind_m else comp.get("industry", ""),
                    "province": prov_m.group(1).strip() if prov_m else comp.get("province", ""),
                    "legal_person": legal_m.group(1).strip() if legal_m else comp.get("legal_person", ""),
                    "general_manager": comp.get("general_manager", ""),
                    "registered_capital": comp.get("registered_capital", ""),
                    "main_business": " ".join((biz_m.group(1).strip() if biz_m else "").split()) or comp.get("main_business", ""),
                }
        except Exception as e:
            logger.debug(f"Company Info Tier 2 (THS) failed for {clean_code}: {e}")

    # Tier 3: Sina CorpInfo Fallback
    if not comp or not comp.get("main_business"):
        try:
            url_sina = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{clean_code}.phtml"
            req_s = urllib.request.Request(url_sina, headers=_SINA_HEADERS)
            with urllib.request.urlopen(req_s, timeout=4) as resp:
                html_s = _read_response_text(resp, default_encoding="gbk")

            def _get_sina_field(pat: str) -> str:
                m = re.search(pat, html_s, re.DOTALL)
                return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""

            org_s = _get_sina_field(r"公司名称：</td>\s*<td[^>]*>(.*?)</td>")
            biz_s = _get_sina_field(r"主营业务：</td>\s*<td[^>]*>(.*?)</td>")
            intro_s = _get_sina_field(r"公司简介：</td>\s*<td[^>]*>(.*?)</td>")
            addr_s = _get_sina_field(r"办公地址：</td>\s*<td[^>]*>(.*?)</td>")

            if org_s or biz_s:
                comp = {
                    "org_name": org_s or comp.get("org_name", ""),
                    "industry": comp.get("industry", ""),
                    "province": (addr_s[:6] if addr_s else "") or comp.get("province", ""),
                    "legal_person": comp.get("legal_person", ""),
                    "general_manager": comp.get("general_manager", ""),
                    "registered_capital": comp.get("registered_capital", ""),
                    "main_business": biz_s or intro_s or comp.get("main_business", ""),
                }
        except Exception as e:
            logger.debug(f"Company Info Tier 3 (Sina) failed for {clean_code}: {e}")

    # Tier 4: Native TDX F10 Text Fallback
    if not comp or not comp.get("main_business"):
        try:
            with TdxClient.from_best_host(timeout=2.5) as cli:
                cats = cli.get_company_info_category(mkt, clean_code)
                if cats is not None and not cats.empty:
                    r0 = cats.iloc[0]
                    txt = cli.get_company_info_content(
                        mkt, clean_code, r0["filename"], int(r0["start"]), int(r0["length"])
                    )
                    m_biz = re.search(r"★主营业务[:：]([^\n｜]+)", txt)
                    if m_biz:
                        biz_tdx = m_biz.group(1).strip()
                        comp["main_business"] = biz_tdx
        except Exception as e:
            logger.debug(f"Company Info Tier 4 (TDX F10) failed for {clean_code}: {e}")

    return comp


# ==================== 3. 所属板块与题材多源补全 ====================

def _fetch_stock_sectors(
    clean_code: str,
    pfx: str,
    mkt: Market,
    company_info: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """四级弹性容灾获取所属板块与题材：
    - Tier 1: 东方财富核心题材 RPT_F10_CORETHEME_BOARDTYPE (带合规 Referer)
    - Tier 2: 同花顺 10jqka 概念板块解析 (concept.html)
    - Tier 3: 通达信原生 F10 概念板块解析
    - 自动聚合行业标签与题材概念，纯净去重
    """
    sectors: List[Dict[str, str]] = []
    existing_names = set()

    # 优先加入行业标签
    if company_info and company_info.get("industry"):
        ind = company_info["industry"]
        for part in re.split(r"[/—\-]", ind):
            p = part.strip()
            if p and p not in existing_names:
                existing_names.add(p)
                sectors.append({"name": p, "type": "行业"})

    # Tier 1: EastMoney Core Concepts
    try:
        url_boards = (
            f"https://datacenter.eastmoney.com/securities/api/data/v1/get?"
            f"reportName=RPT_F10_CORETHEME_BOARDTYPE&columns=SECURITY_CODE,BOARD_CODE,BOARD_NAME,BOARD_TYPE"
            f"&filter=(SECURITY_CODE%3D%22{clean_code}%22)"
        )
        req_b = urllib.request.Request(url_boards, headers=_EASTMONEY_DATA_HEADERS)
        with urllib.request.urlopen(req_b, timeout=4) as resp_b:
            data_b = json.loads(_read_response_text(resp_b))
            if data_b.get("result") and data_b["result"].get("data"):
                for b_item in data_b["result"]["data"]:
                    b_name = b_item.get("BOARD_NAME", "")
                    if b_name and b_name not in existing_names:
                        existing_names.add(b_name)
                        sectors.append({
                            "name": b_name,
                            "type": b_item.get("BOARD_TYPE") or "概念",
                        })
    except Exception as e:
        logger.debug(f"Sectors Tier 1 (EastMoney) failed for {clean_code}: {e}")

    # Tier 2: THS Concepts Fallback
    if len(sectors) <= 1:
        try:
            url_ths_concept = f"http://basic.10jqka.com.cn/{clean_code}/concept.html"
            req_c = urllib.request.Request(url_ths_concept, headers=_THS_HEADERS)
            with urllib.request.urlopen(req_c, timeout=4) as resp_c:
                html_c = _read_response_text(resp_c, default_encoding="gbk")
            raw_names = re.findall(r"<td[^>]*class=[\'\"]gnName[\'\"][^>]*>(.*?)</td>", html_c, re.DOTALL)
            for x in raw_names:
                c_name = re.sub(r"<[^>]+>", "", x).strip()
                if c_name and c_name not in existing_names:
                    existing_names.add(c_name)
                    sectors.append({"name": c_name, "type": "概念"})
        except Exception as e:
            logger.debug(f"Sectors Tier 2 (THS) failed for {clean_code}: {e}")

    # Tier 3: Native TDX F10 Concepts Fallback
    if len(sectors) <= 1:
        try:
            with TdxClient.from_best_host(timeout=2.5) as cli:
                cats = cli.get_company_info_category(mkt, clean_code)
                if cats is not None and not cats.empty:
                    r0 = cats.iloc[0]
                    txt = cli.get_company_info_content(
                        mkt, clean_code, r0["filename"], int(r0["start"]), int(r0["length"])
                    )
                    c_idx = txt.find("【3.概念板块】")
                    if c_idx == -1:
                        c_idx = txt.find("【概念板块】")
                    if c_idx != -1:
                        part = txt[c_idx : c_idx + 4000]
                        for m in re.finditer(r"｜\s*([^\s｜\n]+(?:概念|[^\s｜\n]{2,8}))\s*｜", part):
                            cname = m.group(1).strip()
                            if cname and cname not in ("概念名称", "概念解析") and cname not in existing_names:
                                existing_names.add(cname)
                                sectors.append({"name": cname, "type": "概念"})
        except Exception as e:
            logger.debug(f"Sectors Tier 3 (TDX F10) failed for {clean_code}: {e}")

    return sectors


# ==================== 4. 财务指标（近4期）多源补全 ====================

def _fetch_stock_financials(
    clean_code: str,
    pfx: str,
    mkt: Market,
    tdx_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """四级弹性容灾获取近4期核心财务指标（营收、净利润、扣非净利、同比与环比）：
    - Tier 1: 东方财富 ZYZBAjaxNew (带合规 Referer)
    - Tier 2: 新浪财经 SinaClient (官方利润表接口，带同比与环比)
    - Tier 3: 量化引擎 fetch_stock_financials 接口
    - Tier 4: 通达信原生 get_finance_info（修复单位倍率）
    """
    reports: List[Dict[str, Any]] = []

    # Tier 1: EastMoney ZYZBAjaxNew
    try:
        url_fin = f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew?type=0&code={pfx}{clean_code}"
        req_fin = urllib.request.Request(url_fin, headers=_EASTMONEY_EMWEB_HEADERS)
        with urllib.request.urlopen(req_fin, timeout=4) as resp_fin:
            raw_fin = _read_response_text(resp_fin)
            data_fin = json.loads(raw_fin).get("data", [])
            for d in data_fin[:4]:
                rep_date = str(d.get("REPORT_DATE", ""))[:10]
                rep_title = d.get("REPORT_DATE_NAME") or _format_period_title(rep_date)

                rev_val = float(d.get("TOTALOPERATEREVE") or 0.0)
                rev_yoy = (
                    float(d["TOTALOPERATEREVETZ"])
                    if d.get("TOTALOPERATEREVETZ") is not None
                    else None
                )

                np_val = float(d.get("PARENTNETPROFIT") or 0.0)
                np_yoy = (
                    float(d["PARENTNETPROFITTZ"])
                    if d.get("PARENTNETPROFITTZ") is not None
                    else None
                )

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
    except Exception as e:
        logger.debug(f"Financials Tier 1 (EastMoney) failed for {clean_code}: {e}")

    # Tier 2: SinaClient LRB Fallback
    if not reports:
        try:
            sc = SinaClient(timeout=4.0)
            df_lrb = sc.get_financial_report(clean_code, report_type="lrb", num=4)
            if df_lrb is not None and not df_lrb.empty:
                for idx, r in df_lrb.iterrows():
                    period = str(r.get("报告期", ""))[:10]
                    rev = float(r.get("营业总收入") or r.get("营业收入") or 0.0)
                    np_val = float(r.get("归属于母公司所有者的净利润") or r.get("净利润") or 0.0)

                    rev_yoy_col = r.get("营业总收入_同比") or r.get("营业收入_同比")
                    rev_yoy = float(rev_yoy_col) * 100.0 if rev_yoy_col is not None else None

                    np_yoy_col = r.get("归属于母公司所有者的净利润_同比") or r.get("净利润_同比")
                    np_yoy = float(np_yoy_col) * 100.0 if np_yoy_col is not None else None

                    reports.append({
                        "period": period,
                        "period_title": _format_period_title(period),
                        "revenue": rev,
                        "revenue_yi": (
                            round(rev / 100000000.0, 2)
                            if rev >= 100000000
                            else round(rev / 10000.0, 2)
                        ),
                        "revenue_unit": "亿" if rev >= 100000000 else "万",
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
                        "deduct_net_profit": 0.0,
                        "deduct_net_profit_wan": None,
                        "deduct_net_profit_yi": None,
                        "deduct_net_profit_yoy": None,
                    })
        except Exception as e:
            logger.debug(f"Financials Tier 2 (Sina) failed for {clean_code}: {e}")

    # Tier 3: Engine fetch_stock_financials Fallback
    if not reports:
        try:
            from easy_tdx.trading_system.engine import fetch_stock_financials
            fina_res = fetch_stock_financials(clean_code)
            f_list = fina_res.get("fina_data") or []
            for f in f_list[:4]:
                p_date = str(f.get("record_date") or "")[:10]
                p_title = str(f.get("qdate") or _format_period_title(p_date))
                r_val = float(f.get("total_operate_income") or 0.0)
                n_val = float(f.get("parent_netprofit") or 0.0)
                # Correct TDX 10x scaling if raw pytdx unit detected
                if r_val > 10000000000:
                    r_val /= 10.0
                if abs(n_val) > 1000000000:
                    n_val /= 10.0

                r_yoy = f.get("ystz")
                n_yoy = f.get("sjltz")
                reports.append({
                    "period": p_date,
                    "period_title": p_title,
                    "revenue": r_val,
                    "revenue_yi": round(r_val / 100000000.0, 2) if r_val >= 100000000 else round(r_val / 10000.0, 2),
                    "revenue_unit": "亿" if r_val >= 100000000 else "万",
                    "revenue_yoy": round(float(r_yoy), 2) if r_yoy is not None else None,
                    "net_profit": n_val,
                    "net_profit_wan": round(n_val / 10000.0, 2) if abs(n_val) < 100000000 else None,
                    "net_profit_yi": round(n_val / 100000000.0, 2) if abs(n_val) >= 100000000 else None,
                    "net_profit_yoy": round(float(n_yoy), 2) if n_yoy is not None else None,
                    "deduct_net_profit": 0.0,
                    "deduct_net_profit_wan": None,
                    "deduct_net_profit_yi": None,
                    "deduct_net_profit_yoy": None,
                })
        except Exception as e:
            logger.debug(f"Financials Tier 3 (Engine) failed for {clean_code}: {e}")

    # 计算环比 (QoQ)
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
                    ((reports[i]["net_profit"] - prev["net_profit"]) / abs(prev["net_profit"])) * 100,
                    2,
                )
            if reports[i].get("deduct_net_profit") and prev.get("deduct_net_profit"):
                reports[i]["deduct_net_profit_qoq"] = round(
                    ((reports[i]["deduct_net_profit"] - prev["deduct_net_profit"]) / abs(prev["deduct_net_profit"])) * 100,
                    2,
                )

    return reports[:4]


# ==================== 主入口：聚合完整股票资料 ====================

def get_stock_full_profile(code: str, use_cache: bool = True) -> Dict[str, Any]:
    """Fetch complete stock profile including shareholders, company info, sectors, and financials."""
    clean_code, mkt, pfx, is_index_or_board = _parse_stock_symbol(code)
    cache_key = clean_code

    if use_cache:
        with _CACHE_LOCK:
            if cache_key in _PROFILE_CACHE:
                ts, cached_result, is_rich = _PROFILE_CACHE[cache_key]
                ttl = _CACHE_TTL if is_rich else _CACHE_TTL_DEGRADED
                if time.time() - ts < ttl:
                    return dict(cached_result)

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
            _PROFILE_CACHE[cache_key] = (time.time(), copy.deepcopy(result), True)
        return result

    # 1. Native TDX Finance Info (Shareholders, Capital, Listing date)
    try:
        try:
            from easy_tdx.market_data import _get_or_create_client, _CLIENT_LOCK
            with _CLIENT_LOCK:
                cli = _get_or_create_client()
                f = cli.get_finance_info(mkt, clean_code)
        except Exception:
            with TdxClient.from_best_host(timeout=2.0) as cli:
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

    # 2. Company Info (4-Tier Fallback)
    result["company_info"] = _fetch_company_info(
        clean_code, pfx, mkt, tdx_data=result.get("shareholders")
    )

    # 3. Sectors & Concepts (4-Tier Fallback)
    result["sectors"] = _fetch_stock_sectors(
        clean_code, pfx, mkt, company_info=result.get("company_info")
    )

    # 4. Financial Reports (4-Tier Fallback)
    result["financials"] = _fetch_stock_financials(
        clean_code, pfx, mkt, tdx_data=result.get("shareholders")
    )

    # 5. Shareholder History (4-Tier Fallback)
    result["shareholder_history"] = _fetch_shareholder_history(
        clean_code, pfx, mkt=mkt, tdx_data=result.get("shareholders")
    )

    # Smart Cache: Only cache for 30 minutes if rich and complete; otherwise 10 seconds
    is_rich = bool(
        result["financials"]
        and len(result["financials"]) >= 2
        and result["sectors"]
        and result["company_info"]
        and result["company_info"].get("main_business")
    )

    with _CACHE_LOCK:
        _PROFILE_CACHE[cache_key] = (time.time(), copy.deepcopy(result), is_rich)

    return result
