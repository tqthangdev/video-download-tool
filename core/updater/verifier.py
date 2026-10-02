"""
core/updater/verifier.py

Checks a downloaded package (SHA-256) and validates the extracted package
before the updater is allowed to touch the running app.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from core.updater.checker import ReleaseAsset

CHUNK_BYTES = 1024 * 1024

# Bundled data folder of a PyInstaller onedir build.
INTERNAL_DIR = "_internal"

# What a valid package must contain, per platform.
ENTRY_POINTS = ("VideoDownloadTool.exe", "VideoDownloadTool", "run.py")
VERSION_FILE = "version.json"


def sha256_of(path: Path) -> str:
    """Hex SHA-256 of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_sha256(asset: ReleaseAsset) -> str:
    """The hex digest the release published for this asset ("" when it has none)."""
    digest = (asset.digest or "").strip().lower()
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    return ""


def verify_download(path: Path, asset: ReleaseAsset) -> bool:
    """True when the file matches the published digest.

    Releases without a digest are accepted here: the ZIP is still integrity
    checked while extracting, and the package is validated afterwards.
    """
    want = expected_sha256(asset)
    if not want:
        return True
    return sha256_of(path) == want


def version_file(root: Path) -> Optional[Path]:
    """The package's version.json: next to the executable, or inside the bundle.

    A PyInstaller onedir build keeps bundled data (including version.json) in
    the `_internal` folder, while a source checkout has it at the top level.
    """
    for candidate in (root / VERSION_FILE, root / INTERNAL_DIR / VERSION_FILE):
        if candidate.is_file():
            return candidate
    return None


def _package_version(root: Path) -> str:
    path = version_file(root)
    if path is None:
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return ""
    return str(data.get("version") or "").strip().lstrip("vV")


def has_entry_point(root: Path) -> bool:
    """True when `root` holds something the updater can launch.

    Must be a file: release zips carry a top-level *folder* named after the
    executable, which is not an install by itself.
    """
    return any((root / name).is_file() for name in ENTRY_POINTS)


def find_app_root(extracted: Path) -> Optional[Path]:
    """The folder inside an extracted package that holds the application.

    Release zips carry a single top-level folder (e.g. ComicDownloadTool/), so
    look one level down when the entry point is not at the top.
    """
    if not extracted.is_dir():
        return None
    if has_entry_point(extracted):
        return extracted

    for child in sorted(extracted.iterdir()):
        if child.is_dir() and has_entry_point(child):
            return child

    return None


def validate_package(extracted: Path, version: str) -> Optional[Path]:
    """Validate an extracted package; returns its app root, or None when invalid.

    A valid package has an entry point and a version.json whose version matches
    the release we downloaded — so a half-extracted or wrong archive is refused
    before anything is replaced.
    """
    root = find_app_root(extracted)
    if root is None or version_file(root) is None:
        return None

    want = (version or "").strip().lstrip("vV")
    if want and _package_version(root) != want:
        return None

    return root


def verify_installation(root: Path, version: str = "") -> bool:
    """Check an installed app after the swap: entry point + matching version.

    Used by the updater, so a broken copy is detected before the old build is
    discarded instead of leaving the user with a half-installed app.
    """
    if not has_entry_point(root):
        return False
    want = (version or "").strip().lstrip("vV")
    return not want or _package_version(root) == want
