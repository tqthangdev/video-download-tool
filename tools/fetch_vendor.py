#!/usr/bin/env python3
"""Download the external binaries the app bundles: FFmpeg and Deno.

- **FFmpeg** — yt-dlp needs it to merge video+audio and to convert MP3.
- **Deno** — the JavaScript runtime yt-dlp uses to solve YouTube's JS
  challenges (without it, YouTube extraction is degraded / misses formats).

They land in `vendor/ffmpeg/` and `vendor/deno/` (gitignored); `scripts/build.py`
picks them up so a release only has to be extracted and run. Standard library
only.

    python tools/fetch_vendor.py
"""

from __future__ import annotations

import os
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
    suffix = ".zip" if url.endswith(".zip") else ".tar.xz"
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


def main() -> int:
    key = platform_key()
    exe = ".exe" if key == "win32" else ""
    for tool, url in SOURCES[key].items():
        if already_fetched(tool, exe):
            print(f"{tool}: already present, skipping")
            continue
        fetch(tool, url, exe)
    print(f"\nVendor binaries ready in {VENDOR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
