"""Run the Ledgerline API:  python -m ledgerline"""
from __future__ import annotations

import ipaddress
import os
import sys

import uvicorn

from . import watcher
from .api.app import create_app
from .config import load_settings


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> None:
    settings = load_settings()
    if not _is_loopback(settings.host) and not settings.cookie_secure:
        sys.exit("Refusing to bind a non-loopback host without LEDGERLINE_COOKIE_SECURE=1 behind HTTPS. See README > Deployment.")
    print(f"Ledgerline API on http://{settings.host}:{settings.port}  bank={settings.provider}  "
          f"claude={'api' if settings.claude_configured else 'offline-fixture'}  data={settings.data_dir}")
    app = create_app(settings)
    watcher.start(app, int(os.environ.get("LEDGERLINE_WATCH_SECONDS", "120")))
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower(),
                proxy_headers=False, access_log=False,
                # Longer than the proxy's idle time, so Caddy never reuses a connection uvicorn is closing (a POST is not retried).
                timeout_keep_alive=75)


if __name__ == "__main__":
    main()
