$ErrorActionPreference = "Stop"

$PROJECT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $PROJECT_DIR

$VENV = Join-Path $PROJECT_DIR ".venv"
$PYTHON = Join-Path $VENV "Scripts\python.exe"

Write-Host "=========================================="
Write-Host " VideoDownloadTool - Windows ONEDIR Build"
Write-Host "=========================================="

# ==========================================
# VENV
# ==========================================

if (!(Test-Path $PYTHON)) {
    Write-Host "=== Creating venv ==="
    python -m venv $VENV
}

Write-Host ""
Write-Host "=== Python ==="
& $PYTHON --version

# ==========================================
# DEPENDENCIES
# ==========================================

Write-Host ""
Write-Host "=== Installing dependencies ==="

& $PYTHON -m pip install -r requirements.txt
& $PYTHON -m pip install pyinstaller

# ==========================================
# CONFIG TEMPLATE
# ==========================================

# data/config.json is runtime state (gitignored), so a fresh checkout has no
# copy of it. Seed one from the app's own defaults so the build can still bundle
# a starter config — the app copies it next to the executable on first run.
if (!(Test-Path "data\config.json")) {
    Write-Host ""
    Write-Host "=== Seeding data\config.json from defaults ==="

    @'
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
'@ | & $PYTHON -
}

# ==========================================
# VERIFY
# ==========================================

Write-Host ""
Write-Host "=== Verify project ==="

if (!(Test-Path "run.py")) {
    throw "run.py was not found."
}

if (!(Test-Path "data\config.json")) {
    throw "data\config.json was not found."
}

if (!(Test-Path "assets\icon.ico")) {
    throw "assets\icon.ico was not found."
}

# ==========================================
# CLEAN OLD BUILD
# ==========================================

Write-Host ""
Write-Host "=== Cleaning previous build ==="

Remove-Item `
    "build" `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

Remove-Item `
    "dist" `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

Remove-Item `
    "run.spec" `
    -Force `
    -ErrorAction SilentlyContinue

# ==========================================
# CREATE SPEC
# ==========================================

Write-Host ""
Write-Host "=== Creating PyInstaller spec ==="

@"
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
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],

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

    icon=str(BASE_DIR / "assets" / "icon.ico"),

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
"@ | Set-Content -Path "run.spec" -Encoding UTF8

# ==========================================
# BUILD ONEDIR
# ==========================================

Write-Host ""
Write-Host "=== Building ONEDIR ==="

& $PYTHON -m PyInstaller `
    run.spec `
    --noconfirm `
    --clean

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

# ==========================================
# VERIFY
# ==========================================

Write-Host ""
Write-Host "=== Verify build ==="

$EXE = "dist\VideoDownloadTool\VideoDownloadTool.exe"

if (!(Test-Path $EXE)) {
    throw "Build failed: VideoDownloadTool.exe was not created."
}

# The GUI stylesheets reference these indicator icons by absolute path, so
# they must be present inside the bundle or the checkboxes/radio buttons
# would silently render without their custom icons.
$ASSET_DIR = "dist\VideoDownloadTool\_internal\assets"

foreach ($asset in @(
    "checkbox-checked.svg",
    "checkbox-unchecked.svg",
    "radio-checked.svg",
    "radio-unchecked.svg"
)) {
    if (!(Test-Path (Join-Path $ASSET_DIR $asset))) {
        throw "Missing bundled asset: assets\$asset"
    }
}

Write-Host "OK: Indicator SVG assets bundled."

# ==========================================
# CLEAN BUILD FILES
# ==========================================

Write-Host ""
Write-Host "=== Removing temporary files ==="

Remove-Item `
    "build" `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

Remove-Item `
    "run.spec" `
    -Force `
    -ErrorAction SilentlyContinue

# ==========================================
# RESULT
# ==========================================

Write-Host ""
Write-Host "=========================================="
Write-Host " Build successful"
Write-Host "=========================================="

$SIZE = (
    Get-ChildItem `
        "dist\VideoDownloadTool" `
        -Recurse `
        -File |
    Measure-Object Length -Sum
).Sum

Write-Host "Build size: $([math]::Round($SIZE / 1MB, 2)) MB"

Write-Host ""
Write-Host "Output:"
Write-Host "$PROJECT_DIR\dist\VideoDownloadTool\"