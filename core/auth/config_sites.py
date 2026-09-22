"""
core/auth/config_sites.py

Allows declaring login-required sites via JSON (see sites_config.json)
instead of creating a separate .py file per site. AuthManager.auto_register()
calls load_config_sites() to register these handlers.

If a site needs special login logic (captcha, multi-step, refresh token...)
you can still create a .py file under core/auth/sites/ as before — a .py handler
is registered afterwards and overrides the config handler (same site_id).
"""

from __future__ import annotations

import json
import urllib3
from pathlib import Path
from typing import Optional

import requests

from core.i18n import tr
from .base import AuthHandler, AuthResult, AuthError

# JSON file sits next to this module, committed with the source (not inside data/).
CONFIG_PATH = Path(__file__).with_name("sites_config.json")

# Suppress SSL warnings for sites with verify_ssl=false.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Common CSRF token selectors.
CSRF_SELECTORS = (
    'input[name="_token"]',
    'input[name="_csrf"]',
    'input[name="csrf_token"]',
    'input[name="csrf-token"]',
    'meta[name="csrf-token"]',
)


def load_sites_config() -> dict:
    """Read the contents of sites_config.json. Returns {} if missing/corrupt."""
    from core.logger import logger

    if not CONFIG_PATH.exists():
        logger.warning(
            f"[auth] {CONFIG_PATH.name} not found — no config-driven sites "
            "registered. Add it next to this module to enable login for sites "
            "that require authentication."
        )
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"[auth] Failed to read {CONFIG_PATH.name}: {e}")
        return {}
    # Skip keys starting with "_" (like "_comment").
    return {k: v for k, v in data.items() if isinstance(v, dict) and not k.startswith("_")}


class ConfigSiteAuth(AuthHandler):
    """
    Shared AuthHandler for a site declared in sites_config.json.

    Supports 3 login types:
      - form : POST application/x-www-form-urlencoded to login_url
               (with CSRF token if csrf=true), cookie session.
      - json : POST JSON to login_url, read a token from the response and attach
               it to a header (Authorization by default).
      - basic: HTTP Basic Auth (requests auth=(username, password)).
    """

    def __init__(self, site_id: str, cfg: dict):
        super().__init__()
        self.site_id = site_id
        self.cfg = cfg

        domains = cfg.get("domains") or []
        self.domains = tuple(domains) if isinstance(domains, list) else (domains,)

        self.login_url = cfg.get("login_url", "")
        self.check_url = cfg.get("check_url", "")
        self.username_field = cfg.get("username_field", "username")
        self.password_field = cfg.get("password_field", "password")
        self.extra_form = cfg.get("extra_form") or {}
        self.csrf = bool(cfg.get("csrf", False))
        self.verify_ssl = bool(cfg.get("verify_ssl", True))
        self.auth_type = (cfg.get("type") or "form").lower()

        # For type=json: the field name holding the token in the response, and the
        # header used to attach the token.
        self.token_path = cfg.get("token_path") or "access_token"
        self.token_header = cfg.get("token_header") or "Authorization"
        self.token_prefix = cfg.get("token_prefix") or "Bearer "

        # type=json alternative for sites that need SEVERAL auth headers taken
        # from the login response, e.g. {"m4u_token": "auth_token",
        # "m4u_uid": "data.id"} (value = dotted path into the JSON response).
        self.token_headers = {
            str(k): str(v) for k, v in (cfg.get("token_headers") or {}).items()
        }
        # Static headers applied to every request of the session (e.g. a client
        # identifier the site requires: {"cuutruyen-client": "OfficialWebApp-..."}).
        self.extra_headers = {
            str(k): str(v) for k, v in (cfg.get("extra_headers") or {}).items()
        }

        # Headers that carry auth/identity, so AuthManager.get_headers() can
        # replay the session in aiohttp/Playwright.
        names = list(self.token_headers) + list(self.extra_headers)
        if self.auth_type == "json" and not self.token_headers:
            names.append(self.token_header)
        self.auth_header_names = tuple(dict.fromkeys(names))

        # The status returned by check_url that counts as logged in.
        self.check_ok_status = cfg.get("check_ok_status", 200)

        if not self.login_url:
            raise ValueError(
                f"ConfigSiteAuth('{site_id}') {tr('auth_missing_login_url')}"
            )

    def build_session(self) -> requests.Session:
        session = super().build_session()
        # Apply verify to every request of this session.
        session.verify = self.verify_ssl
        if self.extra_headers:
            session.headers.update(self.extra_headers)
        return session

    # ---- login ----------------------------------------------------------

    def login(self, username: str, password: str) -> AuthResult:
        if self.auth_type == "basic":
            return self._login_basic(username, password)

        if self.auth_type == "json":
            return self._login_json(username, password)

        return self._login_form(username, password)

    def _login_form(self, username: str, password: str) -> AuthResult:
        session = self.build_session()

        payload = {
            self.username_field: username,
            self.password_field: password,
        }
        # Allow the config to declare extra static fields, or fields reusing the
        # username via extra_form, e.g. {"email": "{username}"} -> {username} replaced.
        for k, v in self.extra_form.items():
            payload[k] = v.replace("{username}", username) if isinstance(v, str) else v

        # GET the login page to fetch the CSRF token if needed.
        if self.csrf:
            try:
                page = session.get(self.login_url, timeout=15)
                page.raise_for_status()
                token = self._extract_csrf(page.text)
                if token:
                    payload["_token"] = token
            except requests.RequestException:
                # Still try POST without a token; many sites allow it.
                pass

        resp = session.post(
            self.login_url,
            data=payload,
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()

        if not self.is_logged_in(session):
            raise AuthError(
                tr("auth_login_failed_user").format(
                    self.site_id, username
                )
                + f" (HTTP {resp.status_code})"
            )

        return AuthResult(
            session=session,
            site_id=self.site_id,
            username=username,
        )

    def _login_json(self, username: str, password: str) -> AuthResult:
        session = self.build_session()

        payload = {
            self.username_field: username,
            self.password_field: password,
        }
        for k, v in self.extra_form.items():
            payload[k] = v.replace("{username}", username) if isinstance(v, str) else v

        resp = session.post(self.login_url, json=payload, timeout=15)
        if not (200 <= resp.status_code < 300):
            raise AuthError(
                tr("auth_login_failed_status").format(self.site_id, resp.status_code)
            )

        data = resp.json()

        # Multi-header login (e.g. cuutruyen sends both m4u_token and m4u_uid).
        if self.token_headers:
            headers = {}
            for header_name, path in self.token_headers.items():
                value = self._get_path(data, path)
                if value is None:
                    raise AuthError(tr("auth_login_no_token").format(self.site_id))
                headers[header_name] = str(value)
            session.headers.update(headers)
            return AuthResult(
                session=session,
                site_id=self.site_id,
                username=username,
                extra={"headers": headers},
            )

        token = self._get_token(data)
        if not token:
            raise AuthError(tr("auth_login_no_token").format(self.site_id))

        header_val = f"{self.token_prefix}{token}" if self.token_prefix else token
        session.headers[self.token_header] = header_val

        return AuthResult(
            session=session,
            site_id=self.site_id,
            username=username,
            extra={"token": token},
        )

    def _login_basic(self, username: str, password: str) -> AuthResult:
        session = self.build_session()
        session.auth = (username, password)

        if not self.is_logged_in(session):
            raise AuthError(
                tr("auth_login_failed_user").format(self.site_id, username)
            )

        return AuthResult(
            session=session,
            site_id=self.site_id,
            username=username,
        )

    # ---- session check --------------------------------------------------

    def is_logged_in(self, session: requests.Session) -> bool:
        if not self.check_url:
            # Without check_url, treat the presence of cookies as logged in.
            return bool(session.cookies)

        try:
            resp = session.get(
                self.check_url,
                timeout=10,
                allow_redirects=False,
            )
        except requests.RequestException:
            return False

        return resp.status_code == self.check_ok_status

    # ---- helpers --------------------------------------------------------

    def _get_path(self, data, path: str):
        """Read a (possibly dotted) value from the login response: a.b.c."""
        cur = data
        for part in str(path).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def _get_token(self, data) -> Optional[str]:
        """Get a token by token_path (supports dotted path: a.b.c)."""
        value = self._get_path(data, self.token_path)
        return value if isinstance(value, str) else None

    @staticmethod
    def _extract_csrf(html: str) -> Optional[str]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        for selector in CSRF_SELECTORS:
            node = soup.select_one(selector)
            if node:
                token = node.get("value") or node.get("content")
                if token:
                    return token

        return None


def build_config_sites() -> list[ConfigSiteAuth]:
    """Create a handler for every site declared in sites_config.json."""
    handlers = []
    for site_id, cfg in load_sites_config().items():
        try:
            handlers.append(ConfigSiteAuth(site_id, cfg))
        except Exception as e:
            from core.logger import logger

            logger.error(tr("auth_config_error").format(site_id, e))
    return handlers