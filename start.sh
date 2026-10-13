#!/usr/bin/env bash
#
# Click-to-run for Linux/macOS:
#   - detect the environment (.venv or vendor/),
#   - if nothing is installed, run scripts/setup.sh,
#   - then launch run.py.
set -e
# Kept next to run.py, so the project root is this script's folder.
cd "$(dirname "$0")"

pick_python() {
    if [ -x ".venv/bin/python" ]; then
        PY=".venv/bin/python"
    elif [ -d "vendor" ]; then
        PY="python3"
        export PYTHONPATH="$PWD/vendor"
    else
        PY=""
    fi
}

pick_python

if [ -z "$PY" ]; then
    if [ ! -f "pyproject.toml" ]; then
        echo "pyproject.toml not found in the project folder."
        echo "Please run: ./scripts/setup.sh"
        exit 1
    fi
    echo "Dependencies not installed. Installing (this may take a few minutes)..."
    ./scripts/setup.sh
    pick_python
    if [ -z "$PY" ]; then
        echo "Installation failed. Please run manually: ./scripts/setup.sh"
        exit 1
    fi
fi

exec "$PY" run.py