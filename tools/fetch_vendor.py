#!/usr/bin/env python3
"""Download the external binaries the app bundles: FFmpeg, Deno and Tor.

- **FFmpeg** — yt-dlp needs it to merge video+audio and to convert MP3.
- **Deno** — the JavaScript runtime yt-dlp uses to solve YouTube's JS
  challenges (without it, YouTube extraction is degraded / misses formats).
- **Tor** — the SOCKS proxy the app starts automatically when the Proxy menu
  is on.

They land in `vendor/<tool>/` (gitignored); `scripts/build.py` picks them up so
a release only has to be extracted and run. Standard library only.

    python tools/fetch_vendor.py
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"

# Which runtime asks for which file names.
WANTED = {
    "ffmpeg": {"ffmpeg", "ffprobe"},
    "deno": {"deno"},
}

# Tor Expert Bundles live under a versioned folder on dist.torproject.org.
TORBROWSER_INDEX = "https://dist.torproject.org/torbrowser/"
TOR_PLATFORM = {
    "linux": "linux-x86_64",
    "win32": "windows-x86_64",
}
# GitHub runners are sometimes served a challenge page instead of the index.
# This stable bundle keeps the build working when that happens.
TOR_FALLBACK_VERSIONS = ("16.0.1",)

# Some mirrors (including dist.torproject.org) reject the default urllib UA.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# BtbN ships FFmpeg (ffmpeg+ffprobe under bin/); Deno ships a single binary.
SOURCES = {
    "linux": {
        "ffmpeg": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-linux64-gpl.tar.xz",
        "deno": "https://github.com/denoland/deno/releases/latest/download/"
        "deno-x86_64-unknown-linux-gnu.zip",
    },
    "win32": {
        "ffmpeg": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-win64-gpl.zip",
        "deno": "https://github.com/denoland/deno/releases/latest/download/"
        "deno-x86_64-pc-windows-msvc.zip",
    },
}


def platform_key() -> str:
    if os.name == "nt":
        return "win32"
    if sys.platform.startswith("linux"):
        return "linux"
    raise SystemExit("No prebuilt binaries are provided for this platform.")


def download(url: str, dest: Path) -> None:
    print(f"Downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)


def extract(archive: Path, into: Path) -> None:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(into)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(into)


def fetch(tool: str, url: str, exe: str) -> None:
    if url.endswith(".zip"):
        suffix = ".zip"
    elif url.endswith(".tar.gz"):
        suffix = ".tar.gz"
    else:
        suffix = ".tar.xz"
    names = {name + exe for name in WANTED[tool]}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / f"{tool}{suffix}"
        download(url, archive)

        print("Extracting ...")
        unpacked = tmp_path / "unpacked"
        extract(archive, unpacked)

        found = [
            path
            for path in unpacked.rglob("*")
            if path.is_file() and path.name in names
        ]
        if not found:
            raise SystemExit(f"{tool}: expected binaries not found in the archive.")

        dest = VENDOR / tool
        dest.mkdir(parents=True, exist_ok=True)
        for path in found:
            target = dest / path.name
            shutil.copy2(path, target)
            target.chmod(
                target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
            print(f"  {target.relative_to(ROOT)}")


def already_fetched(tool: str, exe: str) -> bool:
    dest = VENDOR / tool
    return all((dest / f"{name}{exe}").is_file() for name in WANTED[tool])


def latest_tor_version() -> str:
    """Newest stable Tor Browser version listed in the official index."""
    print(f"Looking up the current Tor version at {TORBROWSER_INDEX}")
    request = urllib.request.Request(
        TORBROWSER_INDEX, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        listing = response.read().decode("utf-8", "replace")
    matches = re.findall(
        r"""href=["'](\d+)\.(\d+)(?:\.(\d+))?/["']""", listing, re.I
    )
    if not matches:
        raise RuntimeError("no stable version found in the index")
    parsed = []
    for major, minor, patch in matches:
        version = f"{major}.{minor}" + (f".{patch}" if patch else "")
        parsed.append((int(major), int(minor), int(patch or 0), version))
    return max(parsed)[3]


def _url_exists(url: str) -> bool:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT}, method="HEAD"
    )
    try:
        with urllib.request.urlopen(request, timeout=30):
            return True
    except Exception:
        return False


def _fetch_tor_version(version: str, platform: str, exe: str) -> None:
    archive_name = f"tor-expert-bundle-{platform}-{version}.tar.gz"
    url = f"https://dist.torproject.org/torbrowser/{version}/{archive_name}"
    # Tor Browser patch releases can appear in the index before their Expert
    # Bundle does (e.g. 16.0.2); skip versions without a published bundle.
    if not _url_exists(url):
        raise RuntimeError("Expert Bundle not published for this version")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / archive_name
        download(url, archive)

        print("Extracting ...")
        unpacked = tmp_path / "unpacked"
        extract(archive, unpacked)

        binaries = [path for path in unpacked.rglob(f"tor{exe}") if path.is_file()]
        if not binaries:
            raise RuntimeError("expected binary not found in the archive")
        source = binaries[0].parent

        dest = VENDOR / "tor"
        dest.mkdir(parents=True, exist_ok=True)

        copied = [path for path in source.iterdir() if path.is_file()]
        for name in ("geoip", "geoip6"):
            data_file = unpacked / "data" / name
            if data_file.is_file():
                copied.append(data_file)

        for path in copied:
            target = dest / path.name
            shutil.copy2(path, target)
            target.chmod(
                target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
            print(f"  {target.relative_to(ROOT)}")


def fetch_tor(platform: str, exe: str) -> None:
    versions = []
    try:
        latest = latest_tor_version()
        versions.append(latest)
    except Exception as exc:  # noqa: BLE001 - fall back to known bundles
        print(f"tor: version lookup failed ({exc}); trying a fallback")
    versions += [v for v in TOR_FALLBACK_VERSIONS if v not in versions]

    last_error = None
    for version in versions:
        try:
            print(f"tor: trying Expert Bundle {version}")
            _fetch_tor_version(version, platform, exe)
            return
        except Exception as exc:  # noqa: BLE001 - try the next known version
            last_error = exc
            print(f"tor: version {version} failed: {type(exc).__name__}: {exc}")

    raise SystemExit(f"tor: could not fetch an Expert Bundle ({last_error})")


def main() -> int:
    key = platform_key()
    exe = ".exe" if key == "win32" else ""
    for tool, url in SOURCES[key].items():
        if already_fetched(tool, exe):
            print(f"{tool}: already present, skipping")
            continue
        fetch(tool, url, exe)

    if (VENDOR / "tor" / f"tor{exe}").is_file():
        print("tor: already present, skipping")
    else:
        fetch_tor(TOR_PLATFORM[key], exe)

    print(f"\nVendor binaries ready in {VENDOR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
