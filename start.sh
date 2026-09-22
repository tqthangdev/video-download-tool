#!/usr/bin/env bash
#
# Click-to-run for Linux/macOS:
#   - detect the environment (.venv or vendor/),
#   - if nothing is installed, run ./setup.sh,
#   - then launch run.py.
set -e
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
    if [ ! -f "requirements.txt" ]; then
        echo "requirements.txt not found in the project folder."
        echo "Please run: ./setup.sh"
        exit 1
    fi
    echo "Dependencies not installed. Installing (this may take a few minutes)..."
    ./setup.sh
    pick_python
    if [ -z "$PY" ]; then
        echo "Installation failed. Please run manually: ./setup.sh"
        exit 1
    fi
fi

exec "$PY" run.py