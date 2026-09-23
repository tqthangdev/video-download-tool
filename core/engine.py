"""Worker pool + job orchestration (flow.md #19, #30, #50, #52).

The GUI only ever talks to the Engine; the Engine talks to the Downloader,
which talks to YtdlpClient (flow.md #52). Blocking yt-dlp work runs in the
default thread pool so the Qt event loop stays responsive (flow.md #53).
"""

import asyncio
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core.downloader import Downloader
from core.errors import CANCELLED
from core.job_manager import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    STATUS_WAITING,
    Job,
    JobManager,
)
from core.logger import logger
from core.utils import CONFIG, remove_partial_files
from core.ytdlp import YtdlpClient, ffmpeg_available


class Engine(QObject):
    # (job_key, status_text) — job_key is Job.key (url + selected format).
    progress = pyqtSignal(str, str)
    # Emitted whenever the run state changes on its own (queue finished or a
    # worker crashed) so the UI can resync its buttons without a manual pause.
    finished = pyqtSignal()

    def __init__(self, max_workers=3, config: dict | None = None):
        super().__init__()
        self.config = config or CONFIG
        self.max_workers = max(1, int(max_workers))
        self.db = JobManager()
        self.client = YtdlpClient(self.config)
        self.downloader = Downloader(self.client)

        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.running = False
        self.workers: list[asyncio.Task] = []
        self.active_jobs: dict[str, Job] = {}
        self.deleted_keys: set[str] = set()
        self._run_task = None

    def ffmpeg_available(self) -> bool:
        return ffmpeg_available()

    # ------------------------------------------------------------------
    # QUEUE MANAGEMENT
    # ------------------------------------------------------------------

    async def add_job(self, job: Job) -> str:
        """Add a job to the queue, resolving against the DB record.

        Returns one of: queued, resume, already_queued, already_running,
        already_downloaded.
        """
        existing = self.db.get(job.url, job.format_key)

        if existing:
            job.id = existing.id
            # Prefer the save path currently chosen in the GUI.
            if existing.save_path != job.save_path:
                self.db.update_save_path(job.id, job.save_path)

            status = existing.status

            if status == STATUS_RUNNING:
                return "already_running"
            if status == STATUS_WAITING:
                return "already_queued"

            if status == STATUS_DONE:
                # Already finished: only re-queue if the output is gone (flow.md #32).
                from core.downloader import verify_output

                if existing.output_file and verify_output(existing.output_file):
                    return "already_downloaded"

            self.db.update_status(job.id, STATUS_WAITING)
            await self.queue.put(job)
            return "resume"

        job = self.db.add(job)
        await self.queue.put(job)
        return "queued"

    async def del_job(self, key: str) -> bool:
        """Remove a job entirely: queue, active download, DB record, temp files."""
        existing = None
        for job in self.db.all_jobs():
            if job.key == key:
                existing = job
                break

        # Drop it from the queue if it is only waiting.
        was_queued = False
        queued_job = None
        pending = []
        while not self.queue.empty():
            queued = self.queue.get_nowait()
            if queued.key == key:
                was_queued = True
                queued_job = queued
                continue
            pending.append(queued)
        for queued in pending:
            self.queue.put_nowait(queued)

        was_running = key in self.active_jobs
        if was_running:
            self.deleted_keys.add(key)
            self.active_jobs.pop(key, None)

        if existing:
            await self.db.adelete(existing.id)

        # A running download still has its .part file open (yt-dlp keeps writing
        # until the cancel flag is seen), so the worker removes those once it has
        # actually stopped. Idle jobs have no writer, so clean them right away —
        # together with the media file their leftovers belong to (flow.md #27).
        if not was_running:
            job = queued_job or existing
            if job is not None:
                remove_partial_files(job.save_path, job.title, include_output=True)

        return bool(existing or was_queued or was_running)

    # ------------------------------------------------------------------
    # RUN / STOP
    # ------------------------------------------------------------------

    async def start(self):
        if self.running:
            return
        self.running = True
        self._run_task = asyncio.ensure_future(self._run_workers())

    async def stop(self):
        self.running = False

        active = list(self.active_jobs.values())
        self.db.update_status_bulk([job.id for job in active if job.id], STATUS_PAUSED)

        for task in self.workers:
            task.cancel()
        self.workers.clear()
        self.active_jobs.clear()

        if self._run_task:
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
            self._run_task = None

        # Re-queue the paused jobs so Resume re-runs them with the same format.
        for job in active:
            job.status = STATUS_PAUSED
            await self.queue.put(job)

    async def _run_workers(self):
        try:
            self.workers = [
                asyncio.create_task(self.worker(index))
                for index in range(self.max_workers)
            ]
            await asyncio.gather(*self.workers, return_exceptions=True)
        finally:
            self.running = False
            self.workers.clear()
            self._run_task = None
            self.finished.emit()

    async def worker(self, wid: int):
        loop = asyncio.get_running_loop()

        while self.running:
            try:
                job = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if job.key in self.deleted_keys:
                self.deleted_keys.discard(job.key)
                self.queue.task_done()
                continue

            self.active_jobs[job.key] = job
            try:
                await self.db.aupdate_status(job.id, STATUS_RUNNING)
                self.progress.emit(job.key, "Starting...")
                logger.info(f"[W{wid}] {job.title} ({job.format_label})")

                result = await loop.run_in_executor(None, self._download_sync, job)

                if job.key in self.deleted_keys:
                    self.deleted_keys.discard(job.key)
                    logger.info(f"[{job.title}] Job deleted mid-download, skipping.")
                    # yt-dlp has stopped by now, so its partial files are no
                    # longer being written and can be removed safely, along with
                    # the half-written media file they belong to (flow.md #27).
                    if job.key not in self.active_jobs:
                        remove_partial_files(job.save_path, job.title, include_output=True)
                elif result.ok:
                    await self.db.aupdate_output(job.id, result.output_file)
                    await self.db.aupdate_status(job.id, STATUS_DONE)
                    # A resumed job can finish through post-processing, or be
                    # skipped because the output already exists; either way any
                    # temporary file left from the interrupted run is now stale.
                    # Only the temporaries go — this output is the good one.
                    remove_partial_files(job.save_path, job.title)
                    self.progress.emit(job.key, "Done")
                    logger.info(f"DONE: {job.title} -> {result.output_file}")
                elif result.error is not None and result.error.code == CANCELLED:
                    await self.db.aupdate_status(job.id, STATUS_PAUSED)
                    self.progress.emit(job.key, "Paused")
                else:
                    message = str(result.error) if result.error else "Download failed."
                    await self.db.aupdate_error(job.id, message)
                    await self.db.aupdate_status(job.id, STATUS_FAILED)
                    # Failed is terminal: nothing will resume this job, so its
                    # scratch files and the half-written media file they belong
                    # to must not be left on disk (flow.md #27).
                    remove_partial_files(job.save_path, job.title, include_output=True)
                    self.progress.emit(job.key, "Failed")
                    logger.warning(f"[{job.title}] Failed: {message}")

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"ERROR processing job [{job.title}]: {exc}", exc_info=True)
                await self.db.aupdate_error(job.id, str(exc))
                await self.db.aupdate_status(job.id, STATUS_FAILED)
                self.progress.emit(job.key, "Failed")
            finally:
                self.active_jobs.pop(job.key, None)
                self.queue.task_done()

    def _download_sync(self, job: Job):
        """Runs in the thread pool (blocking yt-dlp work)."""

        def should_cancel() -> bool:
            return not self.running or job.key in self.deleted_keys

        def on_progress(event: dict):
            if self.running:
                from core.downloader import format_progress

                self.progress.emit(job.key, format_progress(event))

        return self.downloader.download_job(
            job, progress=on_progress, should_cancel=should_cancel
        )

    # ------------------------------------------------------------------
    # RESTORE / PATH SYNC
    # ------------------------------------------------------------------

    async def restore_session(self, base_path: str | None = None):
        """Restore incomplete jobs from the previous session (flow.md #31)."""
        jobs = self.db.get_restorable_jobs()
        total = len(jobs)

        for current, job in enumerate(jobs, start=1):
            if base_path:
                new_path = Path(base_path)
                if job.save_path != new_path:
                    job.save_path = new_path
                    self.db.update_save_path(job.id, new_path)

            self.db.update_status(job.id, STATUS_WAITING)
            job.status = STATUS_WAITING
            await self.queue.put(job)

            yield current, total, job

            if current % 10 == 0:
                await asyncio.sleep(0)

    async def sync_paths(self, base_path: str | None = None):
        """Apply the current save path to jobs still waiting in the queue."""
        if not base_path:
            return

        new_path = Path(base_path)
        pending = []
        while not self.queue.empty():
            job = self.queue.get_nowait()
            if job.save_path != new_path:
                job.save_path = new_path
                self.db.update_save_path(job.id, new_path)
            pending.append(job)

        for job in pending:
            self.queue.put_nowait(job)
