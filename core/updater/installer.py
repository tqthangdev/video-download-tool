"""
core/updater/installer.py

Prepares an update — download, verify, extract, validate — and then hands the
actual replacement to the standalone updater process. The running app never
overwrites itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable, Optional

from core.logger import logger
from core.utils import BASE_DIR
from core.updater import UPDATE_DIR_NAME
from core.updater.checker import UpdateInfo
from core.updater.downloader import DownloadError, download_asset
from core.updater.verifier import validate_package, verify_download


class InstallError(Exception):
    """The update could not be prepared."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        # Stable code for messages the UI translates itself (see i18n).
        self.code = code


def staging_dir(version: str) -> Path:
    return BASE_DIR / UPDATE_DIR_NAME / version.strip().lstrip("vV")


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def cleanup_staging() -> None:
    """Remove the staging area left by a finished update (best-effort).

    A staged build can be locked on Windows while the updater process that
    launched from it is still exiting, so a leftover folder is removed on the
    following launch instead.
    """
    _cleanup(BASE_DIR / UPDATE_DIR_NAME)


def prepare_update(
    info: UpdateInfo,
    progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> Path:
    """Download, verify, extract and validate the release package.

    Returns the folder holding the new application (the updater's --source).
    Any failure leaves the current installation untouched and removes the
    partial download.
    """
    asset = info.asset_for_platform()
    if asset is None:
        raise InstallError("no package for this platform", code="no_package")

    stage = staging_dir(info.latest)
    stage.mkdir(parents=True, exist_ok=True)

    zip_path = stage / asset.name
    try:
        download_asset(asset.url, zip_path, progress=progress, cancel=cancel)
    except DownloadError:
        _cleanup(stage)
        raise

    if not verify_download(zip_path, asset):
        _cleanup(stage)
        raise InstallError("checksum mismatch")

    extracted = stage / "extracted"
    _cleanup(extracted)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            broken = archive.testzip()
            if broken:
                raise InstallError(f"corrupt archive ({broken})")
            archive.extractall(extracted)
    except zipfile.BadZipFile as e:
        _cleanup(stage)
        raise InstallError("invalid zip archive") from e
    except InstallError:
        _cleanup(stage)
        raise
    except OSError as e:
        _cleanup(stage)
        raise InstallError(str(e)) from e

    app_root = validate_package(extracted, info.latest)
    if app_root is None:
        _cleanup(stage)
        raise InstallError("invalid update package")

    logger.info(f"[updater] staged {info.latest} at {app_root}")
    return app_root


def _updater_launcher(source: Path):
    """Command that runs the updater code.

    A packaged update carries its own executable: running *that* (from the
    staging folder) leaves the installed executable unlocked, so it can be
    replaced on Windows. A source checkout has no executable, so the current
    interpreter runs the entry script instead.
    """
    exe_name = "VideoDownloadTool.exe" if os.name == "nt" else "VideoDownloadTool"
    packaged = source / exe_name
    if packaged.is_file():
        return [str(packaged)]

    return [sys.executable, str(Path(sys.argv[0]).resolve())]


def spawn_updater(source: Path, version: str) -> None:
    """Start the updater process that replaces this installation.

    The app exits right after this; the updater waits for that, so the swap
    never happens while the old build is still running.
    """
    args = _updater_launcher(source) + [
        "--update",
        "--source", str(source),
        "--target", str(BASE_DIR),
        "--pid", str(os.getpid()),
        "--version", version,
    ]

    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(args, **kwargs)
    logger.info(f"[updater] started updater process for {version}")
