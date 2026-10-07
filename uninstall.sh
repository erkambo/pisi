#!/usr/bin/env bash
# Remove autostart + launcher. Your data (~/.local/share/desktop-companion) is
# left untouched unless you pass --purge.
set -euo pipefail

echo "==> Removing autostart and launcher entries…"
rm -f "$HOME/.config/autostart/desktop-companion.desktop"
rm -f "$HOME/.local/share/applications/desktop-companion.desktop"

# stop a running instance, if any
pkill -f "python3 -m companion" 2>/dev/null || true

if [[ "${1:-}" == "--purge" ]]; then
    echo "==> Purging saved data…"
    rm -rf "$HOME/.local/share/desktop-companion"
fi

echo "Done. The source folder itself was not deleted — remove it whenever you like."
echo "(Pass --purge to also delete your saved habits/files/links.)"
