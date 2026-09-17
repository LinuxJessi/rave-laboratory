#!/bin/bash
# Rave Laboratory on Linux: double-click (choose "Run") or:  ./Rave\ Laboratory.sh
# Uses the Python bundled in runtime/ if present, otherwise your Python 3 (installs pygame-ce into a private .venv the first time).
cd "$(dirname "$0")"
if [ -x "runtime/bin/python3" ]; then
    exec "runtime/bin/python3" ravelab.py "$@"          # the bundled Python that ships with the release
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Rave Laboratory needs Python 3 (sudo apt install python3 python3-venv, or your distro's package), or the ready-made build."
    read -r -p "Press Enter to close"
    exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
    echo "First run: setting up a private Python environment (about a minute)..."
    python3 -m venv .venv || { echo "python3-venv is missing (sudo apt install python3-venv)"; read -r -p "Press Enter"; exit 1; }
    .venv/bin/python -m pip install --upgrade pip >/dev/null && .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python ravelab.py "$@"
