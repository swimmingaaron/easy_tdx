"""测试 chanlun-pro 架构启发的 K线重采样与磁盘持久化缓存。"""

import pandas as pd
import pytest
from easy_tdx.chanlun.resample import convert_kline_frequency, can_resample_from
from easy_tdx.chanlun.kline_cache import KlineDiskCache


def test_can_resample_from():
    assert can_resample_from("5F", "30F") is True
    assert can_resample_from("5M", "60M") is True
    assert can_resample_from("5MIN", "120MIN") is True
    assert can_resample_from("1F", "5F") is True
    assert can_resample_from("1F", "30F") is True
    assert can_resample_from("DAY", "30F") is False
    assert can_resample_from("30F", "5F") is False


def test_convert_kline_frequency():
    # 构造假数据 5分钟 24 根
    dates = pd.date_range("2026-10-12 09:35", periods=24, freq="5min")
    df = pd.DataFrame({
        "datetime": dates.strftime("%Y-%m-%d %H:%M"),
        "open": [10.0 + i * 0.1 for i in range(24)],
        "high": [10.2 + i * 0.1 for i in range(24)],
        "low": [9.9 + i * 0.1 for i in range(24)],
        "close": [10.1 + i * 0.1 for i in range(24)],
        "volume": [1000 + i * 10 for i in range(24)],
        "amount": [10000 + i * 100 for i in range(24)],
    })

    df_30m = convert_kline_frequency(df, "30M")
    assert not df_30m.empty
    assert len(df_30m) == 4  # 24 根 5M 应该合成 4 根 30M
    assert "datetime" in df_30m.columns
    assert "close" in df_30m.columns


def test_kline_disk_cache(tmp_path):
    cache = KlineDiskCache(cache_dir=tmp_path)
    df = pd.DataFrame({
        "datetime": ["2026-10-12 09:35", "2026-10-12 09:40"],
        "open": [10.0, 10.1],
        "high": [10.2, 10.3],
        "low": [9.9, 10.0],
        "close": [10.1, 10.2],
        "volume": [1000, 2000],
        "amount": [10000, 20000],
    })

    cache.write_cached("000001", "5M", df)
    cached = cache.read_cached("000001", "5M")
    assert cached is not None
    assert len(cached) == 2

    # 测试增量合并
    new_df = pd.DataFrame({
        "datetime": ["2026-10-12 09:40", "2026-10-12 09:45"],
        "open": [10.1, 10.2],
        "high": [10.3, 10.4],
        "low": [10.0, 10.1],
        "close": [10.25, 10.35],
        "volume": [2500, 3000],
        "amount": [25000, 30000],
    })
    merged = cache.merge_and_update("000001", "5M", cached, new_df)
    assert len(merged) == 3  # 09:40 被更新覆盖，总共 3 根
    assert merged.iloc[1]["close"] == 10.25
    assert merged.iloc[2]["close"] == 10.35
