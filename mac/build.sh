#!/usr/bin/env bash
# Build PISI for macOS:  dist/PISI.app  and  dist/PISI-<ver>-mac-<arch>.dmg
# (the single file to give friends). Run on a Mac:   mac/build.sh [--skip-tests]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    echo "Need Python 3.10+ (the one from Xcode is too old). Try: brew install python@3.12" >&2
    exit 1
fi
[ -x .venv-build/bin/python ] || "$PY" -m venv .venv-build
VPY=.venv-build/bin/python
echo "==> Installing build tools..."
"$VPY" -m pip install --disable-pip-version-check -q --upgrade pip
"$VPY" -m pip install --disable-pip-version-check -q -r mac/requirements-build.txt

VER="$("$VPY" -c 'import companion; print(companion.__version__)')"
case "$(uname -m)" in arm64) ARCH=apple-silicon ;; *) ARCH=intel ;; esac
echo "==> PISI $VER ($ARCH)"

if [ "${1:-}" != "--skip-tests" ]; then
    echo "==> Running tests..."
    QT_QPA_PLATFORM=offscreen "$VPY" -m pytest -q
fi

echo "==> Building PISI.app..."
"$VPY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build mac/pisi-mac.spec
# ad-hoc signature over the whole bundle (Apple Silicon refuses unsigned code)
codesign --force --deep --sign - dist/PISI.app

echo "==> Smoke test: PISI --doctor ..."
SMOKE="$(mktemp -d)"
set +e
XDG_DATA_HOME="$SMOKE" dist/PISI.app/Contents/MacOS/PISI --doctor --quiet >/dev/null 2>&1
RC=$?
set -e
cat "$SMOKE/desktop-companion/doctor.txt" || { echo "doctor produced no report" >&2; exit 1; }
rm -rf "$SMOKE"
[ "$RC" -eq 0 ] || { echo "PISI --doctor reported a failure" >&2; exit 1; }

echo "==> Making the disk image..."
STAGE="$(mktemp -d)"
cp -R dist/PISI.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/If macOS won't open PISI.txt" <<'TXT'
PISI isn't from the App Store, so the first time macOS may say it
"can't be opened" or "Apple could not verify" it. To allow it:

  1. Drag PISI into Applications and double-click it once.
  2. Open System Settings > Privacy & Security, scroll down, and click
     "Open Anyway" next to the message about PISI. Confirm with your password.

(Older macOS: right-click PISI in Applications > Open > Open.)

After that it opens normally, starts when you log in, and lives in the
menu bar (top right). Right-click the cat for its menu.
TXT
DMG="dist/PISI-$VER-mac-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "PISI" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo
echo "Built: $ROOT/$DMG"
