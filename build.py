#!/usr/bin/env python3
"""Build a standalone Video Download Tool executable with PyInstaller.

Works on both Windows and Linux. Run it with the project's virtual environment
Python so PyInstaller builds against the app's dependencies:

    .venv/bin/python build.py           # Linux / macOS
    .venv\\Scripts\\python build.py        # Windows
    python build.py --onefile           # single-file executable
    python build.py --name MyApp        # custom name
    python build.py --console           # keep a console window on Windows

Install the dependencies (declared in pyproject.toml) first — `./setup.sh` on
Linux/macOS or `setup.ps1` on Windows. PyInstaller is installed into the
*current* environment on first use, but only when that environment is a
virtualenv: build tools are never installed into the system Python.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

APP_NAME = "VideoDownloadTool"

# Libraries that must come from the host, not from the bundle. The Qt/GTK/
# Wayland/X11 libraries are tied to the target system's driver stack, so a copy
# built on another distribution can break startup; PyInstaller bundles them by
# default and they are stripped back out after the build.
_UNBUNDLED_LIBS = (
    "libxkbcommon",
    "libwayland-client",
    "libwayland-cursor",
    "libwayland-egl",
    "libX11",
    "libX11-xcb",
    "libxcb",
)

# The GUI stylesheets reference these indicator icons by absolute path, so they
# must be present inside the bundle or the checkboxes/radio buttons would
# silently render without their custom icons.
_REQUIRED_ASSETS = (
    "checkbox-checked.svg",
    "checkbox-unchecked.svg",
    "radio-checked.svg",
    "radio-unchecked.svg",
)


def remove_unbundled_libs(dist_dir: Path) -> list[str]:
    """Drop libraries that must come from the host; returns the names removed."""
    internal = dist_dir / "_internal"
    if not internal.is_dir():
        return []

    removed = []
    for library in sorted(internal.glob("lib*.so*")):
        if library.name.startswith(_UNBUNDLED_LIBS):
            library.unlink()
            removed.append(library.name)
    return removed


def verify_no_unbundled_libs(dist_dir: Path) -> None:
    """Fail the build if a host-only GUI library is still inside the bundle."""
    internal = dist_dir / "_internal"
    if not internal.is_dir():
        return

    leftover = [
        library.name
        for library in sorted(internal.glob("lib*.so*"))
        if library.name.startswith(_UNBUNDLED_LIBS)
    ]
    if leftover:
        raise SystemExit(
            "System GUI libraries are still bundled:\n  " + "\n  ".join(leftover)
        )


def verify_assets(dist_dir: Path) -> None:
    """Fail the build if a required indicator icon is missing from the bundle."""
    asset_dir = dist_dir / "_internal" / "assets"
    missing = [name for name in _REQUIRED_ASSETS if not (asset_dir / name).is_file()]
    if missing:
        raise SystemExit("Missing bundled asset(s): " + ", ".join(missing))


def in_virtualenv() -> bool:
    """True when this interpreter belongs to a virtual environment."""
    if os.environ.get("VIRTUAL_ENV"):
        return True
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def pyinstaller_available() -> bool:
    return importlib.util.find_spec("PyInstaller") is not None


def _venv_executable() -> str:
    if sys.platform == "win32":
        return r".venv\Scripts\python.exe"
    return "./.venv/bin/python"


def _venv_hint() -> str:
    lines = [
        "PyInstaller is not available in the Python running this script:",
        f"    {sys.executable}",
        "",
        "Build inside the project's virtual environment — do not install build",
        "tools into the system Python.",
        "",
    ]
    if (ROOT / ".venv").is_dir():
        lines += [
            "The project venv exists, so run the build with it directly:",
            f"    {_venv_executable()} build.py",
            "",
        ]
    lines += ["or activate the virtual environment first:"]
    if sys.platform == "win32":
        lines.append(r"    .venv\Scripts\activate   then   python build.py")
    else:
        lines.append("    source .venv/bin/activate   then   python build.py")
    return "\n".join(lines)


def ensure_pyinstaller() -> None:
    """Make sure PyInstaller is usable, installing it only into a virtualenv."""
    if pyinstaller_available():
        return

    if not in_virtualenv():
        print(_venv_hint(), file=sys.stderr)
        raise SystemExit(1)

    print("PyInstaller not found — installing it into the current environment ...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    except subprocess.CalledProcessError as exc:
        print(
            f"\nCould not install PyInstaller (pip exited with {exc.returncode}).",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def seed_config() -> None:
    """Write data/config.json from the app's defaults when it is missing.

    data/config.json is runtime state (gitignored), so a fresh checkout has no
    copy of it. Seed one from the app's own defaults so the build can still
    bundle a starter config — the app copies it next to the executable on first
    run.
    """
    config_path = ROOT / "data" / "config.json"
    if config_path.exists():
        return

    sys.path.insert(0, str(ROOT))
    from core.utils import DEFAULT_CONFIG

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(DEFAULT_CONFIG, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Seeded {config_path.relative_to(ROOT)} from defaults")


def _entry_point(dist_dir: Path, name: str, onefile: bool) -> Path:
    exe_name = f"{name}.exe" if sys.platform == "win32" else name
    return (ROOT / "dist" / exe_name) if onefile else (dist_dir / exe_name)


def build(name: str, onefile: bool, console: bool) -> int:
    ensure_pyinstaller()
    seed_config()

    dist_dir = ROOT / "dist" / name

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        name,
        "--paths",
        str(ROOT),
        "--onefile" if onefile else "--onedir",
        "--hidden-import",
        "qasync",
        "--hidden-import",
        "yt_dlp",
    ]

    if sys.platform == "win32" and not console:
        command.append("--windowed")
        icon = ROOT / "assets" / "icon.ico"
        if icon.exists():
            command += ["--icon", str(icon)]

    # The app resolves its resources relative to the bundle root
    # (core.utils.get_resource_path), so each one keeps its bundled path.
    assets = ROOT / "assets"
    if assets.is_dir():
        command += ["--add-data", f"{assets}{os.pathsep}assets"]

    config = ROOT / "data" / "config.json"
    if config.is_file():
        command += ["--add-data", f"{config}{os.pathsep}."]

    # version.json is read at runtime (core/updater/version.py).
    version_file = ROOT / "version.json"
    if version_file.is_file():
        command += ["--add-data", f"{version_file}{os.pathsep}."]

    command.append(str(ROOT / "run.py"))

    print("Running:", " ".join(command))
    exit_code = subprocess.call(command, cwd=str(ROOT))
    if exit_code != 0:
        return exit_code

    if not onefile:
        if sys.platform != "win32":
            for library in remove_unbundled_libs(dist_dir):
                print(f"Removed bundled {library} (must come from the host)")
            verify_no_unbundled_libs(dist_dir)
        verify_assets(dist_dir)

    entry_point = _entry_point(dist_dir, name, onefile)
    if not entry_point.is_file():
        print(f"\nBuild failed: {entry_point} was not created.", file=sys.stderr)
        return 1

    # Temporary PyInstaller files.
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    (ROOT / "run.spec").unlink(missing_ok=True)

    return 0


def _size(dist_dir: Path) -> int:
    if dist_dir.is_file():
        return dist_dir.stat().st_size
    return sum(path.stat().st_size for path in dist_dir.rglob("*") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a standalone Video Download Tool executable with PyInstaller."
    )
    parser.add_argument(
        "--onefile", action="store_true", help="build a single-file executable"
    )
    parser.add_argument("--name", default=APP_NAME, help="executable name")
    parser.add_argument(
        "--console",
        action="store_true",
        help="keep a console window on Windows (default: windowed)",
    )
    args = parser.parse_args()

    exit_code = build(args.name, args.onefile, args.console)
    if exit_code == 0:
        output = _entry_point(ROOT / "dist" / args.name, args.name, args.onefile)
        size_mb = _size(output) / (1024 * 1024)
        print(f"\nBuild finished ({size_mb:.2f} MB). Output is in: {ROOT / 'dist'}")
    else:
        print(f"\nBuild failed with exit code {exit_code}.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
