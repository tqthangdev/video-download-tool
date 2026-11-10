"""Runs a Tor SOCKS proxy for yt-dlp.

A Tor that is already listening is reused (the daemon on 9050, Tor Browser on
9150); otherwise the bundled / `PATH` tor binary is started with a private
DataDirectory. Bootstrapping happens in a background thread so the Qt loop is
never blocked; `on_ready` receives the proxy URL once the SOCKS port answers.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from core.utils import DATA_DIR, get_resource_path

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = (9050, 9150)  # tor daemon, Tor Browser
BOOTSTRAP_TIMEOUT = 60.0
POLL_INTERVAL = 0.25
STOP_TIMEOUT = 5.0


def tor_binary() -> Optional[str]:
    """The tor executable: bundled, vendored for dev, else the one on PATH."""
    exe_name = "tor.exe" if os.name == "nt" else "tor"
    candidates = (
        get_resource_path(f"tor/{exe_name}"),            # frozen bundle
        get_resource_path(f"vendor/tor/{exe_name}"),     # dev checkout
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(exe_name)


def _socks5_ready(host: str, port: int, timeout: float = 0.5) -> bool:
    """True when a SOCKS5 server answers the no-auth greeting."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(b"\x05\x01\x00")
            reply = sock.recv(2)
    except OSError:
        return False
    return len(reply) == 2 and reply[0] == 0x05 and reply[1] != 0xFF


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _pick_port(host: str) -> int:
    """Prefer the standard Tor ports so a leftover instance can be reused."""
    for port in DEFAULT_PORTS:
        if _port_free(host, port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


class TorManager:
    """Owns one Tor process (or reuses an existing SOCKS listener)."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        data_dir: Optional[Path] = None,
        timeout: float = BOOTSTRAP_TIMEOUT,
        binary: Optional[str] = None,
        on_ready: Optional[Callable[[str], None]] = None,
        on_failed: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._host = host
        self._data_dir = Path(data_dir) if data_dir else DATA_DIR / "tor"
        self._timeout = timeout
        self._binary = binary
        self._on_ready = on_ready
        self._on_failed = on_failed

        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._proxy_url: Optional[str] = None
        self._log_path = self._data_dir / "process.log"

    # ------------------------------------------------------------------ state
    @property
    def proxy_url(self) -> Optional[str]:
        return self._proxy_url

    @property
    def running(self) -> bool:
        return self._proxy_url is not None

    # ------------------------------------------------------------------- life
    def start(self) -> bool:
        """Start Tor (or reuse one); False when no Tor can be used.

        Bootstrapping is asynchronous: `proxy_url` is filled in by the worker
        thread and `on_ready` is called from it.
        """
        with self._lock:
            if self._proxy_url is not None:
                return True
            if self._thread is not None and self._thread.is_alive():
                return True

            self._stop.clear()

            self._ready.clear()

            existing = self._existing_proxy()
            if existing is not None:
                self._proxy_url = existing
                self._ready.set()
                logger.info("[Tor] reusing SOCKS listener at %s", existing)
                self._notify_ready(existing)
                return True

            binary = self._binary or tor_binary()
            if not binary:
                logger.warning("[Tor] no tor binary found")
                self._ready.set()
                self._notify_failed("tor binary not found")
                return False

            port = _pick_port(self._host)
            try:
                torrc = self._prepare(binary, port)
                process = self._spawn(binary, torrc)
            except OSError as exc:
                logger.warning("[Tor] could not start: %s", exc)
                self._ready.set()
                self._notify_failed(str(exc))
                return False

            self._process = process
            self._thread = threading.Thread(
                target=self._wait_ready,
                args=(process, port),
                name="tor-bootstrap",
                daemon=True,
            )
            self._thread.start()
            return True

    def wait_ready(self, timeout: Optional[float] = None) -> Optional[str]:
        """Wait for bootstrapping; returns the proxy URL or None on failure."""
        self._ready.wait(timeout)
        return self._proxy_url

    def start_and_wait(self, timeout: Optional[float] = None) -> Optional[str]:
        """Start Tor (or reuse one) and block until its SOCKS port answers."""
        if not self.start():
            return None
        return self.wait_ready(timeout)

    def stop(self) -> None:
        """Stop the Tor process this manager started (reused ones keep running)."""
        self._stop.set()
        with self._lock:
            process, self._process = self._process, None
            thread, self._thread = self._thread, None
            self._proxy_url = None
            self._ready.set()  # wake start_and_wait waiters
        if process is not None:
            _terminate(process)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=STOP_TIMEOUT)

    # --------------------------------------------------------------- internals
    def _existing_proxy(self) -> Optional[str]:
        for port in DEFAULT_PORTS:
            if _socks5_ready(self._host, port):
                return f"socks5h://{self._host}:{port}"
        return None

    def _prepare(self, binary: str, port: int) -> Path:
        """Write a private torrc and return its path."""
        data_dir = self._data_dir.resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                data_dir.chmod(0o700)
            except OSError:
                pass

        binary_dir = Path(binary).resolve().parent
        lines = [
            f"SocksPort {self._host}:{port}",
            f"DataDirectory {data_dir}",
            f"Log notice file {self._log_path.resolve()}",
            "MaxCircuitDirtiness 600",
        ]
        for name, option in (("geoip", "GeoIPFile"), ("geoip6", "GeoIPv6File")):
            candidate = binary_dir / name
            if candidate.is_file():
                lines.append(f"{option} {candidate.resolve()}")

        torrc = data_dir / "torrc"
        torrc.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if os.name != "nt":
            try:
                torrc.chmod(0o600)
            except OSError:
                pass
        return torrc

    def _spawn(self, binary: str, torrc: Path) -> subprocess.Popen:
        binary_dir = str(Path(binary).resolve().parent)
        env = os.environ.copy()
        if os.name != "nt":
            # The bundled binary carries its own OpenSSL/libevent libraries.
            existing = env.get("LD_LIBRARY_PATH")
            env["LD_LIBRARY_PATH"] = (
                binary_dir + (os.pathsep + existing if existing else "")
            )

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            log_file = open(self._log_path, "ab")
        except OSError:
            log_file = subprocess.DEVNULL
        try:
            return subprocess.Popen(
                [binary, "-f", str(torrc)],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=creationflags,
            )
        finally:
            if log_file is not subprocess.DEVNULL:
                log_file.close()

    def _wait_ready(self, process: subprocess.Popen, port: int) -> None:
        deadline = time.monotonic() + self._timeout
        while not self._stop.is_set() and time.monotonic() < deadline:
            if _socks5_ready(self._host, port):
                proxy = f"socks5h://{self._host}:{port}"
                with self._lock:
                    if self._stop.is_set() or self._process is not process:
                        return
                    self._proxy_url = proxy
                    self._ready.set()
                logger.info("[Tor] ready at %s", proxy)
                self._notify_ready(proxy)
                return
            if process.poll() is not None:
                break
            time.sleep(POLL_INTERVAL)

        if self._stop.is_set():
            return

        logger.warning("[Tor] did not become ready; see %s", self._log_path)
        with self._lock:
            if self._process is process:
                self._process = None
                self._proxy_url = None
                self._ready.set()
        self._notify_failed("tor did not become ready")
        _terminate(process)

    def _notify_ready(self, proxy_url: str) -> None:
        if self._on_ready is None:
            return
        try:
            self._on_ready(proxy_url)
        except Exception:  # noqa: BLE001 - a callback must never kill the thread
            logger.exception("[Tor] ready callback failed")

    def _notify_failed(self, reason: str) -> None:
        if self._on_failed is None:
            return
        try:
            self._on_failed(reason)
        except Exception:  # noqa: BLE001 - a callback must never kill the thread
            logger.exception("[Tor] failure callback failed")


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            pass
