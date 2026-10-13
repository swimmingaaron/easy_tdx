"""全局 K 线本地磁盘持久化缓存与增量更新管理器。

参考 chanlun-pro 的 FileCacheDB 核心架构：
1. 磁盘持久化保存每只标的、周期、复权类型的历史 K 线数据；
2. 增量更新机制：已有历史数据时，仅向行情服务器请求最新微量增量（少量条数），
   在本地高效拼接去重，极大减轻网络包传输负担并缩减网络往返延迟；
3. 休市/非交易时间智能拦截：若本地数据已覆盖最新交易收盘时间，0 网络请求瞬时返回。
"""

from __future__ import annotations

import datetime
import logging
import pathlib
import threading
import time
from typing import Any
import pandas as pd
import zoneinfo

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_SH_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")


def is_trade_session() -> bool:
    """判断当前是否处于 A 股交易时段。"""
    now = datetime.datetime.now(_SH_TZ)
    if now.weekday() >= 5:  # 周六、周日
        return False
    t = now.time()
    morning = datetime.time(9, 15) <= t <= datetime.time(11, 35)
    afternoon = datetime.time(12, 55) <= t <= datetime.time(15, 5)
    return morning or afternoon


class KlineDiskCache:
    """参考 chanlun-pro FileCacheDB 实现的全局高性能 K 线磁盘缓存管理器。"""

    def __init__(self, cache_dir: pathlib.Path | str | None = None) -> None:
        if cache_dir is None:
            home = pathlib.Path.home()
            self.base_dir = home / ".easy_tdx" / "cache" / "klines"
        else:
            self.base_dir = pathlib.Path(cache_dir)

        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, symbol: str, period: Any, adjust: Any = "QFQ") -> pathlib.Path:
        clean_sym = str(symbol).strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
        clean_p = str(period).strip().upper().replace("MIN_", "").replace("MIN", "M").replace("F", "M")
        clean_adj = str(adjust).strip().upper()
        return self.base_dir / f"{clean_sym}_{clean_p}_{clean_adj}.pkl"

    def read_cached(self, symbol: str, period: str, adjust: str = "QFQ") -> pd.DataFrame | None:
        """从本地磁盘读取 K 线缓存。"""
        fp = self._get_file_path(symbol, period, adjust)
        if not fp.is_file():
            return None
        try:
            with open(fp, "rb") as f:
                df = pd.read_pickle(f)
            if isinstance(df, pd.DataFrame) and not df.empty and ("datetime" in df.columns or "date" in df.columns):
                return df
        except Exception as e:
            logger.debug("读取本地 K 线缓存异常 %s %s: %s", symbol, period, e)
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass
        return None

    def write_cached(self, symbol: str, period: str, df: pd.DataFrame, adjust: str = "QFQ") -> None:
        """写入/更新本地磁盘 K 线缓存。"""
        if df is None or df.empty or len(df) == 0:
            return
        fp = self._get_file_path(symbol, period, adjust)
        try:
            # 限制单文件最大保留 5000 根以控制磁盘大小与读取耗时
            save_df = df.iloc[-5000:].copy().reset_index(drop=True)
            with open(fp, "wb") as f:
                save_df.to_pickle(f)
        except Exception as e:
            logger.debug("写入本地 K 线缓存异常 %s %s: %s", symbol, period, e)

    def merge_and_update(
        self,
        symbol: str,
        period: str,
        existing_df: pd.DataFrame | None,
        new_df: pd.DataFrame | None,
        adjust: str = "QFQ",
    ) -> pd.DataFrame:
        """增量合并已有数据与新数据，去重排序并持久化。"""
        if existing_df is None or existing_df.empty:
            if new_df is not None and not new_df.empty:
                self.write_cached(symbol, period, new_df, adjust)
                return new_df
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "vol", "amount"])

        if new_df is None or new_df.empty:
            return existing_df

        # 识别时间列名（date 或 datetime）
        dt_col = "date" if "date" in existing_df.columns else "datetime"
        if dt_col not in new_df.columns:
            other_dt = "datetime" if dt_col == "date" else "date"
            if other_dt in new_df.columns:
                new_df = new_df.rename(columns={other_dt: dt_col})

        # 拼接并以时间列为唯一键去重，保留最新更新（keep='last' 保证最后一根未完结 bar 能被最新行情覆盖）
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        if dt_col in combined.columns:
            combined.drop_duplicates(subset=[dt_col], keep="last", inplace=True)
            combined.sort_values(by=dt_col, inplace=True)
            combined.reset_index(drop=True, inplace=True)

        self.write_cached(symbol, period, combined, adjust)
        return combined

    def is_up_to_date(self, df: pd.DataFrame, period: str) -> bool:
        """判断缓存中的数据是否已经是最新的（例如非交易时间且已包含最后收盘 bar）。"""
        if df is None or df.empty or len(df) == 0:
            return False

        now = datetime.datetime.now(_SH_TZ)
        dt_col = "date" if "date" in df.columns else "datetime"
        if dt_col not in df.columns:
            return False
        latest_str = str(df[dt_col].iloc[-1]).strip()

        # 1. 周末判断：最后一条日期应为周五或更近
        if now.weekday() in (5, 6):
            return True

        # 2. 工作日收盘后 (15:10 之后)
        t = now.time()
        today_str = now.strftime("%Y-%m-%d")
        if t >= datetime.time(15, 10):
            if latest_str.startswith(today_str):
                return True

        # 3. 工作日开盘前 (09:15 之前)
        if t < datetime.time(9, 15):
            return True

        # 4. 工作日中午休市 (11:35 - 12:55)
        if datetime.time(11, 35) <= t <= datetime.time(12, 55):
            if latest_str.startswith(today_str) and ("11:30" in latest_str or "11:25" in latest_str):
                return True

        return False


_GLOBAL_DISK_CACHE: KlineDiskCache | None = None


def get_global_kline_disk_cache() -> KlineDiskCache:
    """获取全局 K 线磁盘缓存单例。"""
    global _GLOBAL_DISK_CACHE
    if _GLOBAL_DISK_CACHE is None:
        with _CACHE_LOCK:
            if _GLOBAL_DISK_CACHE is None:
                _GLOBAL_DISK_CACHE = KlineDiskCache()
    return _GLOBAL_DISK_CACHE
