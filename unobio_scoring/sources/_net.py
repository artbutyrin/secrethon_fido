"""HTTPS for the downloaders. Standard library only, but uses certifi's CA bundle when it is installed (it is a
dependency of httpx, so the backend always has it): python.org builds on macOS ship without system root
certificates, and plain urllib then fails with CERTIFICATE_VERIFY_FAILED."""
from __future__ import annotations

import ssl
import urllib.request


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def urlopen(url: str, timeout: float = 30):
    return urllib.request.urlopen(url, timeout=timeout, context=ssl_context())
