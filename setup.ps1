# ============================================================
#  Auto installer for the Video Download Tool (Windows)
#
#  Installs everything needed to run the app, all kept inside
#  the code folder:
#    1. Creates a virtual environment (.venv) — if the system
#       cannot create one it falls back to installing packages
#       into vendor/.
#    2. Installs the dependencies declared in pyproject.toml.
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File setup.ps1
#    powershell -ExecutionPolicy Bypass -File setup.ps1 -NoVenv
# ============================================================
param(
    [switch]$NoVenv
)

$ErrorActionPreference = "Stop"

# Làm việc từ thư mục chứa script này
Set-Location $PSScriptRoot

function Write-Step($title) {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "  $title"
    Write-Host "============================================================"
}

$VENV_DIR = Join-Path $PSScriptRoot ".venv"
$VENDOR_DIR = Join-Path $PSScriptRoot "vendor"
$PYTHON_DIR = Join-Path $PSScriptRoot "python"

# ================= 0. FIND PYTHON =================
Write-Step "Finding Python..."
$PythonExe = $null

# Tìm python trên PATH
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    # python có thể là WindowsApps stub -> gọi thử version
    try {
        $ver = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) { $PythonExe = "python" }
    } catch {}
}
if (-not $PythonExe) {
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        try {
            $ver = & py -3 --version 2>&1
            if ($LASTEXITCODE -eq 0) { $PythonExe = "py -3" }
        } catch {}
    }
}
if ($PythonExe) {
    Write-Host "  Su dung Python: $( & $PythonExe --version )"
}
# Nếu không có Python -> tải bản embeddable dùng thư viện `python` cục bộ
if (-not $PythonExe) {
    if (-not (Test-Path (Join-Path $PYTHON_DIR "python.exe"))) {
        Write-Host "  Khong tim thay Python. Dang tai Python embeddable..."
        New-Item -ItemType Directory -Force -Path $PYTHON_DIR | Out-Null
        $zip = Join-Path $PYTHON_DIR "python-embed.zip"
        $url = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip"
        Invoke-WebRequest -Uri $url -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath $PYTHON_DIR -Force
        Remove-Item $zip -Force

        # Bật 'import site' trong embeddable
        Get-ChildItem -Path $PYTHON_DIR -Filter "python*._pth" | ForEach-Object {
            $content = Get-Content $_.FullName
            $content = $content -replace '#import site', 'import site'
            Set-Content -Path $_.FullName -Value $content
        }

        Write-Host "  Cai dat pip cho Python embeddable..."
        & (Join-Path $PYTHON_DIR "python.exe") -m ensurepip --upgrade
    } else {
        Write-Host "  Su dung Python embeddable tai $PYTHON_DIR"
    }
    $PythonExe = Join-Path $PYTHON_DIR "python.exe"
}

if (Test-Path (Join-Path $PSScriptRoot "pyproject.toml") -eq $false) {
    Write-Host ""
    Write-Host "LOI: khong tim thay pyproject.toml trong thu muc project."
    exit 1
}

# ================= 1. VIRTUAL ENVIRONMENT =================
$VenvMode = "venv"
if ($NoVenv) {
    Write-Step "[1/2] Bo qua tao venv (--no-venv), cai package vao thu muc vendor/."
    $VenvMode = "vendor"
} else {
    Write-Step "[1/2] Tao virtual environment..."
    & $PythonExe -m venv $VENV_DIR
    $VENV_PY = Join-Path $VENV_DIR "Scripts\python.exe"
    if (Test-Path $VENV_PY) {
        Write-Host "  Virtual environment da san sang: $VENV_DIR"
    } else {
        Write-Host "  Khong tao duoc venv -> Fallback: cai package vao thu muc vendor/ trong project."
        $VenvMode = "vendor"
    }
}

if ($VenvMode -eq "venv") {
    $PythonExe = Join-Path $VENV_DIR "Scripts\python.exe"
} else {
    New-Item -ItemType Directory -Force -Path $VENDOR_DIR | Out-Null
}

# ================= 2. INSTALL DEPENDENCIES =================
Write-Step "[2/2] Cai dat dependencies..."
& $PythonExe -m pip install --upgrade pip
if ($VenvMode -eq "vendor") {
    & $PythonExe -m pip install --target $VENDOR_DIR .
} else {
    & $PythonExe -m pip install .
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ================= DONE =================
Write-Host ""
Write-Host "============================================================"
Write-Host "  Hoan tat! Chay app bang lenh:"
if ($VenvMode -eq "venv") {
    Write-Host "    $VENV_DIR\Scripts\python.exe run.py"
} else {
    Write-Host "    `$env:PYTHONPATH='$VENDOR_DIR'; $PythonExe run.py"
}
Write-Host "============================================================"