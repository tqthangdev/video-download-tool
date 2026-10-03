"""Owns the SmartProxy: runs it in a dedicated thread + event loop.

The GUI (qasync loop) must never be blocked by the proxy, so the proxy lives
in its own thread with its own asyncio loop. The manager exposes the proxy URL
for yt-dlp/ffmpeg and a small facade over the route table for the UI.

Only the standard library is used here.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Optional

from .proxy import SmartProxy
from .routing import DEFAULT_TTL_DAYS, Routing

logger = logging.getLogger(__name__)

START_TIMEOUT = 8.0
STOP_TIMEOUT = 10.0


class NetworkManager:
    """Start/stop the local proxy and talk to its route table."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        routing_path: Optional[Path] = None,
        ttl_days: int = DEFAULT_TTL_DAYS,
        **proxy_options,
    ) -> None:
        self._enabled = bool(enabled)
        self._routing = Routing(routing_path, ttl_days=ttl_days)
        self._proxy_options = proxy_options
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._proxy: Optional[SmartProxy] = None
        self._proxy_url: Optional[str] = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ state
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        return self._proxy_url is not None

    @property
    def proxy_url(self) -> Optional[str]:
        return self._proxy_url

    @property
    def routing(self) -> Routing:
        return self._routing

    # ------------------------------------------------------------------ life
    def start(self, timeout: float = START_TIMEOUT) -> bool:
        """Start the proxy (no-op when disabled or already running)."""
        if not self._enabled or self.running:
            return False
        self._ready.clear()
        with self._lock:
            self._thread = threading.Thread(
                target=self._run, name="network-proxy", daemon=True
            )
            self._thread.start()
        if not self._ready.wait(timeout):
            logger.error("[Network] proxy did not become ready in %.0fs", timeout)
            return False
        return self.running

    def stop(self) -> None:
        loop, proxy, thread = self._loop, self._proxy, self._thread
        if loop is not None and proxy is not None:
            try:
                asyncio.run_coroutine_threadsafe(proxy.stop(), loop).result(
                    timeout=STOP_TIMEOUT
                )
            except Exception:  # noqa: BLE001 - shutdown is best effort
                logger.warning("[Network] stopping the proxy failed", exc_info=True)
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=STOP_TIMEOUT)
        self._loop = None
        self._thread = None
        self._proxy = None
        self._proxy_url = None

    def set_enabled(self, enabled: bool) -> bool:
        """Turn the fallback on/off at runtime; returns whether it is running."""
        self._enabled = bool(enabled)
        if self._enabled:
            self.start()
        else:
            self.stop()
        return self.running

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            proxy = SmartProxy(routing=self._routing, **self._proxy_options)
            loop.run_until_complete(proxy.start())
            self._proxy = proxy
            self._proxy_url = proxy.proxy_url
            logger.info("[Network] proxy ready at %s", proxy.proxy_url)
            self._ready.set()
            loop.run_forever()
        except Exception:  # noqa: BLE001 - never kill the app because of the proxy
            logger.exception("[Network] proxy thread failed")
            self._ready.set()
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001 - best effort
                pass
            loop.close()
            self._proxy = None
            self._proxy_url = None

    # ------------------------------------------------- routing facade for UI
    def learned_hosts(self):
        """Snapshot of the known hostnames (host -> Route)."""
        return self._routing.snapshot()

    def forget(self, hostname: str) -> None:
        self._routing.forget(hostname)

    def clear_learned(self) -> None:
        self._routing.clear_all()
