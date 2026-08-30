"""Quick launcher for easy_tdx Web & AI Quant Platform."""
import os
import sys
from pathlib import Path

# Add src to path
src_dir = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src_dir))

import uvicorn
from easy_tdx.web.app import _create_app

app = _create_app()

if __name__ == "__main__":
    print("=" * 65)
    print("🚀 easy_tdx 量化投研与多智能体监控工作台正在启动...")
    print("📊 网页访问入口: http://localhost:8000")
    print("📡 通达信原生 TCP 直连 + daily_stock_analysis 战法 + tickflow 监控")
    print("=" * 65)
    uvicorn.run(app, host="0.0.0.0", port=8000)
