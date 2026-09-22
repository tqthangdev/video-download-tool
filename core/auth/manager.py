from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Dict, Optional, Type

import requests

from .base import AuthHandler, AuthError, AuthResult
from .config_sites import build_config_sites
from .session_store import SessionStore

logger = logging.getLogger(__name__)


class AuthManager:
    def __init__(self, store: Optional[SessionStore] = None):
        self._store = store or SessionStore()
        self._handlers: Dict[str, AuthHandler] = {}
        self._sessions: Dict[str, requests.Session] = {}

    # ---- Site registration ------------------------------------------------

    def register(self, handler: AuthHandler) -> None:
        """Register an AuthHandler for its corresponding site_id."""
        if not handler.site_id:
            raise ValueError("AuthHandler must define site_id")

        self._handlers[handler.site_id] = handler
        logger.debug("Registered auth handler for site '%s'", handler.site_id)

    def register_class(self, handler_cls: Type[AuthHandler]) -> None:
        """Convenience: register using a class instead of an instance."""
        self.register(handler_cls())

    def auto_register(self) -> None:
        """
        Register AuthHandlers from core/auth/sites_config.json (config-driven,
        no code required). Handlers are created per site declared in the file.
        """
        for handler in build_config_sites():
            self.register(handler)

    def list_sites(self) -> list[str]:
        return list(self._handlers.keys())

    def _handler_for(self, site_id: str) -> AuthHandler:
        handler = self._handlers.get(site_id)
        if handler is None:
            raise KeyError(
                f"No auth handler registered for site '{site_id}'. "
                f"Registered sites: {self.list_sites()}"
            )
        return handler

    # ---- Login / Session ---------------------------------------------------

    def login(
        self,
        site_id: str,
        username: str,
        password: str,
        remember: bool = True,
    ) -> requests.Session:
        """Log into a site, cache the session in RAM, and persist to disk if remember=True."""
        handler = self._handler_for(site_id)
        result: AuthResult = handler.login(username, password)

        self._sessions[site_id] = result.session

        if remember:
            self._store.save(
                site_id,
                result.session,
                username=result.username or username,
            )

        logger.info("Logged in successfully to site '%s'", site_id)
        return result.session

    def get_session(
        self,
        site_id: str,
        auto_restore: bool = True,
    ) -> requests.Session:
        """
        Get the current session for site_id.

        Priority: RAM cache -> restore from disk -> empty session.
        """
        if site_id in self._sessions:
            return self._sessions[site_id]

        handler = self._handler_for(site_id)
        session = handler.build_session()

        if auto_restore:
            restored = self._store.restore_session(
                site_id,
                session,
                header_names=getattr(handler, "auth_header_names", ()) or (),
            )

            if restored is not None and handler.is_logged_in(restored):
                self._sessions[site_id] = restored

                logger.debug(
                    "Restored saved session for site '%s'",
                    site_id,
                )

                return restored

        self._sessions[site_id] = session
        return session

    def is_logged_in(self, site_id: str) -> bool:
        handler = self._handler_for(site_id)
        session = self.get_session(site_id)
        return handler.is_logged_in(session)

    def ensure_logged_in(self, site_id: str) -> requests.Session:
        """Return a valid session, or raise AuthError if not/login expired."""
        session = self.get_session(site_id)
        handler = self._handler_for(site_id)

        if not handler.is_logged_in(session):
            raise AuthError(
                f"Not logged in or session expired for site '{site_id}'. "
                f"Call auth_manager.login('{site_id}', username, password) first."
            )

        return session

    # ---- Expose cookies/headers to other clients ---------------------------

    def get_cookies(self, site_id: str) -> dict:
        """Return the current session's cookies as {name: value}."""
        session = self.get_session(site_id)
        return requests.utils.dict_from_cookiejar(session.cookies)

    def get_headers(self, site_id: str) -> dict:
        """Return the session's auth headers so other clients can replay them."""
        handler = self._handler_for(site_id)
        session = self.get_session(site_id)

        keys = {"Authorization", "X-Auth-Token", "X-API-Key"}
        keys.update(getattr(handler, "auth_header_names", ()) or ())

        return {
            k: session.headers[k]
            for k in keys
            if k in session.headers
        }

    def site_id_for_url(self, url: str) -> Optional[str]:
        """Auto-detect which registered site a URL belongs to based on domains."""
        from urllib.parse import urlparse

        netloc = urlparse(url).netloc.lower()

        for site_id, handler in self._handlers.items():
            for domain in getattr(handler, "domains", ()):
                domain = domain.lower()

                if netloc == domain or netloc.endswith("." + domain):
                    return site_id

        return None

    def logout(self, site_id: str) -> None:
        """Remove the session from RAM and disk."""
        self._sessions.pop(site_id, None)
        self._store.delete(site_id)

        logger.info("Logged out of site '%s'", site_id)


auth_manager = AuthManager()