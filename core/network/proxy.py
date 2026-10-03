"""Local CONNECT proxy with a direct -> frag fallback.

For every CONNECT it reads the client's first TLS record and decides the
transport for that exact hostname: forward the ClientHello as-is (`direct`) or
split it into two TLS records (`frag`). It never decrypts TLS and never looks
at HTTP: after the first flight it is a byte relay.

Security: binds loopback, requires Basic auth with a per-run random credential,
refuses loopback/link-local/self targets, caps concurrent tunnels and logs only
hostnames/transports (never credentials, URLs or query strings).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import ipaddress
import logging
import secrets
import socket
from typing import Dict, List, Optional, Sequence, Tuple

from .errors import TransportError
from .frag import FRAG_STRATEGIES, fragment, has_full_first_record, is_tls_client_hello
from .relay import DEFAULT_BUFFER_SIZE, DEFAULT_IDLE_TIMEOUT, relay
from .routing import FRAG, Routing

logger = logging.getLogger(__name__)

# ---- tunables (single place, not scattered through the code) ----------------
DEFAULT_HOST = "127.0.0.1"
DEFAULT_T1 = 5.0                 # wait for the origin's first TLS byte
DEFAULT_CONNECT_TIMEOUT = 5.0    # TCP connect to the origin
DEFAULT_MAX_CONNECTIONS = 64
DEFAULT_REQUEST_TIMEOUT = 10.0   # read the CONNECT request / the ClientHello
MAX_HEADER_BYTES = 64 * 1024
MAX_HELLO_BYTES = 256 * 1024
# A first byte from the origin that is a TLS record: handshake or alert.
TLS_FIRST_BYTES = (0x16, 0x15)

Address = Tuple[int, tuple]


class SmartProxy:
    """A local HTTP CONNECT proxy doing per-hostname direct/frag selection."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        t1: float = DEFAULT_T1,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        strategies: Sequence[str] = FRAG_STRATEGIES,
        allow_local_targets: bool = False,
        routing: Optional[Routing] = None,
    ) -> None:
        self._host = host
        self._t1 = t1
        self._connect_timeout = connect_timeout
        self._idle_timeout = idle_timeout
        self._max_connections = max_connections
        self._request_timeout = request_timeout
        self._buffer_size = buffer_size
        self._strategies = tuple(strategies)
        # Test seam: the origin in the integration tests is a local server. The
        # proxy's own port is still refused even when this is True.
        self._allow_local_targets = allow_local_targets

        self._routing = routing if routing is not None else Routing()
        self._server: Optional[asyncio.AbstractServer] = None
        self._tasks: set = set()
        self._active = 0
        self._username = secrets.token_hex(8)
        self._password = secrets.token_hex(16)
        self.port = 0

    # ------------------------------------------------------------------ life
    async def start(self) -> "SmartProxy":
        self._server = await asyncio.start_server(self._handle, self._host, 0)
        self.port = self._server.sockets[0].getsockname()[1]
        logger.info("[Network] proxy listening on %s:%s", self._host, self.port)
        return self

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def __aenter__(self) -> "SmartProxy":
        return await self.start()

    async def __aexit__(self, *_exc) -> None:
        await self.stop()

    @property
    def proxy_url(self) -> str:
        return f"http://{self._username}:{self._password}@{self._host}:{self.port}"

    @property
    def routing(self) -> Routing:
        return self._routing

    # -------------------------------------------------------------- handler
    async def _handle(self, reader, writer) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        self._active += 1
        try:
            if self._active > self._max_connections:
                await self._respond(writer, "503 Service Unavailable", "Retry-After: 1")
                return
            await self._serve(reader, writer)
        except (asyncio.TimeoutError, ConnectionError, OSError):
            pass
        except Exception:  # noqa: BLE001 - a handler must never kill the loop
            logger.exception("[Network] proxy handler error")
        finally:
            self._active -= 1
            self._tasks.discard(task)
            await _close(writer)

    async def _serve(self, reader, writer) -> None:
        request = await self._read_request(reader)
        if request is None:
            await self._respond(writer, "400 Bad Request")
            return

        method, target, headers, leftover = request
        if method != "CONNECT":
            await self._respond(writer, "405 Method Not Allowed", "Allow: CONNECT")
            return
        if not self._check_auth(headers.get("proxy-authorization", "")):
            await self._respond(
                writer,
                "407 Proxy Authentication Required",
                'Proxy-Authenticate: Basic realm="VideoDownloadTool"',
            )
            return

        authority = _parse_authority(target)
        if authority is None:
            await self._respond(writer, "400 Bad Request")
            return
        host, port = authority

        addresses = [(f, sa) for f, sa in await self._resolve(host, port)
                     if not self._target_blocked(sa[0], port)]
        if not addresses:
            logger.info("[Network] CONNECT %s:%s refused (blocked target)", host, port)
            await self._respond(writer, "403 Forbidden")
            return

        await self._respond_established(writer)
        await self._tunnel(reader, writer, host, port, addresses, leftover)

    # ------------------------------------------------------------- CONNECT IO
    async def _read_request(self, reader):
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = await asyncio.wait_for(
                reader.read(4096), timeout=self._request_timeout
            )
            if not chunk:
                return None
            buf += chunk
            if len(buf) > MAX_HEADER_BYTES:
                return None

        head, _, leftover = buf.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        try:
            method, target, _version = lines[0].split()
        except ValueError:
            return None

        headers: Dict[str, str] = {}
        for line in lines[1:]:
            name, _, value = line.partition(b":")
            headers[name.strip().lower().decode("latin-1")] = (
                value.strip().decode("latin-1")
            )
        return method.decode("latin-1").upper(), target.decode("latin-1"), headers, leftover

    def _check_auth(self, header: str) -> bool:
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            decoded = base64.b64decode(token.strip(), validate=True).decode(
                "utf-8", "replace"
            )
        except (ValueError, binascii.Error):
            return False
        user, sep, password = decoded.partition(":")
        if not sep:
            return False
        return hmac.compare_digest(user, self._username) and hmac.compare_digest(
            password, self._password
        )

    def _target_blocked(self, ip: str, port: int) -> bool:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return True
        if address.is_unspecified or address.is_multicast:
            return True
        if address.is_loopback and port == self.port:
            return True  # never proxy to ourselves
        if self._allow_local_targets:
            return False
        return address.is_loopback or address.is_link_local or address.is_reserved

    async def _resolve(self, host: str, port: int) -> List[Address]:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            logger.info("[Network] DNS error for %s", host)
            return []
        addresses: List[Address] = []
        seen = set()
        for family, _type, _proto, _canon, sockaddr in infos:
            key = (family, sockaddr[0])
            if key in seen:
                continue
            seen.add(key)
            addresses.append((family, sockaddr))
        return addresses

    # ---------------------------------------------------------------- tunnel
    async def _tunnel(self, reader, writer, host, port, addresses, leftover) -> None:
        client_hello = await self._read_client_first(reader, leftover)

        if not is_tls_client_hello(client_hello):
            # Plain data through the tunnel: relay it verbatim, never fragment.
            origin = await self._connect(addresses)
            if origin is None:
                await self._respond(writer, "502 Bad Gateway")
                return
            o_reader, o_writer = origin
            o_writer.write(client_hello)
            try:
                await o_writer.drain()
            except OSError:
                await _close(o_writer)
                return
            await self._relay(reader, writer, o_reader, o_writer)
            return

        route = self._routing.get(host)
        if route is not None and route.transport == FRAG:
            logger.info("[Network] CONNECT %s:%s route=frag (learned) -> FRAG", host, port)
            learned, _error = await self._try_frag(
                addresses, client_hello, host, [route.strategy or self._strategies[0]]
            )
            if learned is not None:
                self._routing.touch(host)
                await self._run_tunnel(reader, writer, learned)
                return
            # The learned route stopped working: drop it and fall back once.
            logger.info("[Network] %s FRAG failed -> forget route, trying DIRECT once", host)
            self._routing.forget(host)
            direct, _error = await self._try_direct(addresses, client_hello)
            if direct is not None:
                await self._run_tunnel(reader, writer, direct)
                return
            await self._respond(writer, "502 Bad Gateway")
            return

        logger.info("[Network] CONNECT %s:%s route=unknown -> DIRECT", host, port)
        direct, error = await self._try_direct(addresses, client_hello)
        if direct is not None:
            await self._run_tunnel(reader, writer, direct)
            return

        reason = (error or TransportError.FIRST_BYTE_TIMEOUT).value
        logger.info("[Network] %s DIRECT %s -> trying FRAG", host, reason)
        learned, _error = await self._try_frag(
            addresses, client_hello, host, list(self._strategies)
        )
        if learned is None:
            logger.info("[Network] %s all transports failed -> 502", host)
            await self._respond(writer, "502 Bad Gateway")
            return

        o_reader, o_writer, first, strategy = learned
        self._routing.remember(host, FRAG, strategy, reason)
        logger.info("[Network] Learned route: %s -> frag/%s (%s)", host, strategy, reason)
        await self._finish(reader, writer, o_reader, o_writer, first)

    async def _read_client_first(self, reader, initial: bytes) -> bytes:
        buf = initial
        while True:
            if has_full_first_record(buf):
                return buf
            if len(buf) >= 3 and not is_tls_client_hello(buf):
                return buf  # not TLS: forward as-is
            chunk = await asyncio.wait_for(
                reader.read(MAX_HELLO_BYTES), timeout=self._request_timeout
            )
            if not chunk:
                return buf
            buf += chunk
            if len(buf) > MAX_HELLO_BYTES:
                return buf

    async def _run_tunnel(self, reader, writer, origin) -> None:
        o_reader, o_writer, first, _strategy = origin
        await self._finish(reader, writer, o_reader, o_writer, first)

    async def _finish(self, reader, writer, o_reader, o_writer, first: bytes) -> None:
        writer.write(first)
        await writer.drain()
        await self._relay(reader, writer, o_reader, o_writer)

    async def _relay(self, reader, writer, o_reader, o_writer) -> None:
        try:
            await relay(
                reader, writer, o_reader, o_writer, idle_timeout=self._idle_timeout
            )
        except (asyncio.TimeoutError, ConnectionError, OSError):
            # After the handshake everything is data: a broken tunnel is not a
            # reason to escalate the hostname.
            pass

    # --------------------------------------------------------------- attempts
    async def _try_direct(self, addresses, client_hello):
        """Returns ((reader, writer, first, None), error) — one of the two set."""
        origin = await self._connect(addresses)
        if origin is None:
            return None, TransportError.CONNECT_TIMEOUT
        o_reader, o_writer = origin
        try:
            o_writer.write(client_hello)
            await o_writer.drain()
        except OSError:
            await _close(o_writer)
            return None, TransportError.CONNECTION_RESET
        reply, error = await self._await_server_reply(o_reader, o_writer)
        if reply is None:
            return None, error
        reader, writer, first = reply
        return (reader, writer, first, None), None

    async def _try_frag(self, addresses, client_hello, host, strategies):
        last_error = None
        for strategy in strategies:
            origin = await self._connect(addresses)
            if origin is None:
                last_error = TransportError.CONNECT_TIMEOUT
                continue
            o_reader, o_writer = origin
            try:
                for piece in fragment(client_hello, strategy, host):
                    o_writer.write(piece)
                await o_writer.drain()
            except OSError:
                await _close(o_writer)
                last_error = TransportError.CONNECTION_RESET
                continue
            reply, error = await self._await_server_reply(o_reader, o_writer)
            if reply is not None:
                reader, writer, first = reply
                return (reader, writer, first, strategy), None
            last_error = error
        return None, last_error

    async def _await_server_reply(self, reader, writer):
        """First byte from the origin; (reply, None) or (None, TransportError)."""
        try:
            data = await asyncio.wait_for(reader.read(1), timeout=self._t1)
        except asyncio.TimeoutError:
            logger.info("[Network] first_byte_timeout (%.1fs)", self._t1)
            await _close(writer)
            return None, TransportError.FIRST_BYTE_TIMEOUT
        except (ConnectionResetError, ConnectionAbortedError):
            await _close(writer)
            return None, TransportError.CONNECTION_RESET
        except OSError:
            await _close(writer)
            return None, TransportError.NETWORK_UNREACHABLE
        if not data:
            logger.info("[Network] early_eof")
            await _close(writer)
            return None, TransportError.EARLY_EOF
        if data[0] not in TLS_FIRST_BYTES:
            logger.info("[Network] non_tls_reply (possible block page)")
            await _close(writer)
            return None, TransportError.NON_TLS_REPLY
        return (reader, writer, data), None

    async def _connect(self, addresses):
        loop = asyncio.get_running_loop()
        for family, sockaddr in addresses:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setblocking(False)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            try:
                await asyncio.wait_for(
                    loop.sock_connect(sock, sockaddr), timeout=self._connect_timeout
                )
            except asyncio.TimeoutError:
                sock.close()
                continue
            except OSError:
                sock.close()
                continue
            try:
                return await asyncio.open_connection(sock=sock)
            except OSError:
                sock.close()
                continue
        return None

    # -------------------------------------------------------------- response
    async def _respond_established(self, writer) -> None:
        # A CONNECT success has no body/connection headers: the tunnel stays open.
        try:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        except OSError:
            pass

    async def _respond(self, writer, status: str, extra: str = "") -> None:
        head = f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n"
        if extra:
            head += extra + "\r\n"
        head += "\r\n"
        try:
            writer.write(head.encode("latin-1"))
            await writer.drain()
        except OSError:
            pass


def _parse_authority(target: str):
    """Parse "host:port" (with [ipv6] support) into (host, port)."""
    if target.startswith("["):
        end = target.find("]")
        if end < 0:
            return None
        host = target[1:end]
        rest = target[end + 1:]
        if not rest.startswith(":"):
            return None
        port_text = rest[1:]
    else:
        host, sep, port_text = target.rpartition(":")
        if not sep:
            return None
    if not host or not port_text.isdigit():
        return None
    port = int(port_text)
    if not 1 <= port <= 65535:
        return None
    return host, port


async def _close(writer) -> None:
    try:
        writer.close()
    except Exception:  # noqa: BLE001 - best effort
        pass
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 - best effort
        pass
