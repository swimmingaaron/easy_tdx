"""Quick launcher for easy_tdx Web & AI Quant Platform."""
import os
import sys
import threading
import webbrowser
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add src to path
src_dir = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src_dir))

import uvicorn
from easy_tdx.web.app import _create_app

app = _create_app()

def _open_browser(url: str = "http://localhost:8000"):
    """Open default web browser after server starts."""
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Could not open browser automatically: {e}")

if __name__ == "__main__":
    url = "http://localhost:8000"
    print("=" * 65)
    print(">>> easy_tdx 量化投研与多智能体监控工作台正在启动...")
    print(f">>> 网页访问入口: {url}")
    print(">>> 通达信原生 TCP 直连 + daily_stock_analysis 战法 + tickflow 监控")
    print(">>> 正在自动为您打开浏览器...")
    print("=" * 65)
    
    # Open browser automatically after 1.2s delay
    threading.Timer(1.2, _open_browser, args=[url]).start()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
