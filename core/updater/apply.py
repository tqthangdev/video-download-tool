"""
core/updater/apply.py

The standalone updater process. It is started with `--update`, waits for the
old app to exit, backs up the installed files, copies the staged build over
them, verifies the result and relaunches the app. If anything fails it puts the
old files back, so a failed update never leaves a broken installation.

It runs from the staged copy (not the installed one), so the installed
executable is never overwritten while it is still running.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from core.updater.verifier import verify_installation

# Never replaced by an update: user data and runtime state live here.
SKIP_ENTRIES = {"data", "logs", ".temp", ".update"}

EXE_NAME = "VideoDownloadTool.exe" if os.name == "nt" else "VideoDownloadTool"

# Where the old files are moved while the new ones are copied in.
BACKUP_DIR_NAME = "backup"

WAIT_TIMEOUT = 120
WAIT_INTERVAL = 0.3
# Give the OS a moment to release file handles after the process exits.
SETTLE_SECONDS = 0.5


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_exit(pid: int, timeout: float = WAIT_TIMEOUT) -> bool:
    """Wait until `pid` is gone; False when it is still alive at timeout."""
    if pid <= 0:
        return True

    deadline = time.monotonic() + timeout
    while _pid_alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(WAIT_INTERVAL)

    time.sleep(SETTLE_SECONDS)
    return True


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


def _replace(source: Path, target: Path, backup_root: Path, moved: list) -> None:
    """Copy every staged entry over `target`, moving the old one to `backup_root`.

    Appends the (dest, backup) pairs to `moved` as it goes, so a failure part
    way through can still be undone by the caller.
    """
    for entry in sorted(source.iterdir()):
        if entry.name in SKIP_ENTRIES:
            continue

        dest = target / entry.name
        backup = backup_root / entry.name

        if dest.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            _remove(backup)
            dest.rename(backup)

        # Recorded before the copy so a partial copy is still rolled back.
        moved.append((dest, backup))

        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)


def _rollback(moved) -> None:
    for dest, backup in reversed(moved):
        _remove(dest)
        if backup.exists():
            backup.rename(dest)


def apply_package(source: Path, target: Path, version: str = "") -> bool:
    """Install the staged build over `target`, rolling back on any failure.

    Returns True only when the installed app passes verification.
    """
    backup_root = target / ".update" / BACKUP_DIR_NAME
    moved = []
    try:
        _replace(source, target, backup_root, moved)
        if not verify_installation(target, version):
            raise RuntimeError("installed package failed verification")
    except Exception:
        _rollback(moved)
        return False

    shutil.rmtree(backup_root, ignore_errors=True)
    return True


def _launch(target: Path) -> None:
    packaged = target / EXE_NAME
    if packaged.is_file():
        command = [str(packaged)]
    else:
        command = [sys.executable, str(target / "run.py")]

    kwargs = {"cwd": str(target)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(command, **kwargs)


def _staging_root(source: Path) -> Path:
    """The `.update/<version>` folder a staged app root belongs to."""
    if source.parent.name == "extracted":
        return source.parent.parent
    return source


def run(source: Path, target: Path, pid: int, version: str = "") -> int:
    """Full update: wait for the app to exit, swap the files, relaunch."""
    if not wait_for_exit(pid):
        return 1
    if not source.is_dir() or not target.is_dir():
        return 1
    # Validate the staged build again, in case the staging folder changed
    # between preparing it and applying it.
    if not verify_installation(source, version):
        return 1

    if not apply_package(source, target, version):
        return 1

    _launch(target)
    # Best-effort: on Windows the updater is the staged executable and cannot
    # delete itself; the app clears whatever is left on its next startup.
    shutil.rmtree(_staging_root(source), ignore_errors=True)
    return 0


def run_from_cli(argv) -> int:
    parser = argparse.ArgumentParser(prog="VideoDownloadTool --update", add_help=False)
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--version", default="")

    options, _ = parser.parse_known_args(argv)
    return run(
        Path(options.source), Path(options.target), options.pid, options.version
    )
