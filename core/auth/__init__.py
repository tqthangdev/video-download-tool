"""
core/auth/__init__.py

Import this module to get an auth_manager that has automatically registered
all AuthHandlers from core/auth/sites_config.json.
"""

from .base import AuthError, SessionExpiredError, AuthResult, AuthHandler
from .manager import auth_manager

auth_manager.auto_register()

__all__ = [
    "auth_manager",
    "AuthHandler",
    "AuthResult",
    "AuthError",
    "SessionExpiredError",
]