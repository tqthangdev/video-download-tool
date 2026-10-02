"""
core/updater/downloader.py

Streams a release asset into the update folder, reporting progress and cleaning
up after itself when something goes wrong.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

import requests

CHUNK_BYTES = 256 * 1024
# (connect, read) timeouts: a release package is large, so reads get room.
TIMEOUT = (15, 60)
# A dropped connection should not kill the whole update.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 1.5
RETRYABLE_HTTP = (408, 429)


class DownloadError(Exception):
    """The package could not be downloaded."""


def _should_retry(error: Exception) -> bool:
    """Retry connection/timeout errors and server-side HTTP errors, nothing else."""
    if isinstance(error, DownloadError):
        message = str(error)
        if not message.startswith("HTTP "):
            return False
        try:
            code = int(message.split()[1])
        except (IndexError, ValueError):
            return False
        return code >= 500 or code in RETRYABLE_HTTP
    return isinstance(error, requests.RequestException)


def _download_once(
    url: str,
    tmp: Path,
    progress: Optional[Callable[[int, int], None]],
    cancel: Optional[Callable[[], bool]],
) -> None:
    with requests.get(url, stream=True, timeout=TIMEOUT) as resp:
        if resp.status_code != 200:
            raise DownloadError(f"HTTP {resp.status_code}")

        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(CHUNK_BYTES):
                if cancel and cancel():
                    raise DownloadError("cancelled")
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)


def download_asset(
    url: str,
    dest: Path,
    progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
    attempts: int = RETRY_ATTEMPTS,
) -> Path:
    """Download `url` to `dest`; returns `dest`.

    progress: called with (bytes_done, bytes_total) — total is 0 when the server
    does not report a length. Transient failures are retried; a partial file is
    removed on failure or cancel.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")

    error: Optional[Exception] = None
    for attempt in range(1, max(1, attempts) + 1):
        if cancel and cancel():
            tmp.unlink(missing_ok=True)
            raise DownloadError("cancelled")

        try:
            _download_once(url, tmp, progress, cancel)
        except Exception as e:  # noqa: BLE001 - classified by _should_retry
            tmp.unlink(missing_ok=True)
            if not _should_retry(e):
                if isinstance(e, DownloadError):
                    raise
                raise DownloadError(str(e) or type(e).__name__) from e
            error = e
        else:
            tmp.replace(dest)
            return dest

        if attempt < attempts:
            time.sleep(RETRY_BACKOFF * attempt)

    if isinstance(error, DownloadError):
        raise error
    raise DownloadError(str(error) or "download failed")
