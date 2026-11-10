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
    with urllib.request.urlopen(url, timeout=300) as response, open(dest, "wb") as out:
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
    with urllib.request.urlopen(TORBROWSER_INDEX, timeout=60) as response:
        listing = response.read().decode("utf-8", "replace")
    versions = re.findall(r'href="(\d+)\.(\d+)/"', listing)
    if not versions:
        raise SystemExit("tor: could not find a stable version in the index.")
    major, minor = max((int(a), int(b)) for a, b in versions)
    return f"{major}.{minor}"


def fetch_tor(platform: str, exe: str) -> None:
    version = latest_tor_version()
    archive_name = f"tor-expert-bundle-{platform}-{version}.tar.gz"
    url = f"https://dist.torproject.org/torbrowser/{version}/{archive_name}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / archive_name
        download(url, archive)

        print("Extracting ...")
        unpacked = tmp_path / "unpacked"
        extract(archive, unpacked)

        binaries = [path for path in unpacked.rglob(f"tor{exe}") if path.is_file()]
        if not binaries:
            raise SystemExit("tor: expected binary not found in the archive.")
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
