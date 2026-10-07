#!/usr/bin/env bash
# ============================================================
#  Auto installer for the Video Download Tool (Linux / macOS)
#
#  Installs everything needed to run the app, all kept inside
#  the code folder:
#    1. Creates a virtual environment (.venv) — if the system
#       cannot create one it falls back to installing packages
#       into vendor/.
#    2. Installs the dependencies declared in pyproject.toml.
#
#  Usage:
#    ./setup.sh                # install everything
#    ./setup.sh --no-venv      # skip venv, install packages into vendor/
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_PY=".venv/bin/python"
VEN=".venv"
VENDOR_DIR="vendor"

NO_VENV=false
for arg in "$@"; do
    case "$arg" in
        --no-venv) NO_VENV=true ;;
        *) echo "Khong nhan dien duoc doi so: $arg"; echo "Huu ich: --no-venv"; exit 1 ;;
    esac
done

echo "============================================================"
echo "  Video Download Tool - Auto Installer"
echo "============================================================"
echo
echo "Python: $($PYTHON_BIN --version 2>/dev/null || echo 'not found')"
echo "Hệ điều hành: $(uname -s)"

if [ ! -f "pyproject.toml" ]; then
    echo
    echo "LOI: khong tim thay pyproject.toml trong thu muc project."
    exit 1
fi

# ================= 1. VIRTUAL ENVIRONMENT =================
VENV_MODE="venv"
if [ "$NO_VENV" = true ]; then
    echo
    echo "[1/2] Bo qua tao venv (--no-venv), cai package vao thu muc vendor/."
    VENV_MODE="vendor"
else
    echo
    echo "[1/2] Tao virtual environment..."
    if ! "$PYTHON_BIN" -m venv "$VEN" 2>/dev/null || [ ! -x "$VENV_PY" ]; then
        echo "   Khong tao duoc venv -> Fallback: cai package vao thu muc vendor/ trong project."
        VENV_MODE="vendor"
    else
        echo "   Virtual environment da san sang: $VEN"
    fi
fi

PY="$PYTHON_BIN"
export PYTHONPATH=""
if [ "$VENV_MODE" = "venv" ]; then
    PY="$VENV_PY"
else
    mkdir -p "$VENDOR_DIR"
    export PYTHONPATH="$PWD/$VENDOR_DIR"
fi

# ================= 2. INSTALL DEPENDENCIES =================
echo
echo "[2/2] Cai dat dependencies..."
"$PY" -m pip install --upgrade pip
if [ "$VENV_MODE" = "vendor" ]; then
    "$PY" -m pip install --target "$VENDOR_DIR" .
else
    "$PY" -m pip install .
fi

# ================= DONE =================
echo
echo "============================================================"
echo "  Hoan tat! Chay app bang lenh:"
if [ "$VENV_MODE" = "venv" ]; then
    echo "    $PWD/.venv/bin/python run.py"
else
    echo "    PYTHONPATH=$PWD/$VENDOR_DIR $PYTHON_BIN run.py"
fi
echo "============================================================"