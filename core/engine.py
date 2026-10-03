"""Worker pool + job orchestration (flow.md #19, #30, #50, #52).

The GUI only ever talks to the Engine; the Engine talks to the Downloader,
which talks to YtdlpClient (flow.md #52). Blocking yt-dlp work runs in the
default thread pool so the Qt event loop stays responsive (flow.md #53).
"""

import asyncio
import sqlite3
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core.downloader import Downloader
from core.errors import CANCELLED
from core.job_manager import (
    RESTORABLE_STATUSES,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    STATUS_WAITING,
    Job,
    JobManager,
)
from core.logger import logger
from core.network.manager import NetworkManager
from core.sessions import SessionStore, delete_session_files, session_db_path
from core.utils import (
    CONFIG,
    DATA_DIR,
    cleanup_orphan_temp_dirs,
    remove_job_temp_dir,
    remove_session_temp_dirs,
)
from core.ytdlp import YtdlpClient, ffmpeg_available


class Engine(QObject):
    # (job_key, status_text) — job_key is Job.key (url + selected format).
    progress = pyqtSignal(str, str)
    # Emitted whenever the run state changes on its own (queue finished or a
    # worker crashed) so the UI can resync its buttons without a manual pause.
    finished = pyqtSignal()

    def __init__(self, max_workers=3, config: dict | None = None, session_id: str | None = None):
        super().__init__()
        self.config = config or CONFIG
        self.max_workers = max(1, int(max_workers))

        # Each session is its own database file; open the current one.
        self.session_store = SessionStore()
        if session_id and self.session_store.get(session_id):
            self.session_store.set_current(session_id)
        session = self.session_store.ensure_current()
        self.session_id = session.id
        self.db = JobManager(session_db_path(session.id))

        # Local network fallback (core.network): a per-hostname direct/frag
        # proxy. Started by run.py at launch; yt-dlp/ffmpeg go through it.
        self.network = NetworkManager(
            enabled=bool(self.config.get("network_enabled", True)),
            routing_path=DATA_DIR / "network.json",
        )
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
    # NETWORK FALLBACK
    # ------------------------------------------------------------------
    def start_network(self) -> None:
        """Start the local fallback proxy (no-op when disabled)."""
        if self.network.start():
            self.client.set_proxy(self.network.proxy_url)
        else:
            self.client.set_proxy(None)

    def stop_network(self) -> None:
        self.network.stop()
        self.client.set_proxy(None)

    def apply_network_settings(self) -> None:
        """Re-read the config after the Settings dialog changed it."""
        self.network.set_enabled(bool(self.config.get("network_enabled", True)))
        self.client.set_proxy(self.network.proxy_url if self.network.running else None)

    # ------------------------------------------------------------------
    # QUEUE MANAGEMENT
    # ------------------------------------------------------------------

    async def add_job(self, job: Job) -> str:
        """Add a job to the current session's queue, resolving against the DB.

        Returns one of: queued, resume, already_queued, already_running,
        already_downloaded. A duplicate is a duplicate within this session only;
        the same URL in another session is a separate job.
        """
        job.session_id = self.session_id
        existing = self.db.get(job.url, job.format_key)

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

        if target is not None:
            target.session_id = target.session_id or self.session_id

        if target is not None and target.id is not None:
            await self.db.adelete(target.id)

        # A running download still has its scratch folder open (yt-dlp keeps
        # writing until the cancel flag is seen), so the worker removes it once
        # the download has actually stopped. Idle jobs have no writer, so their
        # scratch folder can go right away (flow.md #27).
        if not was_running and target is not None:
            remove_job_temp_dir(target.save_path, target.session_id, target.id)

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
                        remove_job_temp_dir(job.save_path, job.session_id, job.id)
                elif result.ok:
                    await self.db.aupdate_output(job.id, result.output_file)
                    await self.db.aupdate_status(job.id, STATUS_DONE)
                    # The output was moved out of the scratch folder already;
                    # this clears whatever a resumed run left behind.
                    remove_job_temp_dir(job.save_path, job.session_id, job.id)
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
                    remove_job_temp_dir(job.save_path, job.session_id, job.id)
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
        Every session is scanned, because a folder's owning session is not
        necessarily the one currently open.
        """
        keep: set[tuple[str, int]] = set()
        paths: set[Path] = set()
        for info in self.session_store.list():
            db = (
                self.db
                if info.id == self.session_id
                else JobManager(session_db_path(info.id))
            )
            try:
                for job in db.get_restorable_jobs():
                    keep.add((info.id, job.id))
                for job in db.all_jobs():
                    paths.add(job.save_path)
            except sqlite3.Error as exc:
                logger.warning(f"Could not scan session {info.id} for temp cleanup: {exc}")
            finally:
                if db is not self.db:
                    db.close()
        if base_path:
            paths.add(Path(base_path))

        try:
            removed = sum(cleanup_orphan_temp_dirs(p, keep) for p in paths)
        except OSError as exc:
            logger.warning(f"Could not clean up download temp folders: {exc}")
            return

        if removed:
            logger.info(f"Removed {removed} orphaned download temp folder(s)")

    async def restore_session(self, base_path: str | None = None):
        """Restore the current session's incomplete jobs (flow.md #31)."""
        self._remove_dead_temp_dirs(base_path)
        jobs = self.db.get_restorable_jobs()
        total = len(jobs)

        for current, job in enumerate(jobs, start=1):
            job.session_id = self.session_id
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
    # SESSIONS
    #
    # Each session is a self-contained queue in its own database file
    # (core/sessions.py). Switching opens that file; deleting removes it.
    # ------------------------------------------------------------------

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

    def list_sessions(self):
        return self.session_store.list()

    def current_session(self):
        return self.session_store.get(self.session_id)

    def job_count(self, session_id) -> int:
        """Number of jobs stored in a session (shown in the sessions dialog)."""
        if session_id == self.session_id:
            return self.db.count_jobs()
        db = JobManager(session_db_path(session_id))
        try:
            return db.count_jobs()
        finally:
            db.close()

    def create_session(self, name: str | None = None):
        """Register a fresh, empty session (call activate_session to use it)."""
        return self.session_store.create(name)

    def rename_session(self, session_id, name: str):
        self.session_store.rename(session_id, name)

    def _open_session_db(self, session_id: str):
        """Point the Engine at another session file and reset in-memory state."""
        self.db.close()
        self.session_id = session_id
        self.db = JobManager(session_db_path(session_id))
        self.session_store.set_current(session_id)
        self.queue = asyncio.Queue()
        self.active_jobs.clear()
        self.deleted_keys.clear()
        self.processing_jobs.clear()

    def open_session(self, session_id) -> bool:
        """Switch to another session. The caller must have stopped the engine."""
        if self.running or self.session_store.get(session_id) is None:
            return False
        if session_id != self.session_id:
            self._open_session_db(session_id)
        return True

    def activate_session(self, session_id, base_path: str | None = None) -> list[Job]:
        """Switch to a session and load its jobs (incomplete ones get queued)."""
        if not self.open_session(session_id):
            return []
        return self._load_current_jobs(base_path)

    def _load_current_jobs(self, base_path: str | None = None) -> list[Job]:
        """Every job of the current session; incomplete ones are queued."""
        jobs = self.db.all_jobs()
        for job in jobs:
            job.session_id = self.session_id
            if base_path:
                new_path = Path(base_path)
                if job.save_path != new_path:
                    job.save_path = new_path
                    self.db.update_save_path(job.id, new_path)
            if job.status is None or job.status in RESTORABLE_STATUSES:
                self.db.update_status(job.id, STATUS_WAITING)
                job.status = STATUS_WAITING
                self.queue.put_nowait(job)
        return jobs

    def delete_session(self, session_id) -> str:
        """Delete a session file (and its scratch folders).

        Returns the id of the session that is current afterwards; a fresh one
        is created when the deleted session was the last one.
        """
        if session_id == self.session_id:
            self.db.close()  # release the file before deleting it
        self._delete_session_files(session_id)
        was_current = self.session_store.remove(session_id)
        if was_current:
            remaining = self.session_store.list()
            info = remaining[0] if remaining else self.session_store.create()
            self._open_session_db(info.id)
        return self.session_id

    def delete_all_sessions(self) -> str:
        """Remove every session; open a brand-new empty one."""
        self.db.close()
        for info in self.session_store.list():
            self._delete_session_files(info.id)
        self.session_store.clear()
        info = self.session_store.create()
        self._open_session_db(info.id)
        return info.id

    def _delete_session_files(self, session_id):
        """Delete one session's scratch folders and its database file."""
        db_path = session_db_path(session_id)
        paths: set[Path] = set()
        if db_path.exists():
            try:
                db = JobManager(db_path)
                try:
                    paths = {job.save_path for job in db.all_jobs()}
                finally:
                    db.close()
            except sqlite3.Error as exc:
                logger.warning(f"Could not read session {session_id} before delete: {exc}")
        for path in paths:
            remove_session_temp_dirs(path, session_id)
        delete_session_files(session_id)
