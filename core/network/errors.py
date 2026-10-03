"""Transport error taxonomy for the network fallback.

These are the failures that happen *before* a valid ServerHello is received;
only they justify escalating a hostname from `direct` to `frag`.
"""

from __future__ import annotations

from enum import Enum


class TransportError(str, Enum):
    """Why reaching the origin failed at the transport/TLS-handshake stage."""

    FIRST_BYTE_TIMEOUT = "first_byte_timeout"   # the symptom seen on filtered hosts
    CONNECT_TIMEOUT = "connect_timeout"
    CONNECTION_RESET = "connection_reset"
    CONNECTION_REFUSED = "connection_refused"
    EARLY_EOF = "early_eof"
    DNS_ERROR = "dns_error"
    NETWORK_UNREACHABLE = "network_unreachable"
    NON_TLS_REPLY = "non_tls_reply"             # origin/middlebox replied in plaintext


class TransportFailure(Exception):
    """A transport failure, carrying the matching `TransportError`."""

    def __init__(self, error: TransportError, detail: str = ""):
        self.error = error
        self.detail = detail
        super().__init__(detail or error.value)
