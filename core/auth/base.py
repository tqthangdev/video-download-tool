"""
core/auth/base.py

Defines the common interface every site auth handler must implement.
Each site (site_a.py, site_b.py, ...) inherits AuthHandler and overrides
the methods it needs according to that site's own login flow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import requests


class AuthError(Exception):
    """Generic error when login fails (wrong user/pass, captcha, blocked...)."""


class SessionExpiredError(AuthError):
    """Session/cookie has expired and needs a fresh login."""


@dataclass
class AuthResult:
    """Result returned after a successful login."""
    session: requests.Session
    site_id: str
    username: Optional[str] = None
    extra: dict = field(default_factory=dict)  # token, expire_at, etc if needed


class AuthHandler(ABC):
    """
    Common interface for logging into a specific manga site.

    Each site subclass must define:
        - site_id: unique id (used as the session storage key, e.g. "site_a")
        - login(): perform the login, return an AuthResult
        - is_logged_in(): check whether the current session is still valid

    It may override as well:
        - refresh(): renew the session if the site supports a refresh token
        - build_session(): customize the default session (headers, proxy...)
    """

    site_id: str = ""
    # Domain(s) this handler covers, e.g. ("site-a.example.com",).
    # Used by AuthManager.site_id_for_url() to auto-detect which site a
    # pasted URL belongs to, without the GUI needing a manual site picker.
    domains: tuple[str, ...] = ()
    # Names of the request headers that carry the session's auth (set by the
    # handler). AuthManager.get_headers() forwards exactly these to aiohttp /
    # Playwright so a logged-in session is replayed by other clients.
    auth_header_names: tuple[str, ...] = ()

    def build_session(self) -> requests.Session:
        """Create a default session. Override for special headers/proxy."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        })
        return session

    @abstractmethod
    def login(self, username: str, password: str) -> AuthResult:
        """Perform the login. Raise AuthError on failure."""
        raise NotImplementedError

    @abstractmethod
    def is_logged_in(self, session: requests.Session) -> bool:
        """Check whether the current session is still logged in."""
        raise NotImplementedError

    def refresh(self, session: requests.Session) -> requests.Session:
        """
        Renew a session (e.g. refresh token, ping the home page to renew a cookie).
        Default: do nothing and return the original session unchanged.
        Override if the site supports refreshing without re-entering user/pass.
        """
        return session