"""
core/updater/checker.py

Asks GitHub for this project's latest release and turns the answer into an
`UpdateInfo` the rest of the app can work with.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from core.updater.version import is_newer, read_current_version

REPO = "tqthangdev/video-download-tool"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
REQUEST_TIMEOUT = 15


class UpdateError(Exception):
    """Checking for an update failed (offline, API error, no release...)."""


@dataclass
class ReleaseAsset:
    name: str
    url: str
    size: int = 0
    digest: str = ""  # "sha256:<hex>" when GitHub provides one


@dataclass
class UpdateInfo:
    current: str
    latest: str = ""
    notes: str = ""
    assets: List[ReleaseAsset] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.latest) and is_newer(self.latest, self.current)

    def asset_for_platform(self) -> Optional[ReleaseAsset]:
        """The build for the platform we are running on, if the release has one."""
        wanted = "windows" if os.name == "nt" else "linux"
        for asset in self.assets:
            name = asset.name.lower()
            if wanted in name and name.endswith(".zip"):
                return asset
        return None


def check_for_update() -> UpdateInfo:
    """Read the latest release. Raises UpdateError when it cannot be read."""
    current = read_current_version()

    try:
        resp = requests.get(
            RELEASES_URL,
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/vnd.github+json"},
        )
    except requests.RequestException as e:
        raise UpdateError(type(e).__name__) from e

    if resp.status_code == 404:
        # Also what a private repository returns without credentials.
        raise UpdateError("release not found (private repo or no published release)")
    if resp.status_code != 200:
        raise UpdateError(f"GitHub API returned {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as e:
        raise UpdateError("malformed GitHub response") from e

    return UpdateInfo(
        current=current,
        latest=str(data.get("tag_name") or ""),
        notes=str(data.get("body") or ""),
        assets=[
            ReleaseAsset(
                name=str(a.get("name") or ""),
                url=str(a.get("browser_download_url") or ""),
                size=int(a.get("size") or 0),
                digest=str(a.get("digest") or ""),
            )
            for a in (data.get("assets") or [])
        ],
    )
