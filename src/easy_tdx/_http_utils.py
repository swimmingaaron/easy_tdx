"""HTTP 网络请求跨平台公共工具模块。

解决 macOS（如 Apple Silicon M1/M2/M3/M4）等平台上 Python 未安装/未配置 CA 根证书时，
调用 urllib.request.urlopen 访问 https 接口抛出 SSL: CERTIFICATE_VERIFY_FAILED 的问题。
"""

from __future__ import annotations

import ssl
import urllib.request
from typing import Any

_CACHED_SSL_CONTEXT: ssl.SSLContext | None = None


def get_ssl_context() -> ssl.SSLContext:
    """获取兼容所有平台的 SSL 上下文。

    策略：
    1. 优先尝试使用 certifi 库的 Mozilla CA Bundle；
    2. 其次尝试标准库系统默认证书；
    3. 若系统缺少证书（macOS 常见默认未安装证书环境），回退到 unverified 上下文，
       确保拉取公开股票财务等数据时不发生握手崩溃。
    """
    global _CACHED_SSL_CONTEXT
    if _CACHED_SSL_CONTEXT is not None:
        return _CACHED_SSL_CONTEXT

    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass

    if ctx is None:
        try:
            ctx = ssl.create_default_context()
        except Exception:
            pass

    if ctx is None and hasattr(ssl, "_create_unverified_context"):
        try:
            # 在 macOS 上保证绝不因证书缺失报错
            unverified = ssl._create_unverified_context()
            _CACHED_SSL_CONTEXT = unverified
            return unverified
        except Exception:
            pass

    if ctx is None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    _CACHED_SSL_CONTEXT = ctx
    return ctx


def urlopen_safe(req: urllib.request.Request | str, timeout: float = 10.0, **kwargs: Any) -> Any:
    """带有自适应跨平台 SSL 证书兼容的 urlopen 包装器。"""
    ctx = kwargs.pop("context", None) or get_ssl_context()
    if isinstance(req, urllib.request.Request):
        if not req.has_header("Connection"):
            req.add_unredirected_header("Connection", "close")
        if not req.has_header("User-agent"):
            req.add_unredirected_header(
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
    return urllib.request.urlopen(req, timeout=timeout, context=ctx, **kwargs)
