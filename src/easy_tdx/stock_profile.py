"""Stock Profile Service

Aggregates:
1. Shareholder counts & average shares per holder from TDX Finance
2. Company profile, legal person, main business from F10 survey
3. Belonging sectors and concept theme tags
4. Financial reports: Revenue, Net Profit, YoY, QoQ
"""

import json
import logging
import urllib.request
from typing import Any, Dict, List

from .client import TdxClient
from .models import Market
from .sina import SinaClient

logger = logging.getLogger(__name__)


def get_stock_full_profile(code: str) -> Dict[str, Any]:
    """Fetch complete stock profile including shareholders, company info, sectors, and financials."""
    clean_code = str(code).strip().upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    if clean_code.startswith("6") or clean_code.startswith("9"):
        mkt = Market.SH
        pfx = "SH"
    elif clean_code.startswith(("0", "3")):
        mkt = Market.SZ
        pfx = "SZ"
    else:
        mkt = Market.SH
        pfx = "SH"

    result: Dict[str, Any] = {
        "code": clean_code,
        "symbol": f"{clean_code}.{pfx}",
        "shareholders": {},
        "company_info": {},
        "sectors": [],
        "financials": []
    }

    # 1. Native TDX Finance Info (Shareholders, Capital, Listing date)
    try:
        cli = TdxClient()
        cli.connect()
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
                "total_shares_yi": round(zong_guben / 100000000.0, 2) if zong_guben >= 100000000 else round(zong_guben / 10000.0, 2),
                "float_shares_yi": round(liutong_guben / 100000000.0, 2) if liutong_guben >= 100000000 else round(liutong_guben / 10000.0, 2),
                "updated_date": up_date_fmt,
                "ipo_date": ipo_date_fmt,
                "nav_per_share": round(float(row.get("meigujing_zichan", 0)), 2),
            }
    except Exception as e:
        logger.debug(f"Failed to fetch TDX finance info for {clean_code}: {e}")

    # 2. Company Survey & Main Business (EastMoney F10)
    try:
        url_f10 = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={pfx}{clean_code}"
        req = urllib.request.Request(url_f10, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            jb = data.get("jbzl")
            if isinstance(jb, list) and jb:
                jb = jb[0]
            if isinstance(jb, dict):
                ind = jb.get("sshy", "") or jb.get("sszjhhy", "")
                business_text = jb.get("gsjj", "") or jb.get("jyfw", "") or ""
                business_clean = " ".join(business_text.strip().split())
                if len(business_clean) > 180:
                    business_clean = business_clean[:180] + "..."

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
        url_boards = f"https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_F10_CORETHEME_BOARDTYPE&columns=SECURITY_CODE,BOARD_CODE,BOARD_NAME,BOARD_TYPE&filter=(SECURITY_CODE%3D%22{clean_code}%22)"
        req_b = urllib.request.Request(url_boards, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req_b, timeout=4) as resp_b:
            data_b = json.loads(resp_b.read().decode("utf-8"))
            if data_b.get("result") and data_b["result"].get("data"):
                existing_names = {s["name"] for s in result["sectors"]}
                for b_item in data_b["result"]["data"]:
                    b_name = b_item.get("BOARD_NAME", "")
                    if b_name and b_name not in existing_names:
                        existing_names.add(b_name)
                        result["sectors"].append({
                            "name": b_name,
                            "type": b_item.get("BOARD_TYPE") or "概念"
                        })
    except Exception as e:
        logger.debug(f"Failed to fetch concept boards for {clean_code}: {e}")

    # 4. Sina Financial Reports (Revenue, Net Profit, YoY, QoQ)
    try:
        sc = SinaClient(timeout=4.0)
        df_lrb = sc.get_financial_report(clean_code, report_type="lrb")
        if df_lrb is not None and not df_lrb.empty:
            reports: List[Dict[str, Any]] = []
            max_reports = min(4, len(df_lrb))
            for i in range(max_reports):
                r = df_lrb.iloc[i]
                period = str(r.get("报告期", ""))
                
                period_title = period
                if "-03-31" in period:
                    period_title = f"{period[:4]}一季报"
                elif "-06-30" in period:
                    period_title = f"{period[:4]}中报"
                elif "-09-30" in period:
                    period_title = f"{period[:4]}三季报"
                elif "-12-31" in period:
                    period_title = f"{period[:4]}年报"

                # Revenue column
                rev_col = [c for c in df_lrb.columns if "营业总收入" in c and not c.endswith("_同比")]
                rev_val = float(r[rev_col[0]]) if rev_col and r[rev_col[0]] is not None else 0.0
                
                rev_yoy_col = [c for c in df_lrb.columns if "营业总收入_同比" in c]
                rev_yoy = float(r[rev_yoy_col[0]]) * 100 if rev_yoy_col and r[rev_yoy_col[0]] is not None else None
                
                # Net Profit column
                np_col = [c for c in df_lrb.columns if "归属于母公司" in c and not c.endswith("_同比")]
                if not np_col:
                    np_col = [c for c in df_lrb.columns if "净利润" in c and not c.endswith("_同比")]
                np_val = float(r[np_col[0]]) if np_col and r[np_col[0]] is not None else 0.0
                
                np_yoy_col = [c for c in df_lrb.columns if "归属于母公司" in c and c.endswith("_同比")]
                if not np_yoy_col:
                    np_yoy_col = [c for c in df_lrb.columns if "净利润_同比" in c]
                np_yoy = float(r[np_yoy_col[0]]) * 100 if np_yoy_col and r[np_yoy_col[0]] is not None else None
                
                # QoQ (compared with previous report in list, i.e. index i+1)
                rev_qoq = None
                np_qoq = None
                if i + 1 < len(df_lrb):
                    prev_r = df_lrb.iloc[i + 1]
                    prev_rev = float(prev_r[rev_col[0]]) if rev_col and prev_r[rev_col[0]] is not None else None
                    if prev_rev and prev_rev > 0:
                        rev_qoq = round(((rev_val - prev_rev) / prev_rev) * 100, 2)
                    
                    prev_np = float(prev_r[np_col[0]]) if np_col and prev_r[np_col[0]] is not None else None
                    if prev_np and prev_np != 0:
                        np_qoq = round(((np_val - prev_np) / abs(prev_np)) * 100, 2)

                reports.append({
                    "period": period,
                    "period_title": period_title,
                    "revenue": rev_val,
                    "revenue_yi": round(rev_val / 100000000.0, 2) if rev_val >= 100000000 else round(rev_val / 10000.0, 2),
                    "revenue_unit": "亿" if rev_val >= 100000000 else "万",
                    "revenue_yoy": round(rev_yoy, 2) if rev_yoy is not None else None,
                    "revenue_qoq": rev_qoq,
                    "net_profit": np_val,
                    "net_profit_wan": round(np_val / 10000.0, 2),
                    "net_profit_yi": round(np_val / 100000000.0, 2),
                    "net_profit_yoy": round(np_yoy, 2) if np_yoy is not None else None,
                    "net_profit_qoq": np_qoq,
                })
            result["financials"] = reports
    except Exception as e:
        logger.debug(f"Failed to fetch Sina financial reports for {clean_code}: {e}")

    # 5. Shareholder Counts History (Recent 4 Quarters, QoQ changes)
    result["shareholder_history"] = []
    try:
        url_sh_hist = f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code={pfx}{clean_code}"
        req_sh = urllib.request.Request(url_sh_hist, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req_sh, timeout=4) as resp_sh:
            data_sh = json.loads(resp_sh.read().decode("utf-8"))
            gdrs = data_sh.get("gdrs", [])
            sh_list: List[Dict[str, Any]] = []
            for g in gdrs[:4]:
                end_date = str(g.get("END_DATE", ""))[:10]
                title = end_date
                if "-03-31" in end_date:
                    title = f"{end_date[:4]}一季报"
                elif "-06-30" in end_date:
                    title = f"{end_date[:4]}中报"
                elif "-09-30" in end_date:
                    title = f"{end_date[:4]}三季报"
                elif "-12-31" in end_date:
                    title = f"{end_date[:4]}年报"
                
                sh_list.append({
                    "period": end_date,
                    "period_title": title,
                    "holder_count": g.get("HOLDER_TOTAL_NUM"),
                    "holder_qoq": round(float(g.get("TOTAL_NUM_RATIO")), 2) if g.get("TOTAL_NUM_RATIO") is not None else None,
                    "avg_shares": g.get("AVG_FREE_SHARES"),
                    "avg_shares_wan": round(float(g.get("AVG_FREE_SHARES")) / 10000.0, 2) if g.get("AVG_FREE_SHARES") is not None else None,
                    "avg_shares_qoq": round(float(g.get("AVG_FREESHARES_RATIO")), 2) if g.get("AVG_FREESHARES_RATIO") is not None else None,
                    "avg_hold_amt_wan": round(float(g.get("AVG_HOLD_AMT")) / 10000.0, 2) if g.get("AVG_HOLD_AMT") is not None else None,
                    "focus": g.get("HOLD_FOCUS") or "--"
                })
            result["shareholder_history"] = sh_list
    except Exception as e:
        logger.debug(f"Failed to fetch shareholder history for {clean_code}: {e}")

    return result

