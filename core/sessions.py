"""Session registry: one SQLite database per session (feedback.md #2).

A session is a self-contained queue stored in its own file
(``data/jobs_<id>.db``), so two workloads never share rows or collide on the
job identity. The registry (``data/sessions.json``) maps each session's stable
random id to a display name and remembers which session is current.

Renaming only edits the registry -- the file name never changes, so open
connections and download scratch folders stay valid.
"""

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.logger import logger
from core.utils import DATA_DIR

REGISTRY_PATH = DATA_DIR / "sessions.json"
LEGACY_DB_PATH = DATA_DIR / "jobs.db"
SESSION_FILE_PREFIX = "jobs_"
SESSION_FILE_SUFFIX = ".db"
# Legacy jobs that were never saved into a session get this name.
LEGACY_UNSORTED_LABEL = "Imported"
# Longest session name accepted (kept short so dialog rows stay tidy).
SESSION_NAME_MAX_LENGTH = 12


def clean_session_name(name: str) -> str:
    return (name or "").strip()[:SESSION_NAME_MAX_LENGTH]


def new_session_id() -> str:
    """A short random id: the session's stable key and default name."""
    return secrets.token_hex(4)


def session_db_path(session_id: str) -> Path:
    return DATA_DIR / f"{SESSION_FILE_PREFIX}{session_id}{SESSION_FILE_SUFFIX}"


def delete_session_files(session_id: str) -> None:
    """Remove a session's database plus any SQLite sidecar files."""
    base = session_db_path(session_id)
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            Path(f"{base}{suffix}").unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"[sessions] could not delete {base.name}{suffix}: {exc}")


@dataclass
class SessionInfo:
    """One session: a name for a ``jobs_<id>.db`` file."""

    id: str
    name: str
    created_at: str | None = None


class SessionStore:
    """Reads/writes the session registry and migrates the legacy database."""

    def __init__(self, registry_path: Path = REGISTRY_PATH):
        self.path = Path(registry_path)
        self._sessions: list[SessionInfo] = []
        self.current: str | None = None
        self._load()
        self._migrate_legacy()

    # ------------------------------------------------------------------
    # REGISTRY
    # ------------------------------------------------------------------

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error(f"[sessions] could not read {self.path.name}: {exc}")
            return

        for entry in data.get("sessions") or []:
            session_id = str(entry.get("id") or "")
            if session_id:
                self._sessions.append(
                    SessionInfo(
                        id=session_id,
                        name=str(entry.get("name") or session_id),
                        created_at=entry.get("created_at"),
                    )
                )
        current = data.get("current")
        self.current = str(current) if current else None
        self._prune_missing()

    def _prune_missing(self):
        """Drop entries whose database file disappeared (removed by hand)."""
        self._sessions = [s for s in self._sessions if session_db_path(s.id).exists()]
        ids = {s.id for s in self._sessions}
        if self.current not in ids:
            self.current = self._sessions[0].id if self._sessions else None

    def save(self):
        payload = {
            "current": self.current,
            "sessions": [
                {"id": s.id, "name": s.name, "created_at": s.created_at}
                for s in self._sessions
            ],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error(f"[sessions] could not write {self.path.name}: {exc}")

    # ------------------------------------------------------------------
    # QUERIES
    # ------------------------------------------------------------------

    def list(self) -> list[SessionInfo]:
        return list(self._sessions)

    def get(self, session_id) -> SessionInfo | None:
        return next((s for s in self._sessions if s.id == session_id), None)

    # ------------------------------------------------------------------
    # MUTATIONS
    # ------------------------------------------------------------------

    def create(self, name: str | None = None) -> SessionInfo:
        """Register a new session and make it current (file is opened later)."""
        session_id = self._unique_id()
        info = SessionInfo(
            id=session_id,
            name=clean_session_name(name) or session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._sessions.append(info)
        self.current = info.id
        self.save()
        return info

    def rename(self, session_id, name: str):
        info = self.get(session_id)
        new_name = clean_session_name(name)
        if info and new_name and new_name != info.name:
            info.name = new_name
            self.save()

    def set_current(self, session_id):
        if self.get(session_id):
            self.current = session_id
            self.save()

    def remove(self, session_id) -> bool:
        """Drop a registry entry; returns True when it was the current one."""
        if self.get(session_id) is None:
            return False
        self._sessions = [s for s in self._sessions if s.id != session_id]
        was_current = self.current == session_id
        if was_current:
            self.current = self._sessions[0].id if self._sessions else None
        self.save()
        return was_current

    def clear(self):
        self._sessions = []
        self.current = None
        self.save()

    def ensure_current(self) -> SessionInfo:
        """The current session, creating one when the registry is empty."""
        if self.current:
            info = self.get(self.current)
            if info is not None:
                return info
        if self._sessions:
            self.current = self._sessions[0].id
            self.save()
            return self._sessions[0]
        return self.create()

    def _unique_id(self) -> str:
        session_id = new_session_id()
        while self.get(session_id) or session_db_path(session_id).exists():
            session_id = new_session_id()
        return session_id

    # ------------------------------------------------------------------
    # LEGACY MIGRATION
    # ------------------------------------------------------------------

    def _migrate_legacy(self):
        """Split the pre-session ``jobs.db`` into one file per session."""
        if self._sessions or not LEGACY_DB_PATH.exists():
            return

        try:
            legacy = self._read_legacy()
        except sqlite3.Error as exc:
            logger.error(f"[sessions] legacy migration failed: {exc}")
            return
        if legacy is None:
            return

        groups, order, names = legacy
        from core.job_manager import JobManager

        created: list[SessionInfo] = []
        for legacy_id in order:
            name = names.get(legacy_id)
            if legacy_id == 0:
                name = name or LEGACY_UNSORTED_LABEL
            info = self.create(name=name)
            db = JobManager(session_db_path(info.id))
            for job in groups.get(legacy_id, []):
                db.add(job)
            db.close()
            created.append(info)

        if not created:
            return

        # Never reopen the legacy file: keep it as a backup.
        try:
            LEGACY_DB_PATH.rename(LEGACY_DB_PATH.with_name("jobs.db.bak"))
        except OSError as exc:
            logger.warning(f"[sessions] could not rename legacy jobs.db: {exc}")

        self.current = created[-1].id
        self.save()
        logger.info(
            f"[sessions] migrated legacy jobs.db into {len(created)} session file(s)"
        )

    def _read_legacy(self):
        """Read the legacy db into ({legacy session id: [Job]}, order, names)."""
        from core.job_manager import JobManager

        conn = sqlite3.connect(str(LEGACY_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "jobs" not in tables:
                return None

            cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
            has_session = "session_id" in cols
            job_rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()

            names: dict[int, str] = {}
            if "sessions" in tables:
                for row in conn.execute("SELECT id, name FROM sessions"):
                    names[int(row["id"])] = str(row["name"] or "")
        finally:
            conn.close()

        groups: dict[int, list] = {}
        order: list[int] = []
        for row in job_rows:
            legacy_id = int(row["session_id"]) if has_session and row["session_id"] is not None else 0
            if legacy_id not in groups:
                groups[legacy_id] = []
                order.append(legacy_id)
            groups[legacy_id].append(JobManager._row_to_job(row))

        if not order:
            return {}, [0], names
        return groups, order, names
