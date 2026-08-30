"""Test suite for easy_tdx API Endpoints."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from fastapi.testclient import TestClient
from easy_tdx.web.app import _create_app

app = _create_app()
client = TestClient(app)

def test_api_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_api_stocks_search():
    resp = client.get("/api/stocks/search?q=payh")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    codes = [item["code"] for item in data["data"]]
    assert "000001" in codes

def test_api_stocks_info():
    resp = client.get("/api/stocks/info/000001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "000001"
    assert "平安银行" in data["name"]

def test_api_server_hosts():
    resp = client.get("/api/server/hosts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "servers" in data

def test_api_server_test():
    resp = client.post("/api/server/test", json={"timeout": 0.8})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "servers" in data

def test_api_server_switch():
    resp = client.post("/api/server/switch", json={"host": "119.147.212.81", "port": 7709})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"

def test_api_screener_scan():
    resp = client.get("/api/screener/scan?strategy=bull_trend")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "matches" in data

def test_api_backtest_run():
    resp = client.get("/api/backtest/run?symbol=000001&strategy=bull_trend&initial_cash=100000")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "metrics" in data["data"]
    assert "equity_curve" in data["data"]
    assert "trades" in data["data"]
    assert "平安银行" in data["name"]

def test_api_ai_daily_review():
    resp = client.get("/api/ai/daily_review")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "markdown_content" in data["data"]

def test_api_ai_stock_diagnosis():
    resp = client.get("/api/ai/stock_diagnosis/000001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "ratings_4d" in data["data"]

def test_api_ai_strategy_match():
    resp = client.get("/api/ai/strategy_match/000001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["data"]) == 15

def test_api_ai_chat():
    resp = client.post("/api/ai/chat", json={"message": "请问平安银行当前适合什么策略？", "symbol": "000001"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "reply" in data

def test_api_monitor_sentiment():
    resp = client.get("/api/monitor/sentiment")
    assert resp.status_code == 200
    assert resp.json()["data"]["score"] > 0
