"""Comprehensive test suite for easy_tdx quant components:
- 48 Strategies Registry & Signal Generation (including 15 daily_stock_analysis strategies)
- AI Multi-Agent 4D Diagnosis & Market Reviewer
- Market Pulse Emotion Meter & Abnormal Radar
- Stock Pinyin / Code Lookup
- TDX Server Speed Test
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
import pandas as pd
from easy_tdx.strategies.registry import list_all_strategies, get_strategy
from easy_tdx.screener.scanner import generate_mock_kline, scan_market_strategy
from easy_tdx.ai.agents.decision_agent import decision_agent
from easy_tdx.ai.market_reviewer import market_reviewer
from easy_tdx.ai.strategy_agent import strategy_agent
from easy_tdx.market_pulse.emotion_meter import emotion_meter
from easy_tdx.market_pulse.abnormal_radar import abnormal_radar
from easy_tdx.stock_lookup import search_stocks, get_stock_name

def test_strategies_count():
    strategies = list_all_strategies()
    assert len(strategies) >= 40
    names = [s["name"] for s in strategies]
    # Check 15 daily_stock_analysis strategies
    assert "bottom_volume" in names
    assert "bull_trend" in names
    assert "chan_theory_daily" in names
    assert "dragon_head_momentum" in names
    assert "emotion_cycle_daily" in names
    assert "wave_theory_impulse" in names

def test_strategy_signal_generation():
    df = generate_mock_kline("000001", n_bars=60)
    st = get_strategy("bull_trend")
    sig_df = st.generate_signals(df)
    assert "buy_signal" in sig_df.columns
    assert "sell_signal" in sig_df.columns

def test_ai_multi_agent_diagnosis():
    df = generate_mock_kline("000001", n_bars=60)
    diag = decision_agent.analyze("000001", df)
    assert diag["symbol"] == "000001"
    assert "平安银行" in diag["name"]
    assert "ratings_4d" in diag
    assert "overall_score" in diag
    assert "agents_detail" in diag
    assert 0 <= diag["overall_score"] <= 100

def test_daily_review():
    review = market_reviewer.generate_daily_review()
    assert "markdown_content" in review
    assert review["sentiment_score"] > 0

def test_strategy_matching():
    df = generate_mock_kline("000001", n_bars=60)
    matches = strategy_agent.evaluate_stock_strategies("000001", df)
    assert len(matches) == 15
    assert all("strategy_name" in m for m in matches)

def test_market_pulse():
    sentiment = emotion_meter.get_market_sentiment()
    assert sentiment["score"] > 0
    ladder = emotion_meter.get_limit_up_ladder()
    assert len(ladder) > 0
    anomalies = abnormal_radar.get_auction_anomalies()
    assert len(anomalies) > 0

def test_stock_lookup():
    res_pinyin = search_stocks("payh")
    assert any(s["code"] == "000001" for s in res_pinyin)
    name = get_stock_name("600519")
    assert "茅台" in name
