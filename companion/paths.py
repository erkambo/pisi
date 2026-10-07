"""Filesystem locations for the companion's persistent data.

Everything the companion remembers lives OUTSIDE the source tree so that
reinstalling, moving, or deleting the code never wipes your habits, files,
links and streaks:

    Linux    $XDG_DATA_HOME/desktop-companion   (~/.local/share/…)
    Windows  %APPDATA%\\desktop-companion
    macOS    ~/Library/Application Support/desktop-companion
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "desktop-companion"
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def data_dir() -> Path:
    # XDG_DATA_HOME wins on every platform (the tests rely on it to isolate data)
    base = os.environ.get("XDG_DATA_HOME")
    if not base:
        if IS_WINDOWS:
            base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        elif IS_MAC:
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.path.expanduser("~/.local/share")
    d = Path(base) / APP_ID
    if d not in _PRIVATE:
        # it holds a private calendar address, Google tokens and a log of
        # your days: only you may open it (Windows profiles already are private)
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not IS_WINDOWS:
            try:
                d.chmod(0o700)
            except OSError:
                pass
        _PRIVATE.add(d)
    return d


_PRIVATE: set = set()


def app_root() -> Path:
    """The folder holding ``companion/`` and ``assets/`` — the source checkout,
    or PyInstaller's bundle dir when running as a packaged .exe."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return Path(__file__).resolve().parent.parent


def asset_dir() -> Path:
    """Bundled, read-only assets that ship with the app (icon, sounds…)."""
    return app_root() / "assets"


def sounds_dir() -> Path:
    return asset_dir() / "sounds"


def data_file() -> Path:
    return data_dir() / "data.json"


def log_file() -> Path:
    return data_dir() / "companion.log"


def calendar_cache_file() -> Path:
    return data_dir() / "calendar_cache.json"


def google_token_file() -> Path:
    return data_dir() / "google_token.json"


def private_socket(name: str) -> str:
    """Where a local socket called ``name`` should live. On Linux a bare name
    lands in /tmp, shared by every account on the computer, where another one
    could claim it first; $XDG_RUNTIME_DIR is this user's own (mode 0700).
    macOS already keeps sockets in a per-user folder, and Windows pipes are
    restricted to this user by the server (UserAccessOption)."""
    if IS_WINDOWS or IS_MAC:
        return name
    d = os.environ.get("XDG_RUNTIME_DIR")
    try:
        st = os.stat(d) if d else None
    except OSError:
        st = None
    if st is None or st.st_uid != os.getuid() or st.st_mode & 0o077:
        return name
    return os.path.join(d, name)

