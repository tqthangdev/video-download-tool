"""Download orchestration / progress adapter (flow.md #20, #23, #24, #28).

Wraps YtdlpClient: verifies existing output, converts yt-dlp progress events
into a human-readable status string, and verifies the produced file.
"""

from __future__ import annotations

from pathlib import Path

from core.errors import OUTPUT_MISSING, app_error
from core.utils import expected_output_path, resolve_output_file
from core.ytdlp import DownloadResult, YtdlpClient


def verify_output(path) -> bool:
    """A file counts as complete only if it exists and is non-empty."""
    if not path:
        return False
    candidate = Path(path)
    try:
        return candidate.is_file() and candidate.stat().st_size > 0
    except OSError:
        return False


def _human_bytes(value) -> str:
    if not value:
        return "0 B"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TiB"


def _human_speed(value) -> str:
    return f"{_human_bytes(value)}/s" if value else ""


def _human_eta(value) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    if seconds < 0:
        return ""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"ETA {hours:d}:{minutes:02d}:{seconds:02d}"
    return f"ETA {minutes:02d}:{seconds:02d}"


def format_progress(event: dict) -> str:
    """Render a progress event as the queue status text (flow.md #23)."""
    status = event.get("status")
    if status == "finished":
        return "Processing..."

    downloaded = event.get("downloaded_bytes") or 0
    total = event.get("total_bytes")
    speed = _human_speed(event.get("speed"))
    eta = _human_eta(event.get("eta"))

    if total:
        percent = int(downloaded / total * 100)
        text = f"Downloading {percent}%  {_human_bytes(downloaded)} / {_human_bytes(total)}"
    else:
        text = f"Downloading  {_human_bytes(downloaded)}"

    extra = "  ".join(part for part in (speed, eta) if part)
    return f"{text}  {extra}".strip()


class Downloader:
    """Orchestrates one job's download on top of YtdlpClient."""

    def __init__(self, client: YtdlpClient):
        self.client = client

    def download_job(self, job, progress=None, should_cancel=None) -> DownloadResult:
        fmt = job.selected_format or {}
        output_ext = fmt.get("output_ext") or "mp4"

        final_path = expected_output_path(job.save_path, job.title, output_ext)
        if verify_output(final_path):
            # Already downloaded and valid -> skip (flow.md #28).
            return DownloadResult(True, output_file=str(final_path))

        result = self.client.download(job, on_progress=progress, should_cancel=should_cancel)
        if not result.ok:
            return result

        if verify_output(result.output_file):
            return result

        resolved = resolve_output_file(job.save_path, job.title, output_ext)
        if resolved is not None and verify_output(resolved):
            return DownloadResult(True, output_file=str(resolved))

        return DownloadResult(False, error=app_error(OUTPUT_MISSING))
