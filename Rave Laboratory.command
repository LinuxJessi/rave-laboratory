#!/bin/bash
# Rave Laboratory on macOS: double-click this file in Finder.
# Uses the Python bundled in runtime/ if present, otherwise your Python 3 (installs pygame-ce into a private .venv the first time).
cd "$(dirname "$0")"
if [ -x "runtime/bin/python3" ]; then
    exec "runtime/bin/python3" ravelab.py "$@"          # the bundled Python that ships with the release
fi
if ! command -v python3 >/dev/null 2>&1; then
    osascript -e 'display dialog "Rave Laboratory needs Python 3.\n\nInstall it from python.org, or download the ready-made Mac build (no Python needed)." buttons {"OK"} with icon stop'
    exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
    echo "First run: setting up a private Python environment (about a minute)..."
    python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip >/dev/null && .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python ravelab.py "$@"
