"""Download orchestration / progress adapter (flow.md #20, #23, #24, #28).

Wraps YtdlpClient: verifies existing output, converts yt-dlp progress events
into a human-readable status string, and verifies the produced file.
"""

from __future__ import annotations

import subprocess
import shutil
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


def verify_media_integrity(path, timeout: int = 15) -> bool:
    """True if ffprobe can read the file's duration without error.

    A file can exist at its final name with size > 0 yet still be a
    truncated write (interrupted cross-filesystem copy, disk full, killed
    mid-rename) — verify_output()'s size-only check can't catch that.
    Used as a deeper, slower check during the one-off startup sweep, not
    on the hot resume path (ffprobe has to decode the file, so it's too
    slow to run on every skip-or-redownload decision).
    """
    if shutil.which("ffprobe") is None:
        return True  # no ffprobe available, fall back to size-only check

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False

    if result.returncode != 0 or result.stderr.strip():
        return False

    try:
        return float(result.stdout.strip()) > 0
    except ValueError:
        return False


def repair_broken_outputs(db) -> int:
    """Bounce 'done' jobs whose output is actually corrupt/truncated back
    to waiting, deleting the broken file so the resume path redownloads
    cleanly instead of skipping a bad file (flow.md sweep-on-restore)."""
    from core.logger import logger
    from core.job_manager import STATUS_DONE, STATUS_WAITING

    fixed = 0
    for job in db.all_jobs():
        if job.status != STATUS_DONE:
            continue
        if job.output_file and verify_output(job.output_file) and verify_media_integrity(job.output_file):
            continue

        if job.output_file:
            try:
                Path(job.output_file).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"[repair] could not remove broken output {job.output_file}: {exc}")

        db.update_status(job.id, STATUS_WAITING)
        db.update_output(job.id, None)
        fixed += 1
    return fixed


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
