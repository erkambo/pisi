#!/usr/bin/env bash
# Install PISI on macOS from this source folder (for testers / tinkerers).
# Friends who just want the app should use the .dmg instead (see README).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && \
       "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        PY="$(command -v "$c")"; break
    fi
done
if [ -z "$PY" ]; then
    echo "PISI needs Python 3.10 or newer (macOS's built-in one is too old)."
    echo "Install it with Homebrew:   brew install python@3.12"
    echo "or from https://www.python.org/downloads/macos/ , then run this again."
    exit 1
fi
echo "==> Using $PY"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
echo "==> Installing PyQt6 (first time takes a minute)..."
.venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
.venv/bin/python -m pip install --disable-pip-version-check -q -r mac/requirements.txt
.venv/bin/python -c "import PyQt6.QtWidgets"
echo "==> Open at login..."
.venv/bin/python -m companion --install
echo "==> Starting PISI..."
nohup .venv/bin/python pisi.pyw >/dev/null 2>&1 &
echo
echo "Done! The cat appears in a few seconds; its paw icon is in the menu bar."
echo "Something off?  .venv/bin/python -m companion --doctor"
