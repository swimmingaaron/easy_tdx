"""Quick launcher for easy_tdx Web & AI Quant Platform with CLI arguments support."""
import os
import sys
import socket
import argparse
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
            s.settimeout(0.4)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                print(f">>> 检测到端口 {port} 处于占用状态，正在为您自动释放并清理旧进程...")
                if sys.platform == "win32":
                    out = subprocess.check_output(
                        f'powershell -Command "Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"',
                        shell=True
                    ).decode()
                    for pid_str in out.strip().split():
                        pid = pid_str.strip()
                        if pid and pid.isdigit() and int(pid) != os.getpid() and int(pid) != 0:
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
    except Exception:
        pass

def _open_browser(url: str):
    """Open default web browser after server starts."""
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Could not open browser automatically: {e}")

def parse_args():
    """Parse command line arguments for port, host, and server options."""
    parser = argparse.ArgumentParser(
        description="easy_tdx 量化投研与多智能体监控工作台快速启动器",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="Web 服务监听端口 (默认: 8000，例如: --port 8900)"
    )
    parser.add_argument(
        "--host", "-H",
        type=str,
        default="0.0.0.0",
        help="Web 服务绑定主机地址"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="启动后不自动打开浏览器"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用热重载开发模式"
    )
    parser.add_argument(
        "--tdx-host",
        type=str,
        default=None,
        help="指定通达信直连主站 IP (可选)"
    )
    parser.add_argument(
        "--tdx-port",
        type=int,
        default=7709,
        help="指定通达信直连主站端口 (默认: 7709)"
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    port = args.port
    host = args.host
    
    # Clean up port if occupied
    ensure_port_free(port)
    
    display_host = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
    url = f"http://{display_host}:{port}"
    
    print("=" * 68)
    print(">>> easy_tdx 量化投研与多智能体监控工作台正在启动...")
    print(f">>> 网页访问入口: {url}")
    print(f">>> 监听配置: host={host}, port={port}")
    if args.tdx_host:
        print(f">>> 指定通达信行情节点: {args.tdx_host}:{args.tdx_port}")
    print(">>> 通达信原生 TCP 直连 + daily_stock_analysis 战法 + tickflow 监控")
    if not args.no_browser:
        print(">>> 正在自动为您打开浏览器...")
    print("=" * 68)
    
    # Open browser automatically after 1.2s delay if not disabled
    if not args.no_browser:
        threading.Timer(1.2, _open_browser, args=[url]).start()
    
    import uvicorn
    import copy
    from uvicorn.config import LOGGING_CONFIG
    from easy_tdx.web.app import _create_app
    app = _create_app(host=args.tdx_host, port=args.tdx_port)
    
    # Configure unified timestamps for backend access and server logs
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["formatters"]["access"]["fmt"] = '[%(asctime)s] %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    log_config["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    log_config["formatters"]["default"]["fmt"] = '[%(asctime)s] %(levelprefix)s %(message)s'
    log_config["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    
    if args.reload:
        uvicorn.run("easy_tdx.web.app:_create_app", host=host, port=port, factory=True, reload=True, log_config=log_config)
    else:
        uvicorn.run(app, host=host, port=port, log_config=log_config)
