"""K线多周期重采样合成模块。

参考 chanlun-pro 的周期重采样与低到高频率转换算法，
支持将基础高频 K 线（如 1M、5M）聚合重采样生成 15M、30M、60M、120M、日线等高级别 K 线。
严格遵循 A 股交易时间区间规则（09:30-11:30, 13:00-15:00），确保 60M 与 120M K 线对齐精准。
"""

from __future__ import annotations

import logging
from typing import Any
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# A 股 60分钟与 120分钟交易时间区间映射表
A_SHARE_INTRA_CONFIGS: dict[str, dict[str, tuple[str, str]]] = {
    "60M": {
        "10:30:00": ("09:00:00", "10:30:00"),
        "11:30:00": ("10:30:01", "11:30:00"),
        "14:00:00": ("13:00:00", "14:00:00"),
        "15:00:00": ("14:00:01", "15:00:00"),
    },
    "120M": {
        "11:30:00": ("09:00:00", "11:30:00"),
        "15:00:00": ("13:00:00", "15:00:00"),
    },
}


def can_resample_from(base_freq: str, target_freq: str) -> bool:
    """判断 target_freq 是否能够从 base_freq 在内存中无损或高保真重采样合成。

    例如：
    - 从 5M/5F 可以合成 15M/15F, 30M/30F, 60M/60F, 120M/120F
    - 从 1M/1F 可以合成 5M, 15M, 30M, 60M, 120M
    """
    b = base_freq.upper().replace("MIN", "").replace("F", "").replace("M", "")
    t = target_freq.upper().replace("MIN", "").replace("F", "").replace("M", "")

    # 规范化别名
    if b in ("5",):
        return t in ("15", "30", "60", "120")
    if b in ("1",):
        return t in ("5", "15", "30", "60", "120")
    return False


def convert_kline_frequency(
    df: pd.DataFrame,
    to_freq: str,
) -> pd.DataFrame:
    """将基础 K 线 DataFrame 重采样合成为目标周期 K 线。

    Args:
        df: 包含 datetime, open, high, low, close, volume, (amount) 的 DataFrame
        to_freq: 目标周期代码，如 "15M", "30M", "60M", "120M", "DAY"

    Returns:
        合成后的目标周期 DataFrame
    """
    if df is None or df.empty or len(df) == 0:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])

    clean_freq = to_freq.upper().replace("MIN", "M").replace("F", "M")
    if clean_freq in ("DAILY", "D"):
        clean_freq = "DAY"

    has_amount = "amount" in df.columns

    # 准备标准 datetime 列
    work_df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(work_df["datetime"]):
        work_df["dt"] = pd.to_datetime(work_df["datetime"].astype(str))
    else:
        work_df["dt"] = work_df["datetime"]

    # 1. 针对 60M 和 120M 的 A 股非均匀交易时间段特别处理
    if clean_freq in ("60M", "120M"):
        cfg = A_SHARE_INTRA_CONFIGS[clean_freq]
        date_str = work_df["dt"].dt.strftime("%Y-%m-%d")
        time_str = work_df["dt"].dt.strftime("%H:%M:%S")

        work_df["new_dt"] = pd.NaT
        for target_time_str, (start_t, end_t) in cfg.items():
            mask = (time_str >= start_t) & (time_str <= end_t)
            work_df.loc[mask, "new_dt"] = pd.to_datetime(date_str[mask] + " " + target_time_str)

        # 过滤未匹配到的杂项时间（如集合竞价异常时间点）
        valid_df = work_df.dropna(subset=["new_dt"]).copy()
        if valid_df.empty:
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])

        agg_dict: dict[str, Any] = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        if has_amount:
            agg_dict["amount"] = "sum"

        grouped = valid_df.groupby("new_dt").agg(agg_dict).reset_index()
        grouped["datetime"] = grouped["new_dt"].dt.strftime("%Y-%m-%d %H:%M")
        cols = ["datetime", "open", "high", "low", "close", "volume"]
        if has_amount:
            cols.append("amount")
        else:
            grouped["amount"] = grouped["volume"] * grouped["close"]
            cols.append("amount")
        return grouped[cols].sort_values("datetime").reset_index(drop=True)

    # 2. 针对 15M、30M 使用标准 pandas resample
    if clean_freq in ("15M", "30M"):
        freq_alias = "15min" if clean_freq == "15M" else "30min"
        work_df.set_index("dt", inplace=True)
        agg_dict = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        if has_amount:
            agg_dict["amount"] = "sum"

        resampled = work_df.resample(freq_alias, label="right", closed="right").agg(agg_dict)
        resampled.dropna(subset=["close"], inplace=True)
        resampled.reset_index(inplace=True)
        resampled["datetime"] = resampled["dt"].dt.strftime("%Y-%m-%d %H:%M")
        cols = ["datetime", "open", "high", "low", "close", "volume"]
        if has_amount:
            cols.append("amount")
        else:
            resampled["amount"] = resampled["volume"] * resampled["close"]
            cols.append("amount")
        return resampled[cols].sort_values("datetime").reset_index(drop=True)

    # 3. 针对日线 DAY
    if clean_freq == "DAY":
        work_df["day_str"] = work_df["dt"].dt.strftime("%Y-%m-%d")
        agg_dict = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        if has_amount:
            agg_dict["amount"] = "sum"
        grouped = work_df.groupby("day_str").agg(agg_dict).reset_index()
        grouped.rename(columns={"day_str": "datetime"}, inplace=True)
        cols = ["datetime", "open", "high", "low", "close", "volume"]
        if has_amount:
            cols.append("amount")
        else:
            grouped["amount"] = grouped["volume"] * grouped["close"]
            cols.append("amount")
        return grouped[cols].sort_values("datetime").reset_index(drop=True)

    # 无法直接重采样的，返回原始 DataFrame
    return df
