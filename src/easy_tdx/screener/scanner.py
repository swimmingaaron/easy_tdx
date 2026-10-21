"""Full Market Strategy Screener Scanner for easy_tdx with Real TDX Historical & Live Data.

Supports:
- Multi-tier universes: core (35), hs300 (300), zz500 (500), zz1000 (1000), all (5200+)
- Daily disk caching for fast re-entry
- Progress callbacks for background async task tracking
- Graceful cancellation via stop_event
"""
from __future__ import annotations
import logging
import os
import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable
import pandas as pd
import threading

from easy_tdx.strategies.registry import get_strategy
from easy_tdx.stock_lookup import get_stock_name, COMMON_STOCKS
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.screener.universe import get_universe_symbols, CORE_UNIVERSE
from easy_tdx.MyTT import REF, BARSLASTCOUNT, TD_SEQUENTIAL, MA

logger = logging.getLogger(__name__)

DEFAULT_SCAN_UNIVERSE = CORE_UNIVERSE

INTRADAY_CACHE_TTL_SEC: float = 120.0  # 2 minutes during trading hours (09:15-11:30, 13:00-15:05)
POST_MARKET_CACHE_TTL_SEC: float = 43200.0  # 12 hours post-market / weekends

def _get_cache_dir() -> Path:
    """获取选股策略缓存目录（始终定位到当前工作目录/项目根目录下的 data/screener_cache）。"""
    cwd_cache = Path.cwd() / "data" / "screener_cache"
    if cwd_cache.parent.exists():
        cwd_cache.mkdir(parents=True, exist_ok=True)
        return cwd_cache
    repo_root = Path(__file__).resolve().parents[3]
    base = repo_root / "data" / "screener_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base

def _get_cache_file(strategy_name: str, universe: str, period: str = "DAY") -> Path:
    today_str = date.today().strftime("%Y%m%d")
    p_clean = str(period).strip().upper()
    return _get_cache_dir() / f"{strategy_name}_{universe}_{p_clean}_{today_str}.json"

def _load_cache(strategy_name: str, universe: str, period: str = "DAY", expected_total: int = 0, force_refresh: bool = False) -> list[dict[str, Any]] | None:
    if force_refresh:
        return None
    cache_f = _get_cache_file(strategy_name, universe, period=period)
    if not cache_f.exists():
        p_clean = str(period).strip().upper()
        cands = sorted(_get_cache_dir().glob(f"{strategy_name}_{universe}_{p_clean}_*.json"), key=lambda p: p.name, reverse=True)
        if not cands and p_clean == "DAY":
            cands = sorted(_get_cache_dir().glob(f"{strategy_name}_{universe}_*.json"), key=lambda p: p.name, reverse=True)
        if cands:
            cache_f = cands[0]
            logger.info(f"Fallback to most recent screener cache: {cache_f.name}")

    if cache_f.exists():
        try:
            mtime = os.path.getmtime(cache_f)
            age = time.time() - mtime
            # During trading hours, strategy match cache expires quickly (120s)
            # Outside trading hours, valid for up to 12 hours on the same trading day
            from easy_tdx.market_overview import is_trading_time
            max_age = INTRADAY_CACHE_TTL_SEC if is_trading_time() else POST_MARKET_CACHE_TTL_SEC
            if age < max_age:
                with open(cache_f, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "matches" in data and "total_count" in data:
                        cached_total = data.get("total_count", 0)
                        # Strict universe scope validation: cached total must match expected total (e.g. 5222 vs 159/300)
                        if expected_total > 0 and (cached_total <= 0 or abs(cached_total - expected_total) > max(10, int(expected_total * 0.10))):
                            logger.info(f"Cache {cache_f.name} total_count mismatch ({cached_total} vs expected {expected_total}), discarding stale cache.")
                            return None
                        matches = data["matches"]
                        logger.info(f"Loaded {len(matches)} cached screener results from {cache_f.name} (age={age:.1f}s, scanned={cached_total})")
                        return matches
                    else:
                        logger.info(f"Cache {cache_f.name} is missing total_count metadata, discarding legacy cache.")
                        return None
        except Exception as e:
            logger.warning(f"Failed to read cache {cache_f}: {e}")
    return None

def _save_cache(strategy_name: str, universe: str, total_count: int, matches: list[dict[str, Any]], period: str = "DAY") -> None:
    try:
        cache_f = _get_cache_file(strategy_name, universe, period=period)
        payload = {
            "strategy": strategy_name,
            "universe": universe,
            "period": str(period).strip().upper(),
            "total_count": total_count,
            "date": date.today().strftime("%Y%m%d"),
            "timestamp": time.time(),
            "matches_count": len(matches),
            "matches": matches
        }
        with open(cache_f, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(matches)} screener matches (total={total_count}, period={period}) to cache {cache_f.name}")
    except Exception as e:
        logger.warning(f"Failed to save screener cache: {e}")

def enrich_stocks_with_inflows(stocks: list[dict[str, Any]]) -> None:
    """Enrich screener matches in-place with real-time 1d/3d/5d net capital inflows from TDX MAC."""
    if not stocks:
        return
    try:
        from easy_tdx.market_data import _get_market, _fmt_pool_money
        from easy_tdx.market_overview import _get_or_create_mac_client
        from easy_tdx.codec.bitmap import FieldBit, PresetField
        
        mac = _get_or_create_mac_client()
        fields = (
            PresetField.BASIC
            + FieldBit.AMOUNT
            + FieldBit.TOTAL_MARKET_CAP_AB
            + FieldBit.MAIN_NET_AMOUNT
            + FieldBit.MAIN_NET_3D_AMOUNT
            + FieldBit.MAIN_NET_5D_AMOUNT
        )
        
        symbols = [s.get("code") or s.get("symbol") for s in stocks if s.get("code") or s.get("symbol")]
        batch_size = 80
        inflow_map: dict[str, tuple[float, float, float, float]] = {}
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            pairs = [(int(_get_market(code).value), code) for code in batch]
            df = mac.get_stock_quotes(pairs, fields=fields)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    c = str(row.get("code", ""))
                    m1 = float(row.get("main_net_amount") or 0.0)
                    m3 = float(row.get("main_net_3d_amount") or 0.0)
                    m5 = float(row.get("main_net_5d_amount") or 0.0)
                    t_cap = float(row.get("total_market_cap_ab") or 0.0)
                    mv_yi = round(t_cap / 100000000.0, 2) if t_cap > 0 else 0.0
                    if mv_yi == 0.0 and row.get("total_shares") and row.get("close"):
                        sh = float(row.get("total_shares") or 0.0)
                        cl = float(row.get("close") or 0.0)
                        if sh > 0 and cl > 0:
                            mv_yi = round(sh * cl / 10000.0, 2)
                    inflow_map[c] = (m1, m3, m5, mv_yi)
                    
        for s in stocks:
            c = s.get("code") or s.get("symbol", "")
            if not s.get("board_name") or not s.get("board_code"):
                try:
                    from easy_tdx.web.routers.quotes import _resolve_stock_board_info
                    b_info = _resolve_stock_board_info(c)
                    b_code = b_info.get("board_code", "")
                    b_name = b_info.get("board_name", "")
                    if b_code:
                        s["board_code"] = b_code
                    if b_name and b_name != "--":
                        s["board_name"] = b_name
                        s["industry"] = b_name
                except Exception:
                    pass
            s.setdefault("board_code", "")
            s.setdefault("board_name", "--")
            s.setdefault("industry", s.get("board_name", "--"))

            if not s.get("patterns"):
                try:
                    from easy_tdx.pattern_recognition import detect_stock_patterns
                    pats = detect_stock_patterns(c)
                    s["patterns"] = pats
                    s["pattern_status"] = " · ".join(pats) if pats else "震荡整理"
                    s["status"] = s["pattern_status"]
                except Exception:
                    s["patterns"] = ["震荡整理"]
                    s["pattern_status"] = "震荡整理"
                    s["status"] = "震荡整理"

            pat_str = s.get("pattern_status") or (s.get("patterns") and " · ".join(s["patterns"])) or "震荡整理"
            s.setdefault("pattern_feature", pat_str)
            s.setdefault("pattern", pat_str)

            if c in inflow_map:
                m1, m3, m5, mv_yi = inflow_map[c]
                s["main_net_amount"] = m1
                s["main_net_3d"] = m3
                s["main_net_5d"] = m5
                s["total_mv"] = mv_yi
                s["total_mv_yi"] = mv_yi
                s["market_cap_yi"] = mv_yi
                s["market_cap_str"] = f"{mv_yi:.2f}亿" if mv_yi > 0 else "--"
                f1 = _fmt_pool_money(m1)
                f3 = _fmt_pool_money(m3)
                f5 = _fmt_pool_money(m5)
                s["inflow_1d_str"] = f1
                s["inflow_3d_str"] = f3
                s["inflow_5d_str"] = f5
                s["flow_1d_str"] = f1
                s["flow_3d_str"] = f3
                s["flow_5d_str"] = f5
            else:
                s.setdefault("main_net_amount", 0.0)
                s.setdefault("main_net_3d", 0.0)
                s.setdefault("main_net_5d", 0.0)
                s.setdefault("total_mv", 0.0)
                s.setdefault("total_mv_yi", 0.0)
                s.setdefault("market_cap_yi", 0.0)
                s.setdefault("market_cap_str", "--")
                s.setdefault("inflow_1d_str", "0.0万")
                s.setdefault("inflow_3d_str", "0.0万")
                s.setdefault("inflow_5d_str", "0.0万")
                s.setdefault("flow_1d_str", "0.0万")
                s.setdefault("flow_3d_str", "0.0万")
                s.setdefault("flow_5d_str", "0.0万")
    except Exception as e:
        logger.debug(f"Failed to enrich screener stocks with inflows: {e}")
        for s in stocks:
            c = s.get("code") or s.get("symbol", "")
            if not s.get("board_name") or not s.get("board_code"):
                try:
                    from easy_tdx.web.routers.quotes import _resolve_stock_board_info
                    b_info = _resolve_stock_board_info(c)
                    b_code = b_info.get("board_code", "")
                    b_name = b_info.get("board_name", "")
                    if b_code:
                        s["board_code"] = b_code
                    if b_name and b_name != "--":
                        s["board_name"] = b_name
                        s["industry"] = b_name
                except Exception:
                    pass
            s.setdefault("board_code", "")
            s.setdefault("board_name", "--")
            s.setdefault("industry", s.get("board_name", "--"))

            if not s.get("patterns"):
                s["patterns"] = ["震荡整理"]
                s["pattern_status"] = "震荡整理"
                s["status"] = "震荡整理"
            pat_str = s.get("pattern_status") or "震荡整理"
            s.setdefault("pattern_feature", pat_str)
            s.setdefault("pattern", pat_str)
            s.setdefault("main_net_amount", 0.0)
            s.setdefault("main_net_3d", 0.0)
            s.setdefault("main_net_5d", 0.0)
            s.setdefault("total_mv", 0.0)
            s.setdefault("total_mv_yi", 0.0)
            s.setdefault("market_cap_yi", 0.0)
            s.setdefault("market_cap_str", "--")
            s.setdefault("inflow_1d_str", "0.0万")
            s.setdefault("inflow_3d_str", "0.0万")
            s.setdefault("inflow_5d_str", "0.0万")
            s.setdefault("flow_1d_str", "0.0万")
            s.setdefault("flow_3d_str", "0.0万")
            s.setdefault("flow_5d_str", "0.0万")

    # 进一步自动补齐量化共振交易系统多因子数据 (买入分, 卖出分, 连续净流入, 换手, 估值分位, 股东集中度, 营业/净利润同比等)
    try:
        from easy_tdx.trading_system.engine import evaluate_universe
        sym_codes = [s.get("code") or s.get("symbol") for s in stocks if s.get("code") or s.get("symbol")]
        if sym_codes:
            ts_res = evaluate_universe(symbols=sym_codes, universe_type="custom", period="day")
            if ts_res:
                ts_map = {r["stock_code"]: r for r in ts_res if "stock_code" in r}
                for s in stocks:
                    c = s.get("code") or s.get("symbol")
                    tr = ts_map.get(c)
                    if tr:
                        s["buy_score"] = tr.get("buy_score", 0)
                        s["sell_score"] = tr.get("sell_score", 0)
                        s["consec_days"] = tr.get("consec_days", 0)
                        s["consec_amount"] = tr.get("consec_amount", 0.0)
                        s["t_rate"] = tr.get("t_rate", 0.0)
                        s["v_rate"] = tr.get("v_rate", 0.0)
                        s["days"] = tr.get("days", 0)
                        s["zig"] = tr.get("zig", 0)
                        s["ystz"] = tr.get("ystz", 0.0)
                        s["sjltz"] = tr.get("sjltz", 0.0)
                        s["pe_percentile"] = tr.get("pe_percentile", 0.0)
                        s["holder_ratio"] = tr.get("holder_ratio", 0.0)
                        s["holder_focus"] = tr.get("holder_focus", "--")
                        s["holders_num"] = tr.get("holders_num", 0)
                        s["holders_str"] = tr.get("holders_str", "--")
                        s["holders_changes"] = tr.get("holders_changes", [])
                        s["pattern_score"] = tr.get("pattern_score", 0)
                        if tr.get("amount") and not s.get("amount"):
                            s["amount"] = tr["amount"]
                        if tr.get("mkt_capt") and not s.get("mkt_capt"):
                            s["mkt_capt"] = tr["mkt_capt"]
                        if tr.get("industry") and tr["industry"] != "--" and (not s.get("industry") or s.get("industry") == "--"):
                            s["industry"] = tr["industry"]
                            s["board_name"] = tr["industry"]
                        if tr.get("board_code") and not s.get("board_code"):
                            s["board_code"] = tr["board_code"]
    except Exception as e:
        logger.debug(f"Failed to enrich screener stocks with trading system data: {e}")

    for s in stocks:
        for k, def_val in [
            ("buy_score", 0), ("sell_score", 0), ("consec_days", 0),
            ("consec_amount", 0.0), ("t_rate", 0.0), ("v_rate", 0.0),
            ("days", 0), ("zig", 0), ("ystz", 0.0), ("sjltz", 0.0),
            ("pe_percentile", 0.0), ("holder_ratio", 0.0), ("holders_num", 0),
            ("pattern_score", 0)
        ]:
            if s.get(k) is None:
                s[k] = def_val
        if not s.get("holder_focus"):
            s["holder_focus"] = "--"
        if not s.get("holders_str"):
            s["holders_str"] = "--"
        if s.get("holders_changes") is None:
            s["holders_changes"] = []

from concurrent.futures import ThreadPoolExecutor, as_completed

_DAILY_KLINE_CACHE: dict[str, tuple[str, float, pd.DataFrame]] = {}
_DAILY_KLINE_LOCK = threading.Lock()


def clear_screener_cache() -> None:
    """Clear in-memory daily kline cache for all strategies."""
    with _DAILY_KLINE_LOCK:
        _DAILY_KLINE_CACHE.clear()
        logger.info("Cleared screener in-memory daily kline cache.")


def _fetch_kline_internal(sym: str, period: str = "DAY", force_refresh: bool = False) -> pd.DataFrame | None:
    today_str = date.today().strftime("%Y%m%d")
    now_ts = time.time()
    p_clean = str(period).strip().upper()
    cache_key = f"{sym}_{p_clean}"
    
    if not force_refresh:
        with _DAILY_KLINE_LOCK:
            if cache_key in _DAILY_KLINE_CACHE:
                d_str, cached_ts, cached_df = _DAILY_KLINE_CACHE[cache_key]
                if d_str == today_str:
                    from easy_tdx.market_overview import is_trading_time
                    max_age = INTRADAY_CACHE_TTL_SEC if is_trading_time() else POST_MARKET_CACHE_TTL_SEC
                    if (now_ts - cached_ts) < max_age:
                        return cached_df

    from easy_tdx.market_data import fetch_security_kline
    fetch_cnt = 140 if p_clean in ("DAY", "WEEK", "MONTH", "SEASON", "YEAR") else (160 if p_clean == "60M" else 240)
    df = fetch_security_kline(sym, count=fetch_cnt, period=p_clean)
    if df is not None and len(df) >= 15:
        with _DAILY_KLINE_LOCK:
            _DAILY_KLINE_CACHE[cache_key] = (today_str, now_ts, df)
        return df
    return None


def _get_or_fetch_daily_kline(sym: str, force_refresh: bool = False) -> pd.DataFrame | None:
    """Backwards compatibility wrapper for daily kline."""
    return _fetch_kline_internal(sym, period="DAY", force_refresh=force_refresh)


def _get_or_fetch_kline(sym: str, period: str = "DAY", force_refresh: bool = False) -> pd.DataFrame | None:
    p_clean = str(period).strip().upper()
    if p_clean == "DAY":
        return _get_or_fetch_daily_kline(sym, force_refresh=force_refresh)
    return _fetch_kline_internal(sym, period=p_clean, force_refresh=force_refresh)


# ── 缠论 4 级联选股周期预设 ───────────────────────────────────────────
# 1. 30F 5F 1F: 筛选条件 大周期30F线出现大买 (默认)
# 2. 日 30F 5F: 筛选条件 大周期日线出现大买
# 3. 周 日 30F: 筛选条件 大周期周线出现大买且保持上升趋势，同时30M出现1买
# 4. 月 周 日: 筛选条件 大周期月线出现大买且保持上升趋势，同时日线出现1买
CHANLUN_PERIOD_PRESETS: dict[str, dict[str, Any]] = {
    "30F_5F_1F": {
        "key": "30F_5F_1F",
        "periods": ["30F", "5F", "1F"],
        "high_p": "30F",
        "high_period": "30F",
        "high_name": "30F",
        "kline_period": "30M",
        "label": "30F 5F 1F",
        "desc": "30F 5F 1F (30F转折大买 + 1F买点共振)",
    },
    "DAY_30F_5F": {
        "key": "DAY_30F_5F",
        "periods": ["DAY", "30F", "5F"],
        "high_p": "DAY",
        "high_period": "DAY",
        "high_name": "日线",
        "kline_period": "DAY",
        "label": "日 30F 5F",
        "desc": "日30M5F (日线转折大买 + 5M 2买 · 默认)",
    },
    "WEEK_DAY_30F": {
        "key": "WEEK_DAY_30F",
        "periods": ["WEEK", "DAY", "30F"],
        "high_p": "WEEK",
        "high_period": "WEEK",
        "high_name": "周线",
        "kline_period": "WEEK",
        "label": "周 日 30F",
        "desc": "周日30M (周线转折大买且上升趋势 + 30M 1买)",
    },
    "MONTH_WEEK_DAY": {
        "key": "MONTH_WEEK_DAY",
        "periods": ["MONTH", "WEEK", "DAY"],
        "high_p": "MONTH",
        "high_period": "MONTH",
        "high_name": "月线",
        "kline_period": "MONTH",
        "label": "月 周 日",
        "desc": "月周日 (月线转折大买且上升趋势 + 日线 1买)",
    },
}


def _is_top_sell_downtrend(sym: str, period: str = "MONTH", force_refresh: bool = False) -> bool:
    """检查指定周期（月线或周线）是否处于见顶大卖之后的空头杀跌趋势。
    
    判定准则（任何一条满足即判定为见顶大卖下跌）：
    1. 过去 6 根 K 线内最高价到当前最新收盘价的回撤超过 12%，且最新收盘价跌破 5 周期移动均线 (MA5)。
    2. 最近 3 根 K 线构成顶分型（中间一根高点最高、低点最高），且当前收盘价低于顶分型中K线的最低点，且位于 MA5 下方。
    """
    df = _get_or_fetch_kline(sym, period=period, force_refresh=force_refresh)
    if df is None or len(df) < 5:
        return False

    try:
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        n = len(closes)

        last_close = float(closes[-1])
        ma5 = float(closes[-5:].mean())

        # 1. 见顶深幅杀跌回撤且跌破 MA5 生命线
        lookback = min(6, n)
        recent_peak = float(highs[-lookback:].max())
        if recent_peak > 0:
            drawdown_pct = (recent_peak - last_close) / recent_peak * 100.0
            if drawdown_pct >= 12.0 and last_close < ma5:
                return True

        # 2. 顶分型破位杀跌：倒数第2根为顶分型顶点，且最新价格跌破顶分型区间且在 MA5 下
        if n >= 4:
            h_prev2, h_prev1, h_cur = highs[-3], highs[-2], highs[-1]
            l_prev2, l_prev1, l_cur = lows[-3], lows[-2], lows[-1]
            if h_prev1 > h_prev2 and h_prev1 > h_cur and l_prev1 > l_prev2 and l_prev1 > l_cur:
                if last_close < min(l_prev1, l_prev2) and last_close < ma5:
                    return True

        return False
    except Exception:
        return False


def parse_chanlun_screener_preset(raw_period: str | None) -> dict[str, Any]:
    """解析缠论选股的 4 级联周期，默认为 日 30F 5F (DAY_30F_5F)。"""
    if not raw_period:
        return CHANLUN_PERIOD_PRESETS["DAY_30F_5F"]

    clean = str(raw_period).strip().upper().replace(" ", "_").replace("-", "_").replace(",", "_")

    # 1. 30F 5F 1F
    if "30F_5F_1F" in clean or ("30F" in clean and "5F" in clean and "1F" in clean) or clean in ("30M", "30F", "1M", "5M"):
        return CHANLUN_PERIOD_PRESETS["30F_5F_1F"]

    # 2. 日 30F 5F (默认)
    if "DAY_30F_5F" in clean or ("DAY" in clean and "30F" in clean and "5F" in clean) or ("日" in str(raw_period) and "30" in str(raw_period) and "5" in str(raw_period)) or clean in ("DAY", "DAILY", "D"):
        return CHANLUN_PERIOD_PRESETS["DAY_30F_5F"]

    # 3. 周 日 30F
    if "WEEK_DAY_30F" in clean or ("WEEK" in clean and "DAY" in clean and "30F" in clean) or ("周" in str(raw_period) and "日" in str(raw_period) and "30" in str(raw_period)) or clean in ("WEEK", "WEEKLY", "W"):
        return CHANLUN_PERIOD_PRESETS["WEEK_DAY_30F"]

    # 4. 月 周 日
    if "MONTH_WEEK_DAY" in clean or ("MONTH" in clean and "WEEK" in clean and "DAY" in clean) or ("月" in str(raw_period) and "周" in str(raw_period) and "日" in str(raw_period)) or clean in ("MONTH", "MONTHLY", "M"):
        return CHANLUN_PERIOD_PRESETS["MONTH_WEEK_DAY"]

    return CHANLUN_PERIOD_PRESETS["DAY_30F_5F"]


def _evaluate_stock_for_strategy(
    sym: str,
    strategy_name: str,
    st: Any,
    lookback_bars: int,
    period: str = "DAY",
    force_refresh: bool = False
) -> dict[str, Any] | None:
    if strategy_name == "chanlun_strategy":
        cl_preset = parse_chanlun_screener_preset(period)
        eval_period = cl_preset["kline_period"]
    elif strategy_name == "chanlun_resonance":
        cl_preset = None
        eval_period = "DAY"
    else:
        cl_preset = None
        eval_period = period

    df = _get_or_fetch_kline(sym, period=eval_period, force_refresh=force_refresh)
    if df is None or len(df) < 15:
        return None

    try:
        if strategy_name == "chanlun_resonance":
            # -------------------------------------------------------------
            # 缠论共振策略：必须全部同时满足下列三个条件：
            # 1. 月周日区间套：月线最近一次转折是大买，月线保持上升趋势（非空头，无月线见顶大卖杀跌破位，周线非空头），月线最近一笔是向下笔，同时日线出现 1买；
            # 2. 周日30M区间套：周线最近一次转折是大买，周线保持上升趋势（排除周线见顶杀跌），周线最近一笔是向下笔，同时 30M 出现 1买；
            # 3. 日30M5F区间套：日线最近一次转折是大买，日线最近一笔是向下笔，同时 5M 出现 2买。
            # 任何一个条件不满足均一票否决（如 002463.SZ 返回 None）。
            # -------------------------------------------------------------
            from easy_tdx.chanlun.resonance import analyze_multi_period_resonance

            # 全局大级别防线：月线不可处于大卖见顶杀跌趋势中
            if _is_top_sell_downtrend(sym, "MONTH", force_refresh=force_refresh):
                return None

            # 条件 1：月周日区间套 (MONTH_WEEK_DAY)
            res_mwd = analyze_multi_period_resonance(
                code=sym,
                periods=["MONTH", "WEEK", "DAY"],
                count=300,
                force_refresh=force_refresh
            )
            if not res_mwd:
                return None
            high_mwd = [m for m in res_mwd.get("unified_chart", {}).get("mmd_marks", []) if m.get("level") == "high"]
            low_mwd = [m for m in res_mwd.get("unified_chart", {}).get("mmd_marks", []) if m.get("level") == "low"]
            if not high_mwd:
                return None
            sum_mwd = res_mwd.get("summary", {})
            high_state_m = sum_mwd.get("high_state", {})
            mid_state_w = sum_mwd.get("mid_state", {})

            # 1.1 月线最近一次转折是大买
            last_m_high = high_mwd[-1]
            if not last_m_high.get("is_buy", False) or "SELL" in str(last_m_high.get("type", "")).upper() or "卖" in str(last_m_high.get("label", "")):
                return None
            m_bars_ago = high_state_m.get("recent_mmd_bars_ago")
            if m_bars_ago is not None and int(m_bars_ago) > 8:
                return None
            # 1.2 月线保持上升趋势 (月线非空头，排除见顶杀跌，周线非空头)
            if high_state_m.get("is_bearish", False) or mid_state_w.get("is_bearish", False):
                return None
            if _is_top_sell_downtrend(sym, "MONTH", force_refresh=force_refresh):
                return None
            # 1.3 月线最近一笔是向下笔
            m_bi_dir = str(high_state_m.get("bi_direction", "")).lower()
            if m_bi_dir not in ("down", "向下", "向下笔"):
                return None
            # 1.4 同时日线出现 1买
            day_1buys = [
                m for m in low_mwd
                if m.get("is_buy") and ("1BUY" in str(m.get("type", "")).upper() or "1买" in str(m.get("label", "")))
            ]
            if not day_1buys:
                return None
            if low_mwd and not low_mwd[-1].get("is_buy", False):
                return None

            # 条件 2：周日30M区间套 (WEEK_DAY_30F)
            if _is_top_sell_downtrend(sym, "WEEK", force_refresh=force_refresh):
                return None
            res_wd30 = analyze_multi_period_resonance(
                code=sym,
                periods=["WEEK", "DAY", "30F"],
                count=300,
                force_refresh=force_refresh
            )
            if not res_wd30:
                return None
            high_wd30 = [m for m in res_wd30.get("unified_chart", {}).get("mmd_marks", []) if m.get("level") == "high"]
            low_wd30 = [m for m in res_wd30.get("unified_chart", {}).get("mmd_marks", []) if m.get("level") == "low"]
            if not high_wd30:
                return None
            sum_wd30 = res_wd30.get("summary", {})
            high_state_w = sum_wd30.get("high_state", {})

            # 2.1 周线最近一次转折是大买
            last_w_high = high_wd30[-1]
            if not last_w_high.get("is_buy", False) or "SELL" in str(last_w_high.get("type", "")).upper() or "卖" in str(last_w_high.get("label", "")):
                return None
            w_bars_ago = high_state_w.get("recent_mmd_bars_ago")
            if w_bars_ago is not None and int(w_bars_ago) > 8:
                return None
            # 2.2 周线保持上升趋势 (排除周线见顶杀跌)
            if high_state_w.get("is_bearish", False):
                return None
            # 2.3 周线最近一笔是向下笔
            w_bi_dir = str(high_state_w.get("bi_direction", "")).lower()
            if w_bi_dir not in ("down", "向下", "向下笔"):
                return None
            # 2.4 同时 30M 出现 1买
            f30_1buys = [
                m for m in low_wd30
                if m.get("is_buy") and ("1BUY" in str(m.get("type", "")).upper() or "1买" in str(m.get("label", "")))
            ]
            if not f30_1buys:
                return None
            if low_wd30 and not low_wd30[-1].get("is_buy", False):
                return None

            # 条件 3：日30M5F区间套 (DAY_30F_5F)
            res_d30f5 = analyze_multi_period_resonance(
                code=sym,
                periods=["DAY", "30F", "5F"],
                count=300,
                force_refresh=force_refresh
            )
            if not res_d30f5:
                return None
            high_d30f5 = [m for m in res_d30f5.get("unified_chart", {}).get("mmd_marks", []) if m.get("level") == "high"]
            low_d30f5 = [m for m in res_d30f5.get("unified_chart", {}).get("mmd_marks", []) if m.get("level") == "low"]
            if not high_d30f5:
                return None
            sum_d30f5 = res_d30f5.get("summary", {})
            high_state_d = sum_d30f5.get("high_state", {})

            # 3.1 日线最近一次转折是大买
            last_d_high = high_d30f5[-1]
            if not last_d_high.get("is_buy", False) or "SELL" in str(last_d_high.get("type", "")).upper() or "卖" in str(last_d_high.get("label", "")):
                return None
            d_bars_ago = high_state_d.get("recent_mmd_bars_ago")
            if d_bars_ago is not None and int(d_bars_ago) > 15:
                return None
            # 3.2 日线最近一笔是向下笔
            d_bi_dir = str(high_state_d.get("bi_direction", "")).lower()
            if d_bi_dir not in ("down", "向下", "向下笔"):
                return None
            # 3.3 同时 5M 出现 2买
            f5_2buys = [
                m for m in low_d30f5
                if m.get("is_buy") and ("2BUY" in str(m.get("type", "")).upper() or "2买" in str(m.get("label", "")))
            ]
            if not f5_2buys:
                return None
            if low_d30f5 and not low_d30f5[-1].get("is_buy", False):
                return None

            # 全部满足！选取 5M 2买作为精确买点
            target_m = f5_2buys[-1]
            last_m = target_m
            label = str(last_m.get("label", ""))
            m_type = str(last_m.get("type", "")).upper()
            chan_tag = "[缠论全级别共振]月周日1买+周日30M1买+日30M5F2买"

            sig_df = df.copy()
            sig_date_str = str(last_m.get("date", "")).strip()
            date_col = "datetime" if "datetime" in sig_df.columns else "date"
            dt_series = sig_df[date_col].astype(str)

            match_indices = sig_df.index[dt_series.str.startswith(sig_date_str[:10])]
            if len(match_indices) == 0:
                match_indices = sig_df.index[dt_series <= sig_date_str]

            if len(match_indices) > 0:
                trigger_loc = sig_df.index.get_loc(match_indices[-1])
                trigger_bar = sig_df.iloc[trigger_loc]
                trigger_idx = match_indices[-1]
                days_ago = len(sig_df) - 1 - trigger_loc
            else:
                trigger_bar = sig_df.iloc[-1]
                trigger_idx = sig_df.index[-1]
                trigger_loc = len(sig_df) - 1
                days_ago = 0

            # 价格与风控防线：最新收盘价不得跌破买点止损位
            last_c = float(sig_df.iloc[-1]["close"])
            trigger_p = float(last_m.get("price", 0.0))
            if trigger_p > 0:
                if last_c < trigger_p * 0.95:
                    return None
                since_pct = (last_c - trigger_p) / trigger_p * 100.0
                if since_pct > 25.0:
                    return None
        elif strategy_name == "chanlun_strategy":
            assert cl_preset is not None
            chan_periods = cl_preset["periods"]
            high_name = cl_preset["high_name"]
            high_p = cl_preset["high_p"]
            preset_key = cl_preset.get("key", "DAY_30F_5F")

            # 执行三周期缠论立体共振分析，大周期为 high_p (30F / 日 / 周 / 月)
            from easy_tdx.chanlun.resonance import analyze_multi_period_resonance
            chan_res = analyze_multi_period_resonance(
                code=sym,
                periods=chan_periods,
                count=300,
                force_refresh=force_refresh
            )
            if not chan_res:
                return None

            unified = chan_res.get("unified_chart", {})
            mmd_marks = unified.get("mmd_marks", [])
            high_mmds = [m for m in mmd_marks if m.get("level") == "high"]
            low_mmds = [m for m in mmd_marks if m.get("level") == "low"]

            if not high_mmds:
                return None

            summary = chan_res.get("summary", {})
            high_state = summary.get("high_state", {})
            mid_state = summary.get("mid_state", {})
            low_state = summary.get("low_state", {})

            # 1. 大级别最近一次转折必须是大买 (last_high 必须是买点，绝不能是卖点破坏)
            last_high = high_mmds[-1]
            if not last_high.get("is_buy", False):
                return None
            if "SELL" in str(last_high.get("type", "")).upper() or "卖" in str(last_high.get("label", "")):
                return None

            # 全局大级别防线：若月线处于见顶大卖杀跌趋势中（高点大幅回撤且跌破月线MA5生命线），坚决排除
            if _is_top_sell_downtrend(sym, "MONTH", force_refresh=force_refresh):
                return None

            # 大周期时效性防线：大买转折不能过于陈旧 (月线 <= 6 根, 周线 <= 8 根, 日线 <= 15 根, 分钟线 <= 30 根)
            high_bars_ago = high_state.get("recent_mmd_bars_ago")
            if high_bars_ago is not None:
                max_high_bars = 6 if high_p == "MONTH" else (8 if high_p == "WEEK" else (15 if high_p == "DAY" else 30))
                if int(high_bars_ago) > max_high_bars:
                    return None

            # 2. 根据各级联区间套策略，严格检验大周期趋势维持与小级别买点
            if preset_key == "MONTH_WEEK_DAY":
                # 月周日区间套上最近一次转折是大买，月线保持上升趋势，月线最近一笔是向下笔，同时日线出现1买
                if high_state.get("is_bearish", False):
                    return None
                if _is_top_sell_downtrend(sym, "MONTH", force_refresh=force_refresh):
                    return None
                if mid_state.get("is_bearish", False):
                    return None
                m_bi_dir = str(high_state.get("bi_direction", "")).lower()
                if m_bi_dir not in ("down", "向下", "向下笔"):
                    return None

                day_1buys = [
                    m for m in low_mmds
                    if m.get("is_buy") and ("1BUY" in str(m.get("type", "")).upper() or "1买" in str(m.get("label", "")))
                ]
                if not day_1buys:
                    return None
                # 日线最近买卖点不能被卖点破坏
                if low_mmds and not low_mmds[-1].get("is_buy", False):
                    return None
                target_m = day_1buys[-1]
                chan_tag = "[月周日]大买共振·日线1买"

            elif preset_key == "WEEK_DAY_30F":
                # 周日30M 区间套上最近一次转折是大买，周线保持上升趋势，周线最近一笔是向下笔，同时30M出现1买
                if high_state.get("is_bearish", False):
                    return None
                if _is_top_sell_downtrend(sym, "WEEK", force_refresh=force_refresh):
                    return None
                w_bi_dir = str(high_state.get("bi_direction", "")).lower()
                if w_bi_dir not in ("down", "向下", "向下笔"):
                    return None

                f30_1buys = [
                    m for m in low_mmds
                    if m.get("is_buy") and ("1BUY" in str(m.get("type", "")).upper() or "1买" in str(m.get("label", "")))
                ]
                if not f30_1buys:
                    return None
                if low_mmds and not low_mmds[-1].get("is_buy", False):
                    return None
                target_m = f30_1buys[-1]
                chan_tag = "[周日30M]大买共振·30M1买"

            elif preset_key == "DAY_30F_5F":
                # 日30M5F 区间套上最近一次转折是大买，日线最近一笔是向下笔，同时5M出现2买
                d_bi_dir = str(high_state.get("bi_direction", "")).lower()
                if d_bi_dir not in ("down", "向下", "向下笔"):
                    return None

                f5_2buys = [
                    m for m in low_mmds
                    if m.get("is_buy") and ("2BUY" in str(m.get("type", "")).upper() or "2买" in str(m.get("label", "")))
                ]
                if not f5_2buys:
                    return None
                if low_mmds and not low_mmds[-1].get("is_buy", False):
                    return None
                target_m = f5_2buys[-1]
                chan_tag = "[日30M5F]大买共振·5M2买"

            else:
                # 30F_5F_1F 超短日内区间套
                f1_buys = [m for m in low_mmds if m.get("is_buy", False)]
                if not f1_buys:
                    return None
                if low_mmds and not low_mmds[-1].get("is_buy", False):
                    return None
                target_m = f1_buys[-1]
                chan_tag = f"[{high_name}]大买共振·1F进场"

            last_m = target_m
            label = str(last_m.get("label", ""))
            m_type = str(last_m.get("type", "")).upper()

            sig_df = df.copy()

            # 定位触发日及价格
            sig_date_str = str(last_m.get("date", "")).strip()
            date_col = "datetime" if "datetime" in sig_df.columns else "date"
            dt_series = sig_df[date_col].astype(str)

            match_indices = sig_df.index[dt_series.str.startswith(sig_date_str)]
            if len(match_indices) == 0 and len(sig_date_str) >= 16:
                # 尝试匹配到分钟 "YYYY-MM-DD HH:MM"
                match_indices = sig_df.index[dt_series.str.startswith(sig_date_str[:16])]
            if len(match_indices) == 0 and len(sig_date_str) >= 10:
                # 若为同一天，寻找时间紧随其后的K线 (如 09:31 落在 10:00 K线)
                match_ge = sig_df.index[dt_series.str.startswith(sig_date_str[:10]) & (dt_series >= sig_date_str)]
                if len(match_ge) > 0:
                    match_indices = match_ge[:1]
                else:
                    match_indices = sig_df.index[dt_series.str.startswith(sig_date_str[:10])]
            if len(match_indices) == 0 and len(sig_date_str) >= 7 and cl_preset["kline_period"] == "MONTH":
                # 月线匹配 YYYY-MM
                match_indices = sig_df.index[dt_series.str.startswith(sig_date_str[:7])]
            if len(match_indices) == 0:
                match_indices = sig_df.index[dt_series <= sig_date_str]

            if len(match_indices) > 0:
                trigger_loc = sig_df.index.get_loc(match_indices[-1])
                trigger_bar = sig_df.iloc[trigger_loc]
                trigger_idx = match_indices[-1]
                days_ago = len(sig_df) - 1 - trigger_loc
            else:
                bars_ago_val = high_state.get("recent_mmd_bars_ago")
                if bars_ago_val is not None and 0 <= int(bars_ago_val) < len(sig_df):
                    days_ago = int(bars_ago_val)
                    trigger_loc = max(0, len(sig_df) - 1 - days_ago)
                    trigger_bar = sig_df.iloc[trigger_loc]
                    trigger_idx = sig_df.index[trigger_loc]
                else:
                    trigger_bar = sig_df.iloc[-1]
                    trigger_idx = sig_df.index[-1]
                    trigger_loc = len(sig_df) - 1
                    days_ago = 0

            # 1. 严格时效性控制：买点必须发生在近期
            is_min_period = cl_preset["kline_period"] in ("30M", "60M", "120M", "15M", "5M")
            default_limit = 30 if is_min_period else 15
            effective_lookback = min(lookback_bars, default_limit) if lookback_bars > 0 else default_limit
            if days_ago > effective_lookback:
                return None

            # 2. 价格与风控防线：最新收盘价不得跌破买点止损位
            last_c = float(sig_df.iloc[-1]["close"])
            trigger_p = float(last_m.get("price", 0.0))
            if trigger_p > 0:
                # 止损过滤：跌破买点价 5% 视为买点破坏失效
                if last_c < trigger_p * 0.95:
                    return None
                # 透支过滤：自买点以来涨幅超 25% 视为已大幅兑现/追高风险，不推荐
                since_pct = (last_c - trigger_p) / trigger_p * 100.0
                if since_pct > 25.0:
                    return None

            # 3. 区间套次级别共振过滤：
            # 若次级别最新最后点位处于严重卖点破位 (如次级别3卖)，排除
            mid_mmds = [m for m in chan_res.get("unified_chart", {}).get("mmd_marks", []) if m.get("level") == "mid"]
            if mid_mmds:
                last_mid = mid_mmds[-1]
                if not last_mid.get("is_buy", True) and "3SELL" in str(last_mid.get("type", "")).upper():
                    mid_date_str = str(last_mid.get("date", "")).strip()
                    mid_matches = sig_df.index[dt_series.str.startswith(mid_date_str[:10])]
                    if len(mid_matches) > 0:
                        mid_days_ago = len(sig_df) - 1 - sig_df.index.get_loc(mid_matches[-1])
                        if mid_days_ago <= 3:
                            return None
        elif strategy_name == "td_sequential":
            sig_df = st.generate_signals(df)
            if sig_df is None:
                return None
            # 严格以 K 线显示的 TD_SEQUENTIAL 算法为单一基准：
            # 必须保证最新一根 K 线的上升九转序列真实点亮且在第3根日线及以上 (td9_h[-1] >= 3)，
            # 在第3根日线时开始标注，严格过滤掉未达3根 (td9_h[-1] < 3)、未点亮/已中断 (td9_h[-1] == 0) 或已转为下跌低序列 (td9_l[-1] > 0) 的股票
            c_vals = sig_df["close"].values
            td9_h, td9_l = TD_SEQUENTIAL(c_vals, 9)
            cur_h_seq = int(td9_h[-1])
            cur_l_seq = int(td9_l[-1])
            if cur_h_seq < 3 or cur_l_seq > 0:
                return None

            days_ago = cur_h_seq - 3
            if lookback_bars > 0 and days_ago >= lookback_bars:
                return None

            trigger_loc = max(0, len(sig_df) - 1 - days_ago)
            trigger_bar = sig_df.iloc[trigger_loc]
            trigger_idx = sig_df.index[trigger_loc]
        else:
            sig_df = st.generate_signals(df)
            if sig_df is None:
                return None
            if "buy_signal" not in sig_df.columns:
                return None

            window_size = min(lookback_bars, len(sig_df))
            recent_df = sig_df.iloc[-window_size:]
            buy_mask = recent_df["buy_signal"].astype(bool)

            if not buy_mask.any():
                return None

            trigger_idx = buy_mask[buy_mask].index[-1]
            trigger_bar = sig_df.loc[trigger_idx]
            trigger_loc = sig_df.index.get_loc(trigger_idx)
            days_ago = len(sig_df) - 1 - trigger_loc

            # 触发后若已产生卖出破位信号，则该信号已终结或止损，坚决排除
            if "sell_signal" in sig_df.columns:
                recent_sells = sig_df["sell_signal"].iloc[trigger_loc + 1:].astype(bool)
                if recent_sells.any():
                    return None

            # 波浪理论主升3浪专项风控：
            if strategy_name == "wave_theory_impulse":
                # 主升浪必须具备强时效性（启动后10根K线内，避免追高末期）
                if days_ago > 10:
                    return None
                # 当前最新价格不能跌穿 MA20*0.96，否则视为破位回调
                last_c = float(sig_df.iloc[-1]["close"])
                c_vals = sig_df["close"].values
                ma20_last = float(MA(c_vals, min(20, len(c_vals)))[-1])
                if last_c < ma20_last * 0.96:
                    return None

            # 均线四边形加速专项时效与风控控制:
            if strategy_name == "ma_quadrilateral":
                if days_ago > max(20, lookback_bars):
                    return None
                # 1. 信号触发后若已经触发过离场/止损 (sell_signal)，则不可再作为有效标的推荐
                if trigger_loc < len(sig_df) - 1:
                    post_signals = sig_df.iloc[trigger_loc + 1:]
                    if "sell_signal" in post_signals.columns and post_signals["sell_signal"].any():
                        return None

                # 2. 当前最新价格与短中期均线动态监控
                last_c = float(sig_df.iloc[-1]["close"])
                c_vals = sig_df["close"].values
                ma5_last = float(MA(c_vals, min(5, len(c_vals)))[-1])
                ma10_last = float(MA(c_vals, min(10, len(c_vals)))[-1])
                ma20_last = float(MA(c_vals, min(20, len(c_vals)))[-1])

                # 跌破 MA20 趋势生命线直接淘汰
                if last_c < ma20_last * 0.98:
                    return None

                # 若距离信号已过去3天以上，短线已见顶走坏（MA5死叉MA10且收盘在MA10下方），淘汰避免追高或抄底接飞刀
                if days_ago >= 3:
                    if last_c < ma10_last and ma5_last < ma10_last:
                        return None

        # 优化：筛选结果的价格、涨跌幅、成交量和成交额统一显示为日线 (DAY)
        if eval_period == "DAY":
            day_df = sig_df
        else:
            day_df = _get_or_fetch_kline(sym, period="DAY", force_refresh=force_refresh)
            if day_df is None or len(day_df) == 0:
                day_df = sig_df

        day_last_bar = day_df.iloc[-1]
        last_bar = day_last_bar
        stock_name = get_stock_name(sym)

        close_price = round(float(day_last_bar["close"]), 2)
        trigger_price = round(float(trigger_bar["close"]), 2)
        vol = int(day_last_bar.get("volume", 0))
        amt_wan = round(float(day_last_bar.get("amount", 0.0)) / 10000.0, 1)

        # 日线今日最新涨跌幅
        if len(day_df) >= 2:
            day_prev_close = float(day_df.iloc[-2]["close"])
            latest_change_pct = round((close_price - day_prev_close) / day_prev_close * 100.0, 2) if day_prev_close > 0 else 0.0
        else:
            latest_change_pct = 0.0

        if trigger_loc > 0:
            trigger_prev_close = float(sig_df.iloc[trigger_loc - 1]["close"])
            signal_change_pct = round((trigger_price - trigger_prev_close) / trigger_prev_close * 100.0, 2) if trigger_prev_close > 0 else 0.0
        elif "change_pct" in trigger_bar and pd.notna(trigger_bar["change_pct"]):
            signal_change_pct = round(float(trigger_bar["change_pct"]), 2)
        else:
            signal_change_pct = 0.0

        # 自信号触发以来的涨跌幅 (以日线最新现价相对于触发价计算)
        since_signal_pct = round((close_price - trigger_price) / trigger_price * 100.0, 2) if trigger_price > 0 else 0.0

        signal_date = str(trigger_bar.get("datetime", ""))
        if " " in signal_date:
            signal_date = signal_date.split(" ")[0]
        elif len(signal_date) == 8 and signal_date.isdigit():
            signal_date = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:]}"

        p_clean = str(period).strip().upper()
        period_unit_map = {
            "30F_5F_1F": "根30分K",
            "DAY_30F_5F": "日",
            "WEEK_DAY_30F": "周",
            "MONTH_WEEK_DAY": "月",
            "30M": "根30分K",
            "60M": "根60分K",
            "120M": "根120分K",
            "DAY": "日",
            "WEEK": "周",
            "MONTH": "月",
            "SEASON": "季",
            "YEAR": "年",
        }
        period_name_map = {
            "30F_5F_1F": "30F 5F 1F",
            "DAY_30F_5F": "日 30F 5F",
            "WEEK_DAY_30F": "周 日 30F",
            "MONTH_WEEK_DAY": "月 周 日",
            "30M": "30分钟",
            "60M": "60分钟",
            "120M": "120分钟",
            "DAY": "日线",
            "WEEK": "周线",
            "MONTH": "月线",
            "SEASON": "季线",
            "YEAR": "年线",
        }
        if strategy_name == "chanlun_strategy" and cl_preset is not None:
            p_unit = period_unit_map.get(cl_preset["kline_period"], "期")
            p_name = cl_preset["label"]
        elif strategy_name == "chanlun_resonance":
            p_unit = "日"
            p_name = "全级别共振"
        else:
            p_unit = period_unit_map.get(p_clean, "期")
            p_name = period_name_map.get(p_clean, p_clean)

        if strategy_name == "td_sequential":
            if cur_h_seq == 3:
                status_label = "今日高3序列" if p_clean == "DAY" else f"最新{p_name}高3"
            elif cur_h_seq == 9:
                status_label = "高9序列 (见顶警示)" if p_clean == "DAY" else f"{p_name}高9 (见顶警示)"
            elif cur_h_seq == 13:
                status_label = "高13序列 (极致反转)" if p_clean == "DAY" else f"{p_name}高13 (极致反转)"
            else:
                unit_text = f"{days_ago}日前启动" if p_clean == "DAY" else f"{days_ago}{p_unit}前启动"
                status_label = f"高{cur_h_seq}序列 ({unit_text})" if p_clean == "DAY" else f"{p_name}高{cur_h_seq}序列 ({unit_text})"
        elif strategy_name == "wave_theory_impulse":
            w_type = str(trigger_bar.get("wave_type") or "3浪确认")
            if days_ago == 0:
                status_label = f"今日{w_type}" if p_clean == "DAY" else f"最新{p_name}{w_type}"
            else:
                status_label = f"{days_ago}日前{w_type}" if p_clean == "DAY" else f"{days_ago}{p_unit}前{w_type}"
        elif strategy_name == "ma_quadrilateral":
            q_type = str(trigger_bar.get("quad_buy_type") or "闭合加速")
            if not q_type:
                q_type = "闭合加速"
            if days_ago == 0:
                status_label = f"今日四边形·{q_type}" if p_clean == "DAY" else f"最新{p_name}四边形·{q_type}"
            else:
                status_label = f"{days_ago}日前四边形·{q_type}" if p_clean == "DAY" else f"{days_ago}{p_unit}前四边形·{q_type}"
        elif strategy_name in ("chanlun_strategy", "chanlun_resonance"):
            if days_ago == 0:
                status_label = f"最新{chan_tag}"
            else:
                status_label = f"{days_ago}{p_unit}前{chan_tag}"
        else:
            if days_ago == 0:
                status_label = "今日触发" if p_clean == "DAY" else f"最新{p_name}触发"
            else:
                status_label = f"{days_ago}日前触发" if p_clean == "DAY" else f"{days_ago}{p_unit}前触发"

        try:
            from easy_tdx.pattern_recognition import detect_patterns
            patterns = detect_patterns(sig_df)
        except Exception:
            patterns = ["震荡整理"]

        if strategy_name in ("chanlun_strategy", "chanlun_resonance"):
            patterns = [chan_tag] + [p for p in patterns if "缠论" not in p and "买" not in p and "卖" not in p]
        elif strategy_name == "td_sequential":
            td_badge = f"高{cur_h_seq}序列" if cur_h_seq < 9 else (f"高{cur_h_seq}序列(见顶)" if cur_h_seq == 9 else f"高{cur_h_seq}序列")
            patterns = [td_badge] + [p for p in patterns if "TD" not in p and "序列" not in p]
        elif strategy_name == "wave_theory_impulse":
            w_type = str(trigger_bar.get("wave_type") or "3浪主升")
            w_rise = float(trigger_bar.get("wave1_rise") or 0.0)
            w_retrace = float(trigger_bar.get("wave2_retrace") or 0.0)
            if w_rise > 0 and w_retrace > 0:
                wave_badge = f"{w_type}(1浪+{w_rise}%/回踩{w_retrace}%)"
            else:
                wave_badge = f"{w_type}"
            patterns = [wave_badge] + [p for p in patterns if "浪" not in p]
        elif strategy_name == "ma_quadrilateral":
            q_type = str(trigger_bar.get("quad_buy_type") or "闭合加速")
            if not q_type:
                q_type = "闭合加速"
            q_score = float(trigger_bar.get("quad_regularity") or 0.0)
            q_bot = float(trigger_bar.get("quad_bottom_price") or 0.0)
            if q_bot > 0 and q_score > 0:
                quad_badge = f"四边形·{q_type}(底{q_bot}元/规则度{q_score:.0f}分)"
            elif q_score > 0:
                quad_badge = f"四边形·{q_type}(规则度{q_score:.0f}分)"
            else:
                quad_badge = f"四边形·{q_type}"
            patterns = [quad_badge] + [p for p in patterns if "四边形" not in p]

        pattern_status = " · ".join(patterns) if patterns else "震荡整理"

        # 计算历史触发日的形态特征
        if days_ago == 0:
            trigger_patterns = list(patterns)
        else:
            try:
                from easy_tdx.pattern_recognition import detect_patterns
                trigger_df = sig_df.iloc[:trigger_loc + 1]
                trigger_patterns = detect_patterns(trigger_df)
            except Exception:
                trigger_patterns = ["震荡整理"]

        if strategy_name == "chanlun_strategy":
            if chan_tag not in trigger_patterns:
                trigger_patterns = [chan_tag] + [p for p in trigger_patterns if "缠论" not in p and "买" not in p and "卖" not in p]
        elif strategy_name == "td_sequential":
            if "高3序列" not in trigger_patterns:
                trigger_patterns = ["高3序列"] + [p for p in trigger_patterns if "TD" not in p and "序列" not in p]
        elif strategy_name == "wave_theory_impulse":
            w_type = str(trigger_bar.get("wave_type") or "3浪主升")
            w_rise = float(trigger_bar.get("wave1_rise") or 0.0)
            w_retrace = float(trigger_bar.get("wave2_retrace") or 0.0)
            if w_rise > 0 and w_retrace > 0:
                wave_badge = f"{w_type}(1浪+{w_rise}%/回踩{w_retrace}%)"
            else:
                wave_badge = f"{w_type}"
            trigger_patterns = [wave_badge] + [p for p in trigger_patterns if "浪" not in p]
        elif strategy_name == "ma_quadrilateral":
            q_type = str(trigger_bar.get("quad_buy_type") or "闭合加速")
            if not q_type:
                q_type = "闭合加速"
            q_score = float(trigger_bar.get("quad_regularity") or 0.0)
            q_bot = float(trigger_bar.get("quad_bottom_price") or 0.0)
            if q_bot > 0 and q_score > 0:
                t_badge = f"四边形·{q_type}(底{q_bot}元/规则度{q_score:.0f}分)"
            elif q_score > 0:
                t_badge = f"四边形·{q_type}(规则度{q_score:.0f}分)"
            else:
                t_badge = f"四边形·{q_type}"
            if t_badge not in trigger_patterns:
                trigger_patterns = [t_badge] + [p for p in trigger_patterns if "四边形" not in p]

        trigger_pattern_status = " · ".join(trigger_patterns) if trigger_patterns else "震荡整理"

        latest_date = str(last_bar.get("datetime", ""))
        if " " in latest_date:
            latest_date = latest_date.split(" ")[0]
        elif len(latest_date) == 8 and latest_date.isdigit():
            latest_date = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"

        res_dict = {
            "symbol": sym,
            "code": sym,
            "name": stock_name,
            "display": f"{sym} {stock_name}",
            "strategy": st.display_name,
            "strategy_id": strategy_name,
            "period": p_clean,
            "period_name": p_name,
            "price": close_price,
            "change_pct": latest_change_pct,
            "signal_change_pct": signal_change_pct,
            "since_signal_pct": since_signal_pct,
            "latest_change_pct": latest_change_pct,
            "trigger_price": trigger_price,
            "volume": vol,
            "amount_wan": amt_wan,
            "days_ago": days_ago,
            "trigger_days_ago": days_ago,
            "status_label": status_label,
            "signal_date": signal_date or "最新交易日",
            "trigger_date": signal_date or "最新交易日",
            "latest_date": latest_date or "最新收盘",
            "patterns": patterns,
            "pattern_status": pattern_status,
            "trigger_patterns": trigger_patterns,
            "trigger_pattern_status": trigger_pattern_status,
            "status": pattern_status,
            "total_mv_yi": 0.0,
            "market_cap_yi": 0.0,
            "market_cap_str": "--",
        }
        if strategy_name == "chanlun_resonance":
            res_dict["chan_periods"] = ["MONTH", "WEEK", "DAY", "30F", "5F"]
            res_dict["high_period"] = "MONTH"
            res_dict["high_period_name"] = "全周期共振"
            res_dict["period_preset"] = "ALL_CASCADE"
            res_dict["period_preset_label"] = "月周日+周日30M+日30M5F全级别共振"
        elif strategy_name == "chanlun_strategy" and cl_preset is not None:
            res_dict["chan_periods"] = cl_preset["periods"]
            res_dict["high_period"] = cl_preset["high_p"]
            res_dict["high_period_name"] = cl_preset["high_name"]
            res_dict["period_preset"] = cl_preset.get("key", "30F_5F_1F")
            res_dict["period_preset_label"] = cl_preset["label"]
        return res_dict
    except Exception as e:
        logger.debug(f"Strategy {strategy_name} scan error on {sym}: {e}")
        return None


def scan_market_strategy(
    strategy_name: str, 
    symbols: list[str] | None = None,
    universe: str = "core",
    period: str = "DAY",
    lookback_bars: int = 20,
    use_cache: bool = True,
    force_refresh: bool = False,
    progress_callback: Callable[[int, int, int, float], None] | None = None,
    stop_event: threading.Event | None = None,
    max_workers: int | None = None
) -> list[dict[str, Any]]:
    """Scan market universe against strategy using real TDX historical bars with multi-threaded concurrency."""
    if not strategy_name or strategy_name.strip() in ("", "default"):
        strategy_name = "chanlun_resonance"

    if strategy_name == "chanlun_resonance" and (not period or period in ("DAY", "")):
        period = "ALL_CASCADE"
    elif strategy_name == "chanlun_strategy" and (not period or period in ("DAY", "", "ALL_CASCADE")):
        period = "DAY_30F_5F"

    st = get_strategy(strategy_name)
    
    if not symbols:
        symbols = get_universe_symbols(universe)
        
    total_count = len(symbols)
    is_custom_symbols = (symbols is not None and not isinstance(universe, str))

    # 1. Check disk cache if symbols is not custom and not force_refresh
    if not is_custom_symbols and use_cache and not force_refresh:
        cached = _load_cache(strategy_name, universe, period=period, expected_total=total_count, force_refresh=force_refresh)
        if cached is not None:
            if progress_callback:
                progress_callback(total_count, total_count, len(cached), 100.0)
            enrich_stocks_with_inflows(cached)
            return cached

    matched: list[dict[str, Any]] = []

    # Dynamic thread pool sizing (if not explicitly specified)
    if max_workers is None or max_workers <= 0:
        if total_count <= 40:
            pool_workers = min(8, total_count)
        elif total_count <= 500:
            pool_workers = 16
        else:
            pool_workers = 32
    else:
        pool_workers = max(1, min(int(max_workers), 128))

    processed = 0
    with ThreadPoolExecutor(max_workers=pool_workers) as executor:
        futures = {
            executor.submit(_evaluate_stock_for_strategy, sym, strategy_name, st, lookback_bars, period, force_refresh): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            if stop_event is not None and stop_event.is_set():
                logger.info(f"Scan aborted by stop_event at {processed}/{total_count}")
                for f in futures:
                    f.cancel()
                break

            processed += 1
            try:
                res = fut.result()
                if res is not None:
                    matched.append(res)
            except Exception as e:
                logger.debug(f"Strategy eval worker exception: {e}")

            # Throttled progress callback
            if progress_callback and (processed == 1 or processed % 2 == 0 or processed == total_count):
                pct = round((processed / total_count) * 100.0, 1)
                progress_callback(processed, total_count, len(matched), pct)

    # Sort matches: most recent signals first (days_ago ascending), then by volume descending
    matched.sort(key=lambda x: (x.get("days_ago", 999), -x.get("volume", 0)))
    
    enrich_stocks_with_inflows(matched)

    # Save to disk cache if full universe scan completed without abortion
    if (stop_event is None or not stop_event.is_set()) and not is_custom_symbols:
        _save_cache(strategy_name, universe, total_count, matched, period=period)

    return matched
