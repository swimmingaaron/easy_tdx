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
    occupied = False
    for target in ('127.0.0.1', '::1'):
        try:
            family = socket.AF_INET6 if ':' in target else socket.AF_INET
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((target, port)) == 0:
                    occupied = True
                    break
        except Exception:
            pass

    if occupied:
        print(f">>> 检测到端口 {port} 处于占用状态，正在为您自动释放并清理旧进程...")
        if sys.platform == "win32":
            try:
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


def get_lan_ips() -> list[str]:
    """获取本机所有可用局域网 IPv4 地址。"""
    ips = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if ip and not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("223.5.5.5", 80))
            ips.add(s.getsockname()[0])
    except Exception:
        pass
    return sorted(list(ips))


def get_listen_sockets(host: str, port: int) -> list[socket.socket]:
    """根据 host 配置构建监听套接字。当指定 '::'、'[::]' 或 'dual' 时，开启 IPv4 + IPv6 双栈全网监听。"""
    sockets = []
    if host in ("::", "[::]", "dual", "all"):
        # 1. 绑定 IPv4 全接口 (0.0.0.0) -> 支持 127.0.0.1, localhost, 局域网 192.168.x.x
        try:
            s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s4.bind(('0.0.0.0', port))
            s4.listen(2048)
            s4.set_inheritable(True)
            sockets.append(s4)
        except Exception as e:
            print(f">>> IPv4 (0.0.0.0:{port}) 监听绑定提示: {e}")

        # 2. 绑定 IPv6 全接口 (::) -> 支持 [::1], 本机及公网 IPv6
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Windows/Linux 显式设置 IPV6_V6ONLY=1，确保 IPv4 与 IPv6 独立并行运作、互不冲突
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.bind(('::', port))
            s6.listen(2048)
            s6.set_inheritable(True)
            sockets.append(s6)
        except Exception as e:
            print(f">>> IPv6 ([::]:{port}) 监听绑定提示 (如系统未开启IPv6可忽略): {e}")

    return sockets


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
        help="Web 服务监听端口 (默认: 8000，例如: --port 2052)"
    )
    parser.add_argument(
        "--host", "-H",
        type=str,
        default="0.0.0.0",
        help="Web 服务绑定主机地址 (默认: 0.0.0.0；传 '::' 或 'dual' 时同时监听 IPv4+IPv6 双栈，支持 localhost/局域网IP/公网IPv6 全面访问)"
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

    # 尝试构建多栈监听套接字
    listen_sockets = get_listen_sockets(host, port)

    url = f"http://localhost:{port}"

    print("=" * 68)
    print(">>> easy_tdx 量化投研与多智能体监控工作台正在启动...")
    print(f">>> 本地访问入口: {url} (http://127.0.0.1:{port})")
    lan_ips = get_lan_ips()
    for lip in lan_ips:
        print(f">>> 局域网访问:   http://{lip}:{port}")
    if host in ("::", "[::]", "all", "dual"):
        print(f">>> IPv6 访问入口: http://[::1]:{port}")
        print(f">>> 网络监听模式: IPv4 (0.0.0.0) + IPv6 (::) 全网双栈监听")
    else:
        print(f">>> 网络监听模式: host={host}, port={port}")

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
    from uvicorn.config import Config, LOGGING_CONFIG
    from uvicorn.server import Server
    from uvicorn.supervisors import ChangeReload
    from easy_tdx.web.app import _create_app

    # Configure unified timestamps for backend access and server logs
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["formatters"]["access"]["fmt"] = '[%(asctime)s] %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    log_config["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    log_config["formatters"]["default"]["fmt"] = '[%(asctime)s] %(levelprefix)s %(message)s'
    log_config["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"

    if listen_sockets:
        if args.reload:
            config = Config(
                "easy_tdx.web.app:_create_app",
                host=host,
                port=port,
                factory=True,
                reload=True,
                log_config=log_config
            )
            server = Server(config=config)
            ChangeReload(config, target=server.run, sockets=listen_sockets).run()
        else:
            app = _create_app(host=args.tdx_host, port=args.tdx_port)
            config = Config(app, host=host, port=port, log_config=log_config)
            server = Server(config=config)
            server.run(sockets=listen_sockets)
    else:
        if args.reload:
            uvicorn.run("easy_tdx.web.app:_create_app", host=host, port=port, factory=True, reload=True, log_config=log_config)
        else:
            app = _create_app(host=args.tdx_host, port=args.tdx_port)
            uvicorn.run(app, host=host, port=port, log_config=log_config)
