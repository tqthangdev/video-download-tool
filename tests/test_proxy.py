"""Integration tests for the Stage 1 proxy (local origins, no external network)."""

from __future__ import annotations

import asyncio
import base64
import socket
import ssl
import time
import tracemalloc
from urllib.parse import urlsplit

from core.network.frag import handshake_spans_records, has_full_first_record
from core.network.proxy import SmartProxy


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def basic(user_password: str) -> str:
    return base64.b64encode(user_password.encode()).decode()


def credentials(proxy: SmartProxy) -> str:
    parts = urlsplit(proxy.proxy_url)
    return f"{parts.username}:{parts.password}"


def http_connect(proxy_port: int, auth, target: str, timeout: float = 10.0):
    """Open a CONNECT tunnel; return (socket, status_line)."""
    sock = socket.create_connection(("127.0.0.1", proxy_port), timeout=timeout)
    request = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
    if auth:
        request += f"Proxy-Authorization: Basic {auth}\r\n"
    request += "\r\n"
    sock.sendall(request.encode())

    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return sock, data.split(b"\r\n", 1)[0].decode("latin-1")


def recv_all(sock: socket.socket) -> bytes:
    buf = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return buf
        buf += chunk


def client_hello_bytes(server_hostname: str = "example.com") -> bytes:
    """A real TLS ClientHello produced by this interpreter's OpenSSL."""
    ctx = ssl.create_default_context()
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    obj = ctx.wrap_bio(incoming, outgoing, server_hostname=server_hostname)
    try:
        obj.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return outgoing.read()


def start_proxy(loop_runner, **kwargs) -> SmartProxy:
    kwargs.setdefault("idle_timeout", 60.0)
    proxy = SmartProxy(**kwargs)
    loop_runner.run(proxy.start())
    return proxy


def start_origin(loop_runner, handler, ssl_context=None):
    async def _start():
        return await asyncio.start_server(handler, "127.0.0.1", 0, ssl=ssl_context)

    server = loop_runner.run(_start())
    return server, server.sockets[0].getsockname()[1]


def stop_server(loop_runner, server) -> None:
    server.close()
    loop_runner.run(server.wait_closed())


def wait_for_route(proxy: SmartProxy, host: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        route = proxy.routing.get(host)
        if route is not None:
            return route
        time.sleep(0.02)
    return proxy.routing.get(host)


# --------------------------------------------------------------------------
# origin servers
# --------------------------------------------------------------------------
async def tls_http_origin(reader, writer) -> None:
    try:
        await reader.readuntil(b"\r\n\r\n")
        body = b"hello-tls"
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
            % len(body)
        )
        writer.write(body)
        await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()


async def silent_unless_fragmented_origin(reader, writer) -> None:
    """Reply only when the ClientHello arrived split across TLS records."""
    data = b""
    try:
        while not has_full_first_record(data):
            chunk = await reader.read(65536)
            if not chunk:
                return
            data += chunk
        if handshake_spans_records(data):
            writer.write(b"\x16\x03\x03\x00\x00")  # a TLS handshake record
            await writer.drain()
        await asyncio.sleep(0.5)
    except ConnectionError:
        pass
    finally:
        writer.close()


def stream_origin(total: int):
    async def handler(reader, writer) -> None:
        try:
            await reader.read(1024)
            chunk = b"x" * 65536
            sent = 0
            while sent < total:
                count = min(len(chunk), total - sent)
                writer.write(chunk[:count])
                sent += count
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    return handler


async def half_close_origin(reader, writer) -> None:
    """Read until the peer half-closes, then answer and close."""
    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
        writer.write(b"RESPONSE")
        await writer.drain()
    except ConnectionError:
        pass
    finally:
        writer.close()


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------
def test_missing_or_wrong_auth_gets_407(loop_runner):
    proxy = start_proxy(loop_runner, allow_local_targets=True)
    try:
        sock, status = http_connect(proxy.port, None, "example.com:443")
        assert "407" in status
        sock.close()

        sock, status = http_connect(proxy.port, "bad:creds", "example.com:443")
        assert "407" in status
        sock.close()
    finally:
        loop_runner.run(proxy.stop())


def test_loopback_target_is_refused(loop_runner):
    proxy = start_proxy(loop_runner)  # local targets blocked by default
    try:
        sock, status = http_connect(proxy.port, basic(credentials(proxy)), "127.0.0.1:443")
        assert "403" in status
        sock.close()
    finally:
        loop_runner.run(proxy.stop())


def test_plain_http_method_gets_405(loop_runner):
    proxy = start_proxy(loop_runner)
    try:
        sock = socket.create_connection(("127.0.0.1", proxy.port), timeout=10)
        sock.sendall(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
        data = sock.recv(4096)
        assert b"405" in data
        sock.close()
    finally:
        loop_runner.run(proxy.stop())


def test_direct_tunnel_returns_http_200(loop_runner, tls_material):
    cert, key = tls_material
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    origin, origin_port = start_origin(loop_runner, tls_http_origin, context)
    proxy = start_proxy(loop_runner, allow_local_targets=True)
    try:
        target = f"127.0.0.1:{origin_port}"
        sock, status = http_connect(proxy.port, basic(credentials(proxy)), target)
        assert "200 Connection Established" in status

        client_ctx = ssl.create_default_context(cafile=str(cert))
        tls = client_ctx.wrap_socket(sock, server_hostname="localhost")
        tls.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        response = recv_all(tls)
        tls.close()

        assert b"200 OK" in response
        assert b"hello-tls" in response
        assert proxy.routing.get("127.0.0.1") is None  # direct, nothing learned
    finally:
        loop_runner.run(proxy.stop())
        stop_server(loop_runner, origin)


def test_escalates_direct_to_frag_and_learns_route(loop_runner):
    origin, origin_port = start_origin(loop_runner, silent_unless_fragmented_origin)
    proxy = start_proxy(loop_runner, allow_local_targets=True, t1=0.4)
    try:
        target = f"127.0.0.1:{origin_port}"
        sock, status = http_connect(proxy.port, basic(credentials(proxy)), target)
        assert "200 Connection Established" in status

        sock.sendall(client_hello_bytes("127.0.0.1"))
        route = wait_for_route(proxy, "127.0.0.1")
        assert route is not None, "proxy should have learned a frag route"
        assert route.transport == "frag"
        sock.close()
    finally:
        loop_runner.run(proxy.stop())
        stop_server(loop_runner, origin)


def test_large_relay_uses_bounded_memory(loop_runner):
    total = 8 * 1024 * 1024
    origin, origin_port = start_origin(loop_runner, stream_origin(total))
    proxy = start_proxy(loop_runner, allow_local_targets=True)
    try:
        target = f"127.0.0.1:{origin_port}"
        sock, status = http_connect(proxy.port, basic(credentials(proxy)), target)
        assert "200 Connection Established" in status

        sock.sendall(b"GET / HTTP/1.0\r\n\r\n")
        tracemalloc.start()
        received = 0
        while received < total:
            chunk = sock.recv(65536)
            if not chunk:
                break
            received += len(chunk)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        sock.close()

        assert received == total
        # Backpressure: the relay must not buffer the whole transfer.
        assert peak < total // 2
    finally:
        loop_runner.run(proxy.stop())
        stop_server(loop_runner, origin)


def test_half_close_is_propagated(loop_runner):
    origin, origin_port = start_origin(loop_runner, half_close_origin)
    proxy = start_proxy(loop_runner, allow_local_targets=True)
    try:
        target = f"127.0.0.1:{origin_port}"
        sock, status = http_connect(proxy.port, basic(credentials(proxy)), target)
        assert "200 Connection Established" in status

        sock.sendall(b"HELLO")
        sock.shutdown(socket.SHUT_WR)  # half-close: we still want to read
        response = recv_all(sock)
        sock.close()

        assert response == b"RESPONSE"
    finally:
        loop_runner.run(proxy.stop())
        stop_server(loop_runner, origin)


def test_proxy_uses_random_credentials(loop_runner):
    first = start_proxy(loop_runner)
    second = start_proxy(loop_runner)
    try:
        assert credentials(first) != credentials(second)
    finally:
        loop_runner.run(first.stop())
        loop_runner.run(second.stop())
