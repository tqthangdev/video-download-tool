#!/usr/bin/env bash

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

VENV="$PROJECT_DIR/.venv"
PYTHON="$VENV/bin/python"

echo "=========================================="
echo " VideoDownloadTool - Linux ONEDIR Build"
echo "=========================================="

# ==========================================
# VENV
# ==========================================

if [ ! -x "$PYTHON" ]; then
    echo "=== Creating venv ==="
    python3 -m venv "$VENV"
fi

echo
echo "=== Python ==="
"$PYTHON" --version

# ==========================================
# DEPENDENCIES
# ==========================================

echo
echo "=== Installing dependencies ==="

"$PYTHON" -m pip install -r requirements.txt
"$PYTHON" -m pip install pyinstaller

# ==========================================
# CONFIG TEMPLATE
# ==========================================

# data/config.json is runtime state (gitignored), so a fresh checkout has no
# copy of it. Seed one from the app's own defaults so the build can still bundle
# a starter config — the app copies it next to the executable on first run.
if [ ! -f "$PROJECT_DIR/data/config.json" ]; then
    echo
    echo "=== Seeding data/config.json from defaults ==="

    "$PYTHON" - <<'PY'
import json
import pathlib

from core.utils import DEFAULT_CONFIG

path = pathlib.Path("data/config.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    json.dumps(DEFAULT_CONFIG, indent=4, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print("wrote", path)
PY
fi

# ==========================================
# VERIFY
# ==========================================

echo
echo "=== Verify project ==="

test -f run.py
test -f data/config.json
test -f assets/icon.png
test -f version.json

# ==========================================
# CLEAN OLD BUILD
# ==========================================

echo
echo "=== Cleaning previous build ==="

rm -rf \
    "$PROJECT_DIR/build" \
    "$PROJECT_DIR/dist" \
    "$PROJECT_DIR/run.spec"

# ==========================================
# CREATE SPEC
# ==========================================

echo
echo "=== Creating PyInstaller spec ==="

cat > run.spec <<'EOF'
from pathlib import Path

block_cipher = None

BASE_DIR = Path(SPECPATH)

datas = [
    (
        str(BASE_DIR / "assets"),
        "assets",
    ),
    (
        str(BASE_DIR / "data" / "config.json"),
        ".",
    ),
    (
        str(BASE_DIR / "version.json"),
        ".",
    ),
]

# ==========================================
# ANALYSIS
# ==========================================

a = Analysis(
    [str(BASE_DIR / "run.py")],

    pathex=[
        str(BASE_DIR),
    ],

    binaries=[],

    datas=datas,

    hiddenimports=[
        "qasync",
        "yt_dlp",
    ],

    hookspath=[],
    hooksconfig=[],
    runtime_hooks=[],

    # Do not bundle system GUI libraries.
    # Linux Qt/GTK/Wayland/X11 libraries must
    # come from the target system.
    excludes=[
        "libxkbcommon",
        "libwayland-client",
        "libwayland-cursor",
        "libwayland-egl",
        "libX11",
        "libX11-xcb",
        "libxcb",
    ],

    win_no_prefer_redirects=False,
    win_private_assemblies=False,

    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,

    exclude_binaries=True,

    name="VideoDownloadTool",

    debug=False,
    bootloader_ignore_signals=False,

    strip=False,
    upx=True,

    console=False,

    icon=None,

    disable_windowed_traceback=False,
    argv_emulation=False,

    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,

    strip=False,
    upx=True,

    name="VideoDownloadTool",
)
EOF

# ==========================================
# BUILD ONEDIR
# ==========================================

echo
echo "=== Building ONEDIR ==="

"$PYTHON" -m PyInstaller \
    run.spec \
    --noconfirm \
    --clean

# ==========================================
# REMOVE SYSTEM GUI LIBRARIES
# ==========================================

echo
echo "=== Removing bundled system GUI libraries ==="

INTERNAL_DIR="$PROJECT_DIR/dist/VideoDownloadTool/_internal"

rm -f \
    "$INTERNAL_DIR"/libxkbcommon.so.* \
    "$INTERNAL_DIR"/libwayland-client.so.* \
    "$INTERNAL_DIR"/libwayland-cursor.so.* \
    "$INTERNAL_DIR"/libwayland-egl.so.* \
    "$INTERNAL_DIR"/libX11.so.* \
    "$INTERNAL_DIR"/libX11-xcb.so.* \
    "$INTERNAL_DIR"/libxcb*.so.*

# ==========================================
# VERIFY
# ==========================================

echo
echo "=== Verify build ==="

if [ ! -f "$PROJECT_DIR/dist/VideoDownloadTool/VideoDownloadTool" ]; then
    echo "ERROR: Build failed."
    exit 1
fi

# The GUI stylesheets reference these indicator icons by absolute path, so
# they must be present inside the bundle or the checkboxes/radio buttons
# would silently render without their custom icons.
ASSET_DIR="$INTERNAL_DIR/assets"

for asset in \
    checkbox-checked.svg \
    checkbox-unchecked.svg \
    radio-checked.svg \
    radio-unchecked.svg; do

    if [ ! -f "$ASSET_DIR/$asset" ]; then
        echo "ERROR: Missing bundled asset: assets/$asset"
        exit 1
    fi
done

echo "OK: Indicator SVG assets bundled."

# ==========================================
# VERIFY SYSTEM GUI LIBRARIES
# ==========================================

echo
echo "=== Verify bundled system GUI libraries ==="

if find "$INTERNAL_DIR" -maxdepth 1 -type f \
    \( \
        -name 'libxkbcommon.so.*' \
        -o -name 'libwayland-client.so.*' \
        -o -name 'libwayland-cursor.so.*' \
        -o -name 'libwayland-egl.so.*' \
        -o -name 'libX11.so.*' \
        -o -name 'libX11-xcb.so.*' \
        -o -name 'libxcb*.so.*' \
    \) \
    | grep -q .; then

    echo "ERROR: System GUI libraries are still bundled:"
    find "$INTERNAL_DIR" -maxdepth 1 -type f \
        \( \
            -name 'libxkbcommon.so.*' \
            -o -name 'libwayland-client.so.*' \
            -o -name 'libwayland-cursor.so.*' \
            -o -name 'libwayland-egl.so.*' \
            -o -name 'libX11.so.*' \
            -o -name 'libX11-xcb.so.*' \
            -o -name 'libxcb*.so.*' \
        \)
    exit 1
fi

echo "OK: No system GUI libraries bundled."

# ==========================================
# CLEAN BUILD FILES
# ==========================================

echo
echo "=== Removing temporary files ==="

rm -rf \
    "$PROJECT_DIR/build" \
    "$PROJECT_DIR/run.spec"

# ==========================================
# RESULT
# ==========================================

echo
echo "=========================================="
echo " Build successful"
echo "=========================================="

du -sh "$PROJECT_DIR/dist/VideoDownloadTool"

echo
echo "Output:"
echo "$PROJECT_DIR/dist/VideoDownloadTool/"