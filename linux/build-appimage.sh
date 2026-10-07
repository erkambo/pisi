#!/usr/bin/env bash
# Build PISI for Linux:  dist/PISI-<ver>-x86_64.AppImage  (one file, runs on
# Mint, Ubuntu, Fedora, Arch... with glibc 2.35+; double-click or run it).
# Usage:  linux/build-appimage.sh [--skip-tests]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
[ -x .venv-build/bin/python ] || "$PY" -m venv .venv-build
VPY=.venv-build/bin/python
echo "==> Installing build tools..."
"$VPY" -m pip install --disable-pip-version-check -q --upgrade pip
"$VPY" -m pip install --disable-pip-version-check -q -r linux/requirements-build.txt

VER="$("$VPY" -c 'import companion; print(companion.__version__)')"
echo "==> PISI $VER (Linux x86_64)"

if [ "${1:-}" != "--skip-tests" ]; then
    echo "==> Running tests..."
    QT_QPA_PLATFORM=offscreen "$VPY" -m pytest -q
fi

echo "==> Building..."
"$VPY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build linux/pisi-linux.spec

echo "==> Smoke test: PISI --doctor ..."
SMOKE="$(mktemp -d)"
set +e
XDG_DATA_HOME="$SMOKE" QT_QPA_PLATFORM=offscreen dist/PISI/PISI --doctor --quiet >/dev/null 2>&1
RC=$?
set -e
cat "$SMOKE/desktop-companion/doctor.txt" || { echo "doctor produced no report" >&2; exit 1; }
rm -rf "$SMOKE"
[ "$RC" -eq 0 ] || { echo "PISI --doctor reported a failure" >&2; exit 1; }

echo "==> Making the AppImage..."
APPDIR="$(mktemp -d)/PISI.AppDir"
mkdir -p "$APPDIR/usr/lib"
cp -R dist/PISI "$APPDIR/usr/lib/pisi"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/pisi/PISI" "$@"
RUN
chmod +x "$APPDIR/AppRun"
cp assets/icon.png "$APPDIR/pisi.png"
cat > "$APPDIR/pisi.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=PISI
Comment=A desktop cat that keeps you company while you focus
Exec=PISI
Icon=pisi
Terminal=false
Categories=Utility;
X-AppImage-Version=$VER
DESK
TOOL=build/appimagetool-x86_64.AppImage
if [ ! -x "$TOOL" ]; then
    mkdir -p build
    curl -fsSL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi
OUT="dist/PISI-$VER-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"
echo
echo "Done: $OUT"
