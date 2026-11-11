"""Parallel Range downloader for direct HTTP(S) media files.

yt-dlp downloads a progressive MP4 over one connection. A server that throttles
each connection can be fed by several Range requests at once; this module is only
used for a direct media file the app resolved itself. It returns False when the
server does not advertise byte ranges, so the caller can fall back to yt-dlp.
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_CONNECTIONS = 8
MAX_CONNECTIONS = 16
MIN_TOTAL_BYTES = 4 * 1024 * 1024
MIN_CHUNK_BYTES = 1024 * 1024
MAX_CHUNK_BYTES = 4 * 1024 * 1024
READ_BYTES = 256 * 1024
MAX_RETRIES = 3
REPORT_INTERVAL = 0.25


class SegmentedError(Exception):
    """The file cannot be fetched by ranges; fall back to yt-dlp."""


class SegmentedCancelled(Exception):
    """The caller asked to stop the download."""


class _State:
    """Shared progress/cancellation state for the worker threads."""

    def __init__(
        self,
        total: int,
        connections: int,
        on_progress: Optional[Callable[[dict], None]],
        should_cancel: Optional[Callable[[], bool]],
    ) -> None:
        self.total = total
        self.connections = connections
        self.on_progress = on_progress
        self.should_cancel = should_cancel
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._done = 0
        self._started = time.monotonic()
        self._last_report = 0.0

    @property
    def done(self) -> int:
        with self._lock:
            return self._done

    def cancelled(self) -> bool:
        if self._cancel.is_set():
            return True
        if self.should_cancel is not None and self.should_cancel():
            self._cancel.set()
            return True
        return False

    def cancel(self) -> None:
        self._cancel.set()

    def add(self, count: int) -> None:
        with self._lock:
            self._done = min(self.total, self._done + count)

    def report(self, force: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_report < REPORT_INTERVAL:
                return
            self._last_report = now
            done = self._done
        if self.on_progress is None:
            return
        elapsed = max(now - self._started, 0.001)
        speed = done / elapsed
        eta = int((self.total - done) / speed) if speed > 0 and done < self.total else 0
        self.on_progress(
            {
                "status": "downloading",
                "downloaded_bytes": done,
                "total_bytes": self.total,
                "speed": speed,
                "eta": eta,
                "connections": self.connections,
            }
        )

    def finish(self) -> None:
        with self._lock:
            self._done = self.total
        if self.on_progress is not None:
            self.on_progress(
                {
                    "status": "finished",
                    "downloaded_bytes": self.total,
                    "total_bytes": self.total,
                    "speed": None,
                    "eta": 0,
                    "connections": self.connections,
                }
            )


def download_segmented(
    url: str,
    dest: Path,
    *,
    connections: int = DEFAULT_CONNECTIONS,
    headers: Optional[dict] = None,
    proxies: Optional[dict] = None,
    timeout: float = 30.0,
    on_progress: Optional[Callable[[dict], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> bool:
    """Download `url` into `dest` with parallel Range requests.

    Returns True on success. Returns False when the server is not suitable (the
    caller falls back to yt-dlp). Raises SegmentedCancelled on cancellation.
    """
    connections = max(1, min(int(connections), MAX_CONNECTIONS))
    if connections < 2:
        return False
    if should_cancel is not None and should_cancel():
        raise SegmentedCancelled()

    base_headers = dict(headers or {})
    total = _probe_size(url, base_headers, proxies, timeout)
    if total is None or total < MIN_TOTAL_BYTES:
        return False

    dest = Path(dest)
    try:
        free = shutil.disk_usage(dest.parent).free
    except OSError:
        free = total
    if free < total:
        logger.warning("[segmented] not enough disk space for %d bytes", total)
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    chunk_size = _chunk_size(total, connections)
    ranges = [
        (start, min(start + chunk_size, total) - 1)
        for start in range(0, total, chunk_size)
    ]
    state = _State(total, connections, on_progress, should_cancel)
    success = False

    try:
        dest.touch()
        os.truncate(dest, total)
        with open(dest, "r+b") as handle:
            file_lock = threading.Lock()

            def fetch(start: int, end: int) -> None:
                _fetch_range(
                    url,
                    start,
                    end,
                    handle,
                    file_lock,
                    state,
                    base_headers,
                    proxies,
                    timeout,
                )

            try:
                with ThreadPoolExecutor(
                    max_workers=connections, thread_name_prefix="segmented"
                ) as pool:
                    futures = [pool.submit(fetch, start, end) for start, end in ranges]
                    for future in as_completed(futures):
                        future.result()
            except SegmentedCancelled:
                state.cancel()
                raise
            except Exception as exc:
                state.cancel()
                raise SegmentedError(str(exc)) from exc
            finally:
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass

        state.finish()
        success = True
        return True
    finally:
        if not success:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass


def _probe_size(
    url: str,
    headers: dict,
    proxies: Optional[dict],
    timeout: float,
) -> Optional[int]:
    """Total size when the server answers a one-byte Range request with 206."""
    request_headers = {**headers, "Range": "bytes=0-0"}
    try:
        with requests.get(
            url,
            headers=request_headers,
            proxies=proxies,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        ) as response:
            if response.status_code != 206:
                return None
            content_range = response.headers.get("Content-Range", "")
            match = re.search(r"/(\d+)\s*$", content_range)
            if not match:
                return None
            return int(match.group(1))
    except Exception as exc:
        logger.debug("[segmented] range probe failed: %s", exc)
        return None


def _chunk_size(total: int, connections: int) -> int:
    per_worker = math.ceil(total / max(connections * 4, 1))
    return max(MIN_CHUNK_BYTES, min(MAX_CHUNK_BYTES, per_worker))


def _fetch_range(
    url: str,
    start: int,
    end: int,
    handle,
    file_lock: threading.Lock,
    state: _State,
    headers: dict,
    proxies: Optional[dict],
    timeout: float,
) -> None:
    length = end - start + 1
    for attempt in range(1, MAX_RETRIES + 1):
        if state.cancelled():
            raise SegmentedCancelled()

        request_headers = {**headers, "Range": f"bytes={start}-{end}"}
        try:
            with requests.get(
                url,
                headers=request_headers,
                proxies=proxies,
                stream=True,
                timeout=timeout,
                allow_redirects=True,
            ) as response:
                if response.status_code == 200:
                    raise SegmentedError("server ignored Range")
                if response.status_code != 206:
                    raise SegmentedError(f"HTTP {response.status_code}")

                buffer = bytearray()
                for chunk in response.iter_content(READ_BYTES):
                    if state.cancelled():
                        raise SegmentedCancelled()
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    if len(buffer) >= length:
                        del buffer[length:]
                        break

            if len(buffer) != length:
                raise SegmentedError(
                    f"short range {start}-{end}: {len(buffer)}/{length}"
                )

            with file_lock:
                handle.seek(start)
                handle.write(buffer)
            state.add(length)
            state.report()
            return
        except SegmentedCancelled:
            raise
        except Exception as exc:
            if state.cancelled():
                raise SegmentedCancelled()
            if attempt >= MAX_RETRIES:
                raise
            logger.debug(
                "[segmented] range %s-%s attempt %d failed: %s",
                start,
                end,
                attempt,
                exc,
            )
            time.sleep(0.4 * attempt)
