"""Quick launcher for easy_tdx Web & AI Quant Platform."""
import os
import sys
import socket
import subprocess
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

def ensure_port_free(port: int = 8000):
    """Check if port is occupied, and auto-terminate stale previous server processes."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                print(f">>> 检测到端口 {port} 处于占用状态，正在为您自动释放并清理旧进程...")
                if sys.platform == "win32":
                    out = subprocess.check_output(f'powershell -Command "Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"', shell=True).decode()
                    for pid_str in out.strip().split():
                        pid = pid_str.strip()
                        if pid and pid.isdigit() and int(pid) != os.getpid() and int(pid) != 0:
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
    except Exception:
        pass

def _open_browser(url: str = "http://localhost:8000"):
    """Open default web browser after server starts."""
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Could not open browser automatically: {e}")

if __name__ == "__main__":
    port = 8000
    ensure_port_free(port)
    
    url = f"http://localhost:{port}"
    print("=" * 65)
    print(">>> easy_tdx 量化投研与多智能体监控工作台正在启动...")
    print(f">>> 网页访问入口: {url}")
    print(">>> 通达信原生 TCP 直连 + daily_stock_analysis 战法 + tickflow 监控")
    print(">>> 正在自动为您打开浏览器...")
    print("=" * 65)
    
    # Open browser automatically after 1.2s delay
    threading.Timer(1.2, _open_browser, args=[url]).start()
    
    import uvicorn
    from easy_tdx.web.app import _create_app
    app = _create_app()
    uvicorn.run(app, host="0.0.0.0", port=port)
