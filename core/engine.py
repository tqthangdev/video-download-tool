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
from core.utils import CONFIG, cleanup_orphan_temp_dirs, remove_job_temp_dir
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
        self.processing_jobs: set[str] = set()

    def ffmpeg_available(self) -> bool:
        return ffmpeg_available()

    # ------------------------------------------------------------------
    # QUEUE MANAGEMENT
    # ------------------------------------------------------------------

    async def add_job(self, job: Job) -> str:
        """Add a job to the queue, resolving against the DB record.

        Returns one of: queued, resume, already_queued, already_running,
        already_downloaded. A duplicate is only a duplicate within the same
        session; the same URL in another session is a separate job.
        """
        existing = self.db.get(job.url, job.format_key, job.session_id)

        if existing:
            job.id = existing.id
            # Prefer the save path currently chosen in the GUI.
            if existing.save_path != job.save_path:
                self.db.update_save_path(job.id, job.save_path)

            status = existing.status

            if status == STATUS_RUNNING:
                return "already_running"
            # A DB status of "waiting" is not enough: the queue may have been
            # cleared (switching sessions) while the row kept that status, so
            # check the live queue before reporting a duplicate.
            if status == STATUS_WAITING and self._is_queued(job.key):
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

    def _is_queued(self, key: str) -> bool:
        """True when the job is waiting in the queue or downloading right now."""
        if key in self.active_jobs:
            return True
        return any(job.key == key for job in self.queue._queue)

    async def del_job(self, key: str) -> bool:
        """Remove a job entirely: queue, active download, DB record, temp files.

        The same URL + format may exist in another session, so the job that is
        actually queued/downloading (or in the DB) is the one removed.
        """
        # Drop it from the queue if it is only waiting.
        was_queued = False
        queued_job = None
        pending = []
        while not self.queue.empty():
            queued = self.queue.get_nowait()
            if not was_queued and queued.key == key:
                was_queued = True
                queued_job = queued
                continue
            pending.append(queued)
        for queued in pending:
            self.queue.put_nowait(queued)

        active_job = self.active_jobs.get(key)
        was_running = active_job is not None
        if was_running:
            self.deleted_keys.add(key)
            self.active_jobs.pop(key, None)

        target = queued_job or active_job
        if target is None:
            for job in self.db.all_jobs():
                if job.key == key:
                    target = job
                    break

        if target is not None and target.id is not None:
            await self.db.adelete(target.id)

        # A running download still has its scratch folder open (yt-dlp keeps
        # writing until the cancel flag is seen), so the worker removes it once
        # the download has actually stopped. Idle jobs have no writer, so their
        # scratch folder can go right away (flow.md #27).
        if not was_running and target is not None:
            remove_job_temp_dir(target.save_path, target.id)

        return target is not None or was_queued or was_running

    # ------------------------------------------------------------------
    # RUN / STOP
    # ------------------------------------------------------------------

    async def start(self):
        if self.running:
            return
        self.running = True
        self._run_task = asyncio.ensure_future(self._run_workers())

    async def stop(self):
        """Stop active downloads without deleting their .part files."""
        if not self.running and not self.workers:
            return

        self.running = False

        # Snapshot active jobs before workers remove themselves from active_jobs.
        active = list(self.active_jobs.values())

        # Do NOT cancel worker tasks.
        #
        # yt-dlp runs in a thread-pool executor. Cancelling the asyncio worker
        # would not reliably stop the underlying yt-dlp thread.
        #
        # Instead, should_cancel() notices running=False and the progress hook
        # raises _Cancelled. yt-dlp then exits while keeping its .part file.
        if self._run_task:
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            finally:
                self._run_task = None

        # All active yt-dlp downloads have stopped at this point.
        # Re-queue them so the next Start resumes the existing .part files.
        for job in active:
            if job.key in self.processing_jobs:
                continue

            job.status = STATUS_PAUSED
            self.progress.emit(job.key, "Paused")
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
                    # yt-dlp has stopped by now, so its scratch folder is no
                    # longer being written and can be removed safely (flow.md #27).
                    if job.key not in self.active_jobs:
                        remove_job_temp_dir(job.save_path, job.id)
                elif result.ok:
                    await self.db.aupdate_output(job.id, result.output_file)
                    await self.db.aupdate_status(job.id, STATUS_DONE)
                    # The output was moved out of the scratch folder already;
                    # this clears whatever a resumed run left behind.
                    remove_job_temp_dir(job.save_path, job.id)
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
                    # scratch folder must not be left on disk (flow.md #27).
                    remove_job_temp_dir(job.save_path, job.id)
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
                self.processing_jobs.discard(job.key)
                self.queue.task_done()

    def _download_sync(self, job):
        """Runs in the thread pool (blocking yt-dlp work)."""

        def should_cancel() -> bool:
            # Once yt-dlp has finished downloading and entered post-processing,
            # Pause must not interrupt the job.
            if job.key in self.processing_jobs:
                return job.key in self.deleted_keys

            return not self.running or job.key in self.deleted_keys

        def on_progress(event: dict):
            status = event.get("status")

            if status == "finished":
                self.processing_jobs.add(job.key)

            if self.running or job.key in self.processing_jobs:
                from core.downloader import format_progress

                self.progress.emit(job.key, format_progress(event))

        return self.downloader.download_job(
            job,
            progress=on_progress,
            should_cancel=should_cancel,
        )

    # ------------------------------------------------------------------
    # RESTORE / PATH SYNC
    # ------------------------------------------------------------------

    def _remove_dead_temp_dirs(self, base_path: str | None = None):
        """Drop scratch folders whose job no longer exists (flow.md #27).

        Scratch folders of restorable jobs are kept so yt-dlp can resume the
        partial download it left there (flow.md #29); the rest are dead weight.
        """
        keep_ids = {job.id for job in self.db.get_restorable_jobs()}
        paths = {job.save_path for job in self.db.all_jobs()}
        if base_path:
            paths.add(Path(base_path))

        try:
            removed = sum(cleanup_orphan_temp_dirs(p, keep_ids) for p in paths)
        except OSError as exc:
            logger.warning(f"Could not clean up download temp folders: {exc}")
            return

        if removed:
            logger.info(f"Removed {removed} orphaned download temp folder(s)")

    async def restore_session(self, base_path: str | None = None, session_id: int | None = None):
        """Restore incomplete jobs from the previous session (flow.md #31).

        Only the session that was active when the app closed -- plus items
        that were never saved into a session -- comes back, so different
        sessions are not mixed together on launch.
        """
        self._remove_dead_temp_dirs(base_path)
        session_ids = [0] if not session_id else [0, session_id]
        jobs = self.db.get_restorable_jobs(session_ids)
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

    # ------------------------------------------------------------------
    # SAVED SESSIONS
    #
    # A session is a named snapshot of the queue, so separate workloads
    # (e.g. YouTube vs. an anime site) can be kept apart and brought back
    # one at a time (feedback.md).
    # ------------------------------------------------------------------

    def sessions(self):
        return self.db.all_sessions()

    def create_session(self, name: str) -> int:
        """Open a fresh, empty session (filled when the new queue is saved)."""
        return self.db.create_session(name)

    def clear_pending(self):
        """Drop the jobs still waiting in the queue.

        The jobs themselves stay in the database; only the in-memory queue is
        emptied, so switching to a new session does not carry the old one over.
        """
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def save_session(self, name: str, session_id: int | None = None) -> int | None:
        """Snapshot the current queue into a session.

        Only jobs that do not already belong to a session are captured, so
        saving a new session never pulls items out of an existing one. When an
        existing `session_id` is given it is refreshed instead of creating a
        second one. Returns the session id, or None when there was nothing new
        to save.
        """
        if session_id is not None and self.db.get_session(session_id):
            self.db.assign_unassigned_jobs(session_id)
            return session_id

        if not self.db.has_unassigned_jobs():
            return None

        new_id = self.db.create_session(name)
        self.db.assign_unassigned_jobs(new_id)
        return new_id

    def rename_session(self, session_id: int, name: str):
        self.db.rename_session(session_id, name)

    def delete_session(self, session_id: int):
        """Remove a session; its jobs stay in the database (only unlinked)."""
        self.db.delete_session(session_id)

    async def restore_saved_session(
        self, session_id: int, base_path: str | None = None
    ) -> list[Job]:
        """Put a saved session's jobs back into the queue as waiting.

        This switches the queue over to the session: jobs still waiting from
        the previous view are dropped from the queue (they stay in the
        database), so restoring never mixes two sessions together.
        """
        jobs = self.db.session_jobs(session_id)
        if not jobs:
            return []

        # Drain the pending queue so it can be rebuilt for this session.
        self.clear_pending()

        # Jobs already downloading must not be queued again.
        busy = set(self.active_jobs)
        pending: list[Job] = []

        restored: list[Job] = []
        for job in jobs:
            if base_path:
                new_path = Path(base_path)
                if job.save_path != new_path:
                    job.save_path = new_path
                    self.db.update_save_path(job.id, new_path)

            if job.key not in busy:
                self.db.update_status(job.id, STATUS_WAITING)
                job.status = STATUS_WAITING
                pending.append(job)

            restored.append(job)

        for job in pending:
            self.queue.put_nowait(job)

        return restored
