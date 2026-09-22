"""
core/auth/session_store.py

Saves/loads a session's cookies to data/sessions/<site_id>.json so the
app does not require re-login on the next launch.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional
import requests

# data/ sits next to the app, sessions/ inside data/
SESSIONS_DIR = Path(__file__).resolve().parents[2] / "data" / "sessions"


class SessionStore:
    def __init__(self, base_dir: Path = SESSIONS_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, site_id: str) -> Path:
        return self.base_dir / f"{site_id}.json"

    def save(self, site_id: str, session: requests.Session, username: Optional[str] = None) -> None:
        """Save a session's cookie jar to a JSON file."""
        data = {
            "site_id": site_id,
            "username": username,
            "saved_at": time.time(),
            "cookies": requests.utils.dict_from_cookiejar(session.cookies),
            "headers": dict(session.headers),
        }
        path = self._path_for(site_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, site_id: str) -> Optional[dict]:
        """Read stored session data. Returns None if never saved."""
        path = self._path_for(site_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def restore_session(
        self,
        site_id: str,
        base_session: requests.Session,
        header_names: tuple = (),
    ) -> Optional[requests.Session]:
        """
        Restore saved cookies (and the given auth headers, needed by sites whose
        session lives in a token header rather than a cookie) into a fresh
        session. Returns None if no data.
        """
        data = self.load(site_id)
        if not data:
            return None
        cookies = requests.utils.cookiejar_from_dict(data.get("cookies", {}))
        base_session.cookies.update(cookies)
        saved_headers = data.get("headers", {})
        for name in header_names or ():
            value = saved_headers.get(name)
            if value:
                base_session.headers[name] = value
        return base_session

    def delete(self, site_id: str) -> None:
        """Delete a stored session (used on logout)."""
        path = self._path_for(site_id)
        if path.exists():
            path.unlink()