"""Capital Flow (资金监控) Scanner & Strategy Analysis Router for easy_tdx."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query

from easy_tdx.trading_system.engine import evaluate_universe
from easy_tdx.watchlist_store import load_watchlist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fundflow", tags=["fundflow"])


def _fmt_money(val: float) -> str:
    """Format money value to readable text with 万亿 / 亿 / 万 units."""
    abs_v = abs(val)
    sign = "+" if val > 0 else ("-" if val < 0 else "")
    if abs_v >= 1_000_000_000_000:
        return f"{sign}{abs_v / 1_000_000_000_000:.2f}万亿"
    elif abs_v >= 100_000_000:
        return f"{sign}{abs_v / 100_000_000:.2f}亿"
    elif abs_v >= 10_000:
        return f"{sign}{abs_v / 10_000:.2f}万"
    else:
        return f"{sign}{abs_v:.0f}元"


@router.get("/scanner")
def scan_fund_flow(
    strategy: str = Query("all", description="策略筛选: all, latent_breakout, sector_leader, closing_surge, heavy_institution, oversold_reversal"),
    min_inflow: float = Query(0.0, description="最低主力净流入金额(元)"),
    industry: str = Query("", description="行业板块过滤"),
    search: str = Query("", description="代码或名称搜索关键词"),
    sort_col: str = Query("dde_net", description="排序字段: dde_net, dde_ratio, consec_days, consec_amount, pct, amount, t_rate, v_rate"),
    sort_dir: str = Query("desc", description="排序方向: desc, asc"),
    limit: int = Query(200, ge=1, le=500, description="返回最大数量"),
    force_refresh: bool = Query(False, description="是否强制刷新最新数据"),
) -> Dict[str, Any]:
    """
    资金监控核心策略扫描：
    - 策略一：主力潜伏蓄势突破 (latent_breakout)
    - 策略二：板块集群龙头先锋 (sector_leader)
    - 策略三：尾盘抢筹次日溢价 (closing_surge)
    - 策略四：机构重度介入建仓 (heavy_institution)
    - 策略五：超跌资金抄底共振 (oversold_reversal)
    """
    # Safe normalization of parameters
    strat_key = (strategy if isinstance(strategy, str) else getattr(strategy, "default", "all") or "all").strip().lower()
    min_inf = float(min_inflow if isinstance(min_inflow, (int, float)) else getattr(min_inflow, "default", 0.0) or 0.0)
    ind_filter = (industry if isinstance(industry, str) else getattr(industry, "default", "") or "").strip()
    search_kw = (search if isinstance(search, str) else getattr(search, "default", "") or "").strip().upper()
    sort_c = (sort_col if isinstance(sort_col, str) else getattr(sort_col, "default", "dde_net") or "dde_net")
    sort_d = (sort_dir if isinstance(sort_dir, str) else getattr(sort_dir, "default", "desc") or "desc")
    lim = int(limit if isinstance(limit, (int, float)) else getattr(limit, "default", 200) or 200)
    force_ref = bool(force_refresh if isinstance(force_refresh, bool) else getattr(force_refresh, "default", False))

    try:
        stocks = evaluate_universe(universe_type="all", period="day", force_refresh=force_ref)
    except Exception as e:
        logger.error(f"Error evaluating universe for fundflow: {e}")
        return {"success": False, "error": str(e), "rows": [], "summary": {}}

    try:
        wl_set = set(load_watchlist())
    except Exception:
        wl_set = set()

    # Strategy definition configuration
    STRAT_META = {
        "latent_breakout": {
            "name": "主力潜伏蓄势",
            "badge_class": "bg-indigo-50 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-700/80",
            "icon": "sparkles",
        },
        "sector_leader": {
            "name": "板块龙头先锋",
            "badge_class": "bg-amber-50 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-700/80",
            "icon": "crown",
        },
        "closing_surge": {
            "name": "尾盘抢筹溢价",
            "badge_class": "bg-rose-50 dark:bg-rose-950/80 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-700/80",
            "icon": "zap",
        },
        "heavy_institution": {
            "name": "机构重度建仓",
            "badge_class": "bg-purple-50 dark:bg-purple-950/80 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-700/80",
            "icon": "building",
        },
        "oversold_reversal": {
            "name": "超跌资金抄底",
            "badge_class": "bg-emerald-50 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-700/80",
            "icon": "trending-up",
        },
    }

    strategy_counts = {k: 0 for k in STRAT_META}
    strategy_counts["all"] = 0

    record_date = str(stocks[0].get("record_date") or "").strip() if stocks else ""

    total_market_turnover = 0.0
    total_net_inflow = 0.0
    inflow_count = 0
    outflow_count = 0
    flat_count = 0
    consec_inflow_count = 0
    sector_inflow_map: Dict[str, float] = {}

    processed_rows: List[Dict[str, Any]] = []

    for s in stocks:
        code = str(s.get("stock_code") or "").strip()
        name = str(s.get("stock_name") or code).strip()
        close = float(s.get("close") or 0.0)
        open_p = float(s.get("open") or close)
        high = float(s.get("high") or close)
        low = float(s.get("low") or close)
        pct = float(s.get("pct") or 0.0)
        amt = float(s.get("amount") or 0.0)
        dde_net = float(s.get("dde_net") or 0.0)
        c_days = int(s.get("consec_days") or 0)
        c_amt = float(s.get("consec_amount") or 0.0)
        t_rate = float(s.get("t_rate") or 0.0)
        v_rate = float(s.get("v_rate") or 0.0)
        ind = str(s.get("industry") or "其他").strip() or "其他"
        b_code = str(s.get("board_code") or "").strip()
        patterns = s.get("pattern_names") or []

        total_market_turnover += amt
        total_net_inflow += dde_net
        if dde_net > 0:
            inflow_count += 1
        elif dde_net < 0:
            outflow_count += 1
        else:
            flat_count += 1
        if c_days >= 2:
            consec_inflow_count += 1

        sector_inflow_map[ind] = sector_inflow_map.get(ind, 0.0) + dde_net

        dde_ratio = round((dde_net / amt * 100.0), 2) if amt > 0 else 0.0

        # Match strategies
        matched_strats = []
        reasons = []

        # 1. 主力潜伏蓄势突破 (Latent Breakout)
        # 条件：连续2天以上净流入或累计超2000万，换手率1.2%~12%健康，量比良好蓄势放量，涨幅未过大
        if (c_days >= 2 or (c_amt >= 20_000_000 and dde_net > 0)) and (1.2 <= t_rate <= 12.0) and (v_rate >= 1.1) and (0.8 <= pct <= 8.5):
            matched_strats.append({
                "id": "latent_breakout",
                "name": STRAT_META["latent_breakout"]["name"],
                "badge": STRAT_META["latent_breakout"]["badge_class"],
            })
            strategy_counts["latent_breakout"] += 1
            reasons.append(f"主力连续{c_days}天净流入(累计{_fmt_money(c_amt)})，换手率{t_rate:.1f}%温和，蓄势突破")

        # 2. 板块集群龙头先锋 (Sector Leader)
        # 条件：大幅领涨(>=3.8%)，主力单日大额净流入(>=2000万)，换手率活跃(>=3.5%)
        if pct >= 3.8 and dde_net >= 20_000_000 and t_rate >= 3.5:
            matched_strats.append({
                "id": "sector_leader",
                "name": STRAT_META["sector_leader"]["name"],
                "badge": STRAT_META["sector_leader"]["badge_class"],
            })
            strategy_counts["sector_leader"] += 1
            reasons.append(f"所属[{ind}]板块领涨先锋，大单净买{_fmt_money(dde_net)}，资金集群抱团")

        # 3. 尾盘抢筹次日溢价 (Closing Surge)
        # 条件：主力净流入>=1500万，主力净买占比>=6.5%，收盘收在高位且实体为阳线，涨幅适中留有空间
        if dde_net >= 15_000_000 and dde_ratio >= 6.5 and close >= (high + low) / 2 and close >= open_p and (1.5 <= pct <= 7.8):
            matched_strats.append({
                "id": "closing_surge",
                "name": STRAT_META["closing_surge"]["name"],
                "badge": STRAT_META["closing_surge"]["badge_class"],
            })
            strategy_counts["closing_surge"] += 1
            reasons.append(f"主力净买占比达{dde_ratio:.1f}%，日K实体饱满收在高位，尾盘抢筹次日溢价高")

        # 4. 机构重度建仓 (Heavy Institution)
        # 条件：单日主力净买超4500万且占比>=6%，或成交额大且净买超6000万
        if (dde_net >= 45_000_000 and dde_ratio >= 6.0) or (amt >= 350_000_000 and dde_net >= 60_000_000):
            matched_strats.append({
                "id": "heavy_institution",
                "name": STRAT_META["heavy_institution"]["name"],
                "badge": STRAT_META["heavy_institution"]["badge_class"],
            })
            strategy_counts["heavy_institution"] += 1
            reasons.append(f"单日大资金重度介入{_fmt_money(dde_net)}，净流入占比{dde_ratio:.1f}%，机构主导强控盘")

        # 5. 超跌资金抄底共振 (Oversold Reversal)
        # 条件：超跌或筑底后主力大单率先转正(>=500万)，出现底背离/底分型或首日资金翻红
        if dde_net >= 5_000_000 and (any(('底' in p or '超跌' in p or '背离' in p) for p in patterns) or c_days == 1) and pct >= 0.5:
            matched_strats.append({
                "id": "oversold_reversal",
                "name": STRAT_META["oversold_reversal"]["name"],
                "badge": STRAT_META["oversold_reversal"]["badge_class"],
            })
            strategy_counts["oversold_reversal"] += 1
            reasons.append(f"超跌企稳筑底，主力资金翻红净买入{_fmt_money(dde_net)}，技术共振反弹点")

        if dde_net > 0 or len(matched_strats) > 0:
            strategy_counts["all"] += 1

        primary_reason = reasons[0] if reasons else ("主力资金净流入" if dde_net > 0 else "主力资金观望")

        processed_rows.append({
            "stock_code": code,
            "stock_name": name,
            "close": close,
            "pct": pct,
            "open": open_p,
            "high": high,
            "low": low,
            "amount": amt,
            "amount_str": _fmt_money(amt),
            "dde_net": dde_net,
            "dde_net_str": _fmt_money(dde_net),
            "dde_ratio": dde_ratio,
            "consec_days": c_days,
            "consec_amount": c_amt,
            "consec_amount_str": _fmt_money(c_amt),
            "t_rate": t_rate,
            "v_rate": v_rate,
            "industry": ind,
            "board_code": b_code,
            "matched_strategies": matched_strats,
            "matched_ids": [m["id"] for m in matched_strats],
            "reason": primary_reason,
            "is_optional": code in wl_set,
        })

    # Top 5 sectors by net inflow
    sorted_sectors = sorted(sector_inflow_map.items(), key=lambda x: x[1], reverse=True)
    top_sectors = [
        {"industry": k, "net_inflow": v, "net_inflow_str": _fmt_money(v)}
        for k, v in sorted_sectors[:5] if v > 0
    ]

    # Water level description (全市场 5200+ 标的资金水位)
    if total_market_turnover >= 1_500_000_000_000:
        water_level = "活跃放量市"
        water_level_desc = "全市场交投活跃超1.5万亿，资金充沛，热点扩散，可积极参与主线龙头与高贝塔标的"
    elif total_market_turnover >= 1_000_000_000_000:
        water_level = "温和震荡市"
        water_level_desc = "存量博弈万亿级别，板块资金轮动加快，优先选择主力持续潜伏蓄势标的"
    else:
        water_level = "缩量防守市"
        water_level_desc = "全市场量能收敛不足万亿，抱团避险为主，重点观察超跌底背离与机构低位承接标的"

    # Filtering
    # 1. Search keyword filter (若用户输入搜索词，支持检索全池任何标的)
    if search_kw:
        filtered_rows = [r for r in processed_rows if search_kw in r["stock_code"] or search_kw in r["stock_name"].upper()]
    else:
        filtered_rows = processed_rows

    # 2. Strategy filter
    if strat_key and strat_key != "all":
        filtered_rows = [r for r in filtered_rows if strat_key in r["matched_ids"]]
    elif not search_kw:
        # 默认全部（未显式搜索时）：展示主力资金净流入或匹配任意策略的标的
        filtered_rows = [r for r in filtered_rows if r["dde_net"] > 0 or len(r["matched_strategies"]) > 0]

    # 3. Minimum inflow filter
    if min_inf > 0:
        filtered_rows = [r for r in filtered_rows if r["dde_net"] >= min_inf]

    # 4. Industry filter
    if ind_filter:
        filtered_rows = [r for r in filtered_rows if r["industry"] == ind_filter]

    # Sorting
    reverse_sort = (sort_d.lower() != "asc")
    sort_key_map = {
        "dde_net": lambda r: r["dde_net"],
        "dde_ratio": lambda r: r["dde_ratio"],
        "consec_days": lambda r: r["consec_days"],
        "consec_amount": lambda r: r["consec_amount"],
        "pct": lambda r: r["pct"],
        "amount": lambda r: r["amount"],
        "t_rate": lambda r: r["t_rate"],
        "v_rate": lambda r: r["v_rate"],
    }
    key_func = sort_key_map.get(sort_c, sort_key_map["dde_net"])
    filtered_rows.sort(key=key_func, reverse=reverse_sort)

    total_filtered = len(filtered_rows)
    final_rows = filtered_rows[:lim]

    return {
        "success": True,
        "summary": {
            "record_date": record_date,
            "universe_total": len(stocks),
            "total_market_turnover": total_market_turnover,
            "total_market_turnover_str": _fmt_money(total_market_turnover),
            "total_net_inflow": total_net_inflow,
            "total_net_inflow_str": _fmt_money(total_net_inflow),
            "inflow_count": inflow_count,
            "outflow_count": outflow_count,
            "flat_count": flat_count,
            "consec_inflow_count": consec_inflow_count,
            "water_level": water_level,
            "water_level_desc": water_level_desc,
            "top_sectors": top_sectors,
        },
        "strategy_counts": strategy_counts,
        "total": total_filtered,
        "rows": final_rows,
    }
