"""Per-hostname transport choices, persisted across runs.

A hostname that needed `frag` is remembered with a TTL (default 7 days) in
`data/network.json`. `direct` is the default and is never stored; a learned
route is only kept while it keeps working.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, ItemsView, Optional

logger = logging.getLogger(__name__)

DIRECT = "direct"
FRAG = "frag"

DEFAULT_TTL_DAYS = 7
FILE_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _key(hostname: str) -> str:
    return hostname.strip().lower().rstrip(".")


@dataclass(frozen=True)
class Route:
    transport: str
    strategy: Optional[str] = None
    reason: str = ""
    learned_at: str = ""
    last_success: str = ""
    expires_at: str = ""

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        expiry = _parse_time(self.expires_at)
        if expiry is None:
            return False
        return (now or _now()) >= expiry


class Routing:
    """hostname -> Route, backed by a JSON file when a path is given.

    A missing hostname means `direct`. Thread-safe: the proxy learns routes in
    its own thread while the UI may read or clear them.
    """

    def __init__(
        self, path: Optional[Path] = None, ttl_days: int = DEFAULT_TTL_DAYS
    ) -> None:
        self._path = Path(path) if path else None
        self._ttl = timedelta(days=max(1, int(ttl_days)))
        self._lock = threading.RLock()
        self._routes: Dict[str, Route] = {}
        self._load()

    # ------------------------------------------------------------------ read
    def get(self, hostname: str) -> Optional[Route]:
        key = _key(hostname)
        with self._lock:
            route = self._routes.get(key)
            if route is not None and route.is_expired():
                self._routes.pop(key, None)
                self._save_locked()
                return None
            return route

    def items(self) -> ItemsView[str, Route]:
        with self._lock:
            self._drop_expired_locked()
            return dict(self._routes).items()

    def snapshot(self) -> Dict[str, Route]:
        with self._lock:
            self._drop_expired_locked()
            return dict(self._routes)

    # ----------------------------------------------------------------- write
    def remember(
        self,
        hostname: str,
        transport: str,
        strategy: Optional[str] = None,
        reason: str = "",
    ) -> Route:
        now = _now()
        stamp = now.isoformat()
        route = Route(
            transport=transport,
            strategy=strategy,
            reason=reason,
            learned_at=stamp,
            last_success=stamp,
            expires_at=(now + self._ttl).isoformat(),
        )
        with self._lock:
            self._routes[_key(hostname)] = route
            self._save_locked()
        return route

    def touch(self, hostname: str) -> None:
        """Refresh a route that just worked again, extending its TTL."""
        key = _key(hostname)
        with self._lock:
            route = self._routes.get(key)
            if route is None:
                return
            now = _now()
            self._routes[key] = Route(
                transport=route.transport,
                strategy=route.strategy,
                reason=route.reason,
                learned_at=route.learned_at,
                last_success=now.isoformat(),
                expires_at=(now + self._ttl).isoformat(),
            )
            self._save_locked()

    def forget(self, hostname: str) -> None:
        with self._lock:
            if self._routes.pop(_key(hostname), None) is not None:
                self._save_locked()

    def clear_all(self) -> None:
        with self._lock:
            self._routes.clear()
            self._save_locked()

    # ------------------------------------------------------------ persistence
    def _drop_expired_locked(self) -> None:
        now = _now()
        gone = [k for k, r in self._routes.items() if r.is_expired(now)]
        if gone:
            for k in gone:
                self._routes.pop(k, None)
            self._save_locked()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("[Network] ignoring unreadable %s: %s", self._path, exc)
            return

        hosts = data.get("hosts") if isinstance(data, dict) else None
        if not isinstance(hosts, dict):
            return
        for host, raw in hosts.items():
            route = self._route_from_dict(raw)
            if route is not None:
                self._routes[_key(host)] = route

    @staticmethod
    def _route_from_dict(raw) -> Optional[Route]:
        if not isinstance(raw, dict):
            return None
        transport = raw.get("transport")
        if transport not in (DIRECT, FRAG):
            return None
        return Route(
            transport=transport,
            strategy=raw.get("strategy") or None,
            reason=str(raw.get("reason") or ""),
            learned_at=str(raw.get("learned_at") or ""),
            last_success=str(raw.get("last_success") or ""),
            expires_at=str(raw.get("expires_at") or ""),
        )

    def _save_locked(self) -> None:
        if self._path is None:
            return
        payload = {
            "version": FILE_VERSION,
            "hosts": {
                host: {
                    "transport": route.transport,
                    "strategy": route.strategy,
                    "reason": route.reason,
                    "learned_at": route.learned_at,
                    "last_success": route.last_success,
                    "expires_at": route.expires_at,
                }
                for host, route in self._routes.items()
            },
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, indent=4, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("[Network] could not write %s: %s", self._path, exc)
