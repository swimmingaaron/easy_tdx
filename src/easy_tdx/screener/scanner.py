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
from easy_tdx.MyTT import REF, BARSLASTCOUNT, TD_SEQUENTIAL

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

def _get_cache_file(strategy_name: str, universe: str) -> Path:
    today_str = date.today().strftime("%Y%m%d")
    return _get_cache_dir() / f"{strategy_name}_{universe}_{today_str}.json"

def _load_cache(strategy_name: str, universe: str, expected_total: int = 0, force_refresh: bool = False) -> list[dict[str, Any]] | None:
    if force_refresh:
        return None
    cache_f = _get_cache_file(strategy_name, universe)
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

def _save_cache(strategy_name: str, universe: str, total_count: int, matches: list[dict[str, Any]]) -> None:
    try:
        cache_f = _get_cache_file(strategy_name, universe)
        payload = {
            "strategy": strategy_name,
            "universe": universe,
            "total_count": total_count,
            "date": date.today().strftime("%Y%m%d"),
            "timestamp": time.time(),
            "matches_count": len(matches),
            "matches": matches
        }
        with open(cache_f, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(matches)} screener matches (total={total_count}) to cache {cache_f.name}")
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

from concurrent.futures import ThreadPoolExecutor, as_completed

_DAILY_KLINE_CACHE: dict[str, tuple[str, float, pd.DataFrame]] = {}
_DAILY_KLINE_LOCK = threading.Lock()


def clear_screener_cache() -> None:
    """Clear in-memory daily kline cache for all strategies."""
    with _DAILY_KLINE_LOCK:
        _DAILY_KLINE_CACHE.clear()
        logger.info("Cleared screener in-memory daily kline cache.")


def _get_or_fetch_daily_kline(sym: str, force_refresh: bool = False) -> pd.DataFrame | None:
    today_str = date.today().strftime("%Y%m%d")
    now_ts = time.time()
    
    if not force_refresh:
        with _DAILY_KLINE_LOCK:
            if sym in _DAILY_KLINE_CACHE:
                d_str, cached_ts, cached_df = _DAILY_KLINE_CACHE[sym]
                if d_str == today_str:
                    from easy_tdx.market_overview import is_trading_time
                    max_age = INTRADAY_CACHE_TTL_SEC if is_trading_time() else POST_MARKET_CACHE_TTL_SEC
                    if (now_ts - cached_ts) < max_age:
                        return cached_df

    from easy_tdx.market_data import fetch_kline_with_pool, fetch_security_kline
    df = fetch_kline_with_pool(sym, category="DAY", count=140)
    if df is None or len(df) < 20:
        df = fetch_security_kline(sym, category="DAY", count=140)
    if df is not None and len(df) >= 20:
        with _DAILY_KLINE_LOCK:
            _DAILY_KLINE_CACHE[sym] = (today_str, now_ts, df)
        return df
    return None


def _evaluate_stock_for_strategy(
    sym: str,
    strategy_name: str,
    st: Any,
    lookback_bars: int,
    force_refresh: bool = False
) -> dict[str, Any] | None:
    df = _get_or_fetch_daily_kline(sym, force_refresh=force_refresh)
    if df is None or len(df) < 20:
        return None

    try:
        sig_df = st.generate_signals(df)
        if sig_df is None:
            return None

        if strategy_name == "td_sequential":
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

        last_bar = sig_df.iloc[-1]
        stock_name = get_stock_name(sym)

        close_price = round(float(last_bar["close"]), 2)
        trigger_price = round(float(trigger_bar["close"]), 2)
        vol = int(last_bar["volume"])
        amt_wan = round(float(last_bar.get("amount", 0.0)) / 10000.0, 1)

        if trigger_loc > 0:
            trigger_prev_close = float(sig_df.iloc[trigger_loc - 1]["close"])
            signal_change_pct = round((trigger_price - trigger_prev_close) / trigger_prev_close * 100.0, 2) if trigger_prev_close > 0 else 0.0
        elif "change_pct" in trigger_bar and pd.notna(trigger_bar["change_pct"]):
            signal_change_pct = round(float(trigger_bar["change_pct"]), 2)
        else:
            signal_change_pct = 0.0

        since_signal_pct = round((close_price - trigger_price) / trigger_price * 100.0, 2) if trigger_price > 0 else 0.0

        if len(sig_df) >= 2:
            last_prev_close = float(sig_df.iloc[-2]["close"])
            latest_change_pct = round((close_price - last_prev_close) / last_prev_close * 100.0, 2) if last_prev_close > 0 else 0.0
        else:
            latest_change_pct = 0.0

        signal_date = str(trigger_bar.get("datetime", ""))
        if " " in signal_date:
            signal_date = signal_date.split(" ")[0]
        elif len(signal_date) == 8 and signal_date.isdigit():
            signal_date = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:]}"

        if strategy_name == "td_sequential":
            if cur_h_seq == 3:
                status_label = "今日高3序列"
            elif cur_h_seq == 9:
                status_label = "高9序列 (见顶警示)"
            elif cur_h_seq == 13:
                status_label = "高13序列 (极致反转)"
            else:
                status_label = f"高{cur_h_seq}序列 ({days_ago}日前启动)"
        else:
            status_label = "今日触发" if days_ago == 0 else f"{days_ago}日前触发"

        try:
            from easy_tdx.pattern_recognition import detect_patterns
            patterns = detect_patterns(sig_df)
        except Exception:
            patterns = ["震荡整理"]

        if strategy_name == "td_sequential":
            td_badge = f"高{cur_h_seq}序列" if cur_h_seq < 9 else (f"高{cur_h_seq}序列(见顶)" if cur_h_seq == 9 else f"高{cur_h_seq}序列")
            patterns = [td_badge] + [p for p in patterns if "TD" not in p and "序列" not in p]

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

        if strategy_name == "td_sequential":
            if "高3序列" not in trigger_patterns:
                trigger_patterns = ["高3序列"] + [p for p in trigger_patterns if "TD" not in p and "序列" not in p]

        trigger_pattern_status = " · ".join(trigger_patterns) if trigger_patterns else "震荡整理"

        latest_date = str(last_bar.get("datetime", ""))
        if " " in latest_date:
            latest_date = latest_date.split(" ")[0]
        elif len(latest_date) == 8 and latest_date.isdigit():
            latest_date = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"

        return {
            "symbol": sym,
            "code": sym,
            "name": stock_name,
            "display": f"{sym} {stock_name}",
            "strategy": st.display_name,
            "strategy_id": strategy_name,
            "price": close_price,
            "change_pct": signal_change_pct,
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
    except Exception as e:
        logger.debug(f"Strategy {strategy_name} scan error on {sym}: {e}")
        return None


def scan_market_strategy(
    strategy_name: str, 
    symbols: list[str] | None = None,
    universe: str = "core",
    lookback_bars: int = 20,
    use_cache: bool = True,
    force_refresh: bool = False,
    progress_callback: Callable[[int, int, int, float], None] | None = None,
    stop_event: threading.Event | None = None
) -> list[dict[str, Any]]:
    """Scan market universe against strategy using real TDX historical bars with multi-threaded concurrency.
    
    Args:
        strategy_name: Identifier for strategy in registry
        symbols: Optional custom list of symbols. If None, loaded based on universe.
        universe: Universe tier: 'core' (35), 'hs300' (300), 'zz500' (500), 'zz1000' (1000), 'all' (5200+)
        lookback_bars: Signal trigger lookback window
        use_cache: If True, check disk cache for today's completed scan
        force_refresh: If True, bypass all memory and disk caches and fetch fresh intraday data
        progress_callback: Optional callable(processed, total, matches_count, percent)
        stop_event: Optional threading.Event to abort early
    """
    st = get_strategy(strategy_name)
    
    if not symbols:
        symbols = get_universe_symbols(universe)
        
    total_count = len(symbols)
    is_custom_symbols = (symbols is not None and not isinstance(universe, str))

    # 1. Check disk cache if symbols is not custom and not force_refresh
    if not is_custom_symbols and use_cache and not force_refresh:
        cached = _load_cache(strategy_name, universe, expected_total=total_count, force_refresh=force_refresh)
        if cached is not None:
            if progress_callback:
                progress_callback(total_count, total_count, len(cached), 100.0)
            enrich_stocks_with_inflows(cached)
            return cached

    matched: list[dict[str, Any]] = []

    # Dynamic thread pool sizing
    if total_count <= 40:
        max_workers = min(8, total_count)
    elif total_count <= 500:
        max_workers = 16
    else:
        max_workers = 32

    processed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_evaluate_stock_for_strategy, sym, strategy_name, st, lookback_bars, force_refresh): sym
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
        _save_cache(strategy_name, universe, total_count, matched)

    return matched
