"""K线本地磁盘持久化缓存与增量更新管理器。

参考 chanlun-pro 的 FileCacheDB 架构：
1. 本地磁盘持久化保存历史已获取的 K 线序列；
2. 增量更新机制：已有历史数据时，仅向行情服务器请求最新增量数据（少量条数），
   在本地高效拼接去重，极大减轻网络包传输负担并缩减网络往返延迟；
3. 休市/非交易时间智能拦截：若本地数据已覆盖最新交易收盘时间，0 网络请求瞬时返回。
"""

from __future__ import annotations

import logging
import os
import pathlib
import threading
import time
from typing import Any
import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()


class KlineDiskCache:
    """参考 chanlun-pro FileCacheDB 实现的高性能 K 线磁盘缓存管理器。"""

    def __init__(self, cache_dir: pathlib.Path | str | None = None) -> None:
        if cache_dir is None:
            # 优先使用用户 home 目录下的 .easy_tdx/cache/klines
            home = pathlib.Path.home()
            self.base_dir = home / ".easy_tdx" / "cache" / "klines"
        else:
            self.base_dir = pathlib.Path(cache_dir)

        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, symbol: str, period: str) -> pathlib.Path:
        clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
        clean_p = period.strip().upper()
        return self.base_dir / f"{clean_sym}_{clean_p}.pkl"

    def read_cached(self, symbol: str, period: str) -> pd.DataFrame | None:
        """从本地磁盘读取 K 线缓存。"""
        fp = self._get_file_path(symbol, period)
        if not fp.is_file():
            return None
        try:
            with open(fp, "rb") as f:
                df = pd.read_pickle(f)
            if isinstance(df, pd.DataFrame) and not df.empty and "datetime" in df.columns:
                return df
        except Exception as e:
            logger.debug("读取本地 K 线缓存异常 %s %s: %s", symbol, period, e)
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass
        return None

    def write_cached(self, symbol: str, period: str, df: pd.DataFrame) -> None:
        """写入/更新本地磁盘 K 线缓存。"""
        if df is None or df.empty or len(df) == 0:
            return
        fp = self._get_file_path(symbol, period)
        try:
            # 限制单文件最大保留 4000 根以控制磁盘大小与读取耗时
            save_df = df.iloc[-4000:].copy().reset_index(drop=True)
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
    ) -> pd.DataFrame:
        """增量合并已有数据与新数据，去重排序并异步持久化。"""
        if existing_df is None or existing_df.empty:
            if new_df is not None and not new_df.empty:
                self.write_cached(symbol, period, new_df)
                return new_df
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])

        if new_df is None or new_df.empty:
            return existing_df

        # 拼接并以 datetime 为唯一键去重，保留最新更新（keep='last' 保证最后一根未完结 bar 能被最新行情覆盖）
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined.drop_duplicates(subset=["datetime"], keep="last", inplace=True)
        combined.sort_values(by="datetime", inplace=True)
        combined.reset_index(drop=True, inplace=True)

        self.write_cached(symbol, period, combined)
        return combined


_GLOBAL_DISK_CACHE: KlineDiskCache | None = None


def get_global_kline_disk_cache() -> KlineDiskCache:
    """获取全局 K 线磁盘缓存单例。"""
    global _GLOBAL_DISK_CACHE
    if _GLOBAL_DISK_CACHE is None:
        with _CACHE_LOCK:
            if _GLOBAL_DISK_CACHE is None:
                _GLOBAL_DISK_CACHE = KlineDiskCache()
    return _GLOBAL_DISK_CACHE
