"""SQLite persistence for the download queue (flow.md #45, #46).

A job is one URL + one selected output format. The same URL may exist several
times with different formats, so the logical identity is (url, format_key).
"""

import asyncio
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.utils import DATA_DIR

DB_PATH = DATA_DIR / "jobs.db"

STATUS_WAITING = "waiting"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_FAILED = "failed"
STATUS_DONE = "done"
STATUS_DONE_WITH_MISSING = "done_with_missing"

# Jobs that must come back on the next launch (flow.md #31).
RESTORABLE_STATUSES = (
    STATUS_WAITING,
    STATUS_RUNNING,
    STATUS_PAUSED,
    STATUS_FAILED,
    STATUS_DONE_WITH_MISSING,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Job:
    url: str
    title: str
    save_path: Path
    selected_format: dict | None = None
    status: str = STATUS_WAITING
    thumbnail: str | None = None
    extractor: str | None = None
    output_file: str | None = None
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    error: str | None = None
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def format_key(self) -> str:
        return str((self.selected_format or {}).get("format_id") or "")

    @property
    def key(self) -> str:
        """Logical identity used by the queue/UI: URL + selected format."""
        return f"{self.url}#{self.format_key}"

    @property
    def format_label(self) -> str:
        fmt = self.selected_format or {}
        group = fmt.get("group") or ""
        label = fmt.get("label") or ""
        return f"{group} {label}".strip()

    @property
    def output_ext(self) -> str:
        return (self.selected_format or {}).get("output_ext") or ""


class JobManager:

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the executor calls from a different thread
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # sqlite3 connections are not thread-safe -> guard writes with a lock
        self._lock = threading.Lock()
        self._create_table()
        self._migrate()

    # ------------------------------------------------------------------
    # SCHEMA
    # ------------------------------------------------------------------

    def _create_table(self):
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    url              TEXT NOT NULL,
                    title            TEXT,
                    save_path        TEXT,
                    status           TEXT DEFAULT 'waiting',
                    selected_format  TEXT,
                    format_key       TEXT,
                    thumbnail        TEXT,
                    extractor        TEXT,
                    output_file      TEXT,
                    downloaded_bytes INTEGER DEFAULT 0,
                    total_bytes      INTEGER,
                    error            TEXT,
                    created_at       TEXT,
                    updated_at       TEXT,
                    UNIQUE(url, format_key)
                )
            """)
            self.conn.commit()

    def _migrate(self):
        """Drop the legacy comic-downloader schema if it is present.

        The old table keyed jobs by url and stored chapters/genres; the new
        architecture keys them by (url, selected format), so the old shape
        cannot be carried over.
        """
        with self._lock:
            cols = {row[1] for row in self.conn.execute("PRAGMA table_info(jobs)")}
            legacy = {"chapters", "current_chap", "genres", "thumb", "referer", "site_id"}
            if cols & legacy:
                self.conn.execute("DROP TABLE jobs")
                self.conn.commit()
        self._create_table()

    # ------------------------------------------------------------------
    # SERIALIZATION HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _format_to_json(selected_format) -> str | None:
        if not selected_format:
            return None
        try:
            return json.dumps(selected_format, ensure_ascii=False)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_from_json(raw) -> dict | None:
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            save_path=Path(row["save_path"]) if row["save_path"] else Path("."),
            selected_format=JobManager._format_from_json(row["selected_format"]),
            status=row["status"],
            thumbnail=row["thumbnail"],
            extractor=row["extractor"],
            output_file=row["output_file"],
            downloaded_bytes=row["downloaded_bytes"] or 0,
            total_bytes=row["total_bytes"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, job: Job) -> Job:
        """Insert the job, or return the existing row for (url, format)."""
        existing = self.get(job.url, job.format_key)
        if existing:
            return existing

        now = _now()
        with self._lock:
            cursor = self.conn.execute(
                """
                INSERT INTO jobs (
                    url, title, save_path, status, selected_format, format_key,
                    thumbnail, extractor, output_file, downloaded_bytes,
                    total_bytes, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.url, job.title, str(job.save_path), job.status,
                    self._format_to_json(job.selected_format), job.format_key,
                    job.thumbnail, job.extractor, job.output_file,
                    job.downloaded_bytes, job.total_bytes, job.error, now, now,
                ),
            )
            self.conn.commit()
            job.id = cursor.lastrowid
        job.created_at = job.created_at or now
        job.updated_at = now
        return job

    def get(self, url: str, format_key: str) -> Job | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM jobs WHERE url = ? AND format_key = ?",
                (url, format_key),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def get_by_id(self, job_id: int) -> Job | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def all_jobs(self) -> list[Job]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
        return [self._row_to_job(r) for r in rows]

    def get_restorable_jobs(self) -> list[Job]:
        placeholders = ",".join("?" for _ in RESTORABLE_STATUSES)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM jobs WHERE status IS NULL OR status IN ({placeholders}) "
                "ORDER BY id",
                RESTORABLE_STATUSES,
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def update_status(self, job_id: int, status: str):
        self._update(job_id, "status = ?", (status,))

    def update_status_bulk(self, job_ids: list[int], status: str):
        if not job_ids:
            return
        with self._lock:
            self.conn.executemany(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                [(status, _now(), job_id) for job_id in job_ids],
            )
            self.conn.commit()

    def update_save_path(self, job_id: int, save_path: Path):
        self._update(job_id, "save_path = ?", (str(save_path),))

    def update_output(self, job_id: int, output_file: str | None):
        self._update(job_id, "output_file = ?", (output_file,))

    def update_error(self, job_id: int, error: str | None):
        self._update(job_id, "error = ?", (error,))

    def update_progress(self, job_id: int, downloaded_bytes, total_bytes):
        self._update(
            job_id,
            "downloaded_bytes = ?, total_bytes = ?",
            (downloaded_bytes, total_bytes),
        )

    def update_format(self, job_id: int, selected_format: dict):
        self._update(
            job_id,
            "selected_format = ?, format_key = ?",
            (self._format_to_json(selected_format), str(selected_format.get("format_id") or "")),
        )

    def _update(self, job_id: int, assignments: str, params: tuple):
        if job_id is None:
            return
        with self._lock:
            self.conn.execute(
                f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?",
                (*params, _now(), job_id),
            )
            self.conn.commit()

    def delete(self, job_id: int):
        if job_id is None:
            return
        with self._lock:
            self.conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self.conn.commit()

    def delete_bulk(self, job_ids: list[int]):
        if not job_ids:
            return
        with self._lock:
            self.conn.executemany(
                "DELETE FROM jobs WHERE id = ?",
                [(job_id,) for job_id in job_ids],
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # ASYNC WRAPPERS - used in the hot path so DB writes do not block the
    # event loop (qasync shares the loop with the GUI).
    # ------------------------------------------------------------------

    async def aupdate_status(self, job_id: int, status: str):
        await asyncio.get_running_loop().run_in_executor(
            None, self.update_status, job_id, status
        )

    async def aupdate_output(self, job_id: int, output_file: str | None):
        await asyncio.get_running_loop().run_in_executor(
            None, self.update_output, job_id, output_file
        )

    async def aupdate_error(self, job_id: int, error: str | None):
        await asyncio.get_running_loop().run_in_executor(
            None, self.update_error, job_id, error
        )

    async def aupdate_progress(self, job_id: int, downloaded_bytes, total_bytes):
        await asyncio.get_running_loop().run_in_executor(
            None, self.update_progress, job_id, downloaded_bytes, total_bytes
        )

    async def aupdate_save_path(self, job_id: int, save_path: Path):
        await asyncio.get_running_loop().run_in_executor(
            None, self.update_save_path, job_id, save_path
        )

    async def adelete(self, job_id: int):
        await asyncio.get_running_loop().run_in_executor(None, self.delete, job_id)

    async def aadd(self, job: Job) -> Job:
        return await asyncio.get_running_loop().run_in_executor(None, self.add, job)
