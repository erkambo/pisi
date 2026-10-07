#!/usr/bin/env bash
# Install dependencies and set the companion to start on login.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN="$DIR/run.sh"
chmod +x "$RUN"

echo "==> Checking for PyQt6…"
if python3 -c "import PyQt6" 2>/dev/null; then
    echo "    PyQt6 already available."
else
    echo "    PyQt6 not found. Installing python3-pyqt6 via apt (needs sudo)…"
    sudo apt update
    sudo apt install -y python3-pyqt6
fi

# Optional: xprintidle lets the companion wait until you're back before nudging.
if ! command -v xprintidle >/dev/null 2>&1; then
    echo "==> Installing xprintidle (optional, for idle-aware nudges)…"
    sudo apt install -y xprintidle || echo "    (skipped — not essential)"
fi

echo "==> Setting up autostart on login…"
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/desktop-companion.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Desktop Companion
Comment=A wandering cat that helps you keep up with your habits
Exec=bash -lc "sleep 6; exec '$RUN'"
Icon=face-smile
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "==> Adding an application-menu launcher…"
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
cat > "$APPS_DIR/desktop-companion.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Desktop Companion
Comment=A wandering cat that helps you keep up with your habits
Exec=$RUN
Icon=face-smile
Terminal=false
Categories=Utility;
EOF

case "${XDG_CURRENT_DESKTOP:-}" in
    *Cinnamon*|*GNOME*|*ubuntu*)
        echo "==> Adding PISI's panel extension (so the corner works on the panel)…"
        (cd "$DIR" && python3 -m companion --install-panel-extension) || echo "    (skipped)"
        ;;
esac

echo
echo "Done!  Start it now with:   $RUN"
echo "It will also launch automatically next time you log in."
echo "Right-click the cat (or its tray icon) for the menu."
