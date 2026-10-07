"""Resolve browser tab *titles* to their real URLs via the browsers' own
history databases.

X11 exposes only a window's active-tab title, never its URL — but every browser
records a title→URL mapping in a SQLite history DB. Since we already read the
title from the window manager, we can look the URL up. Read-only, best-effort,
stdlib-only (sqlite3). We copy the DB to a temp file first so we can read it
while the browser holds a write lock.
"""
from __future__ import annotations

import glob
import os
import shutil
import sqlite3
import sys
import tempfile

from .log import get_logger

log = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Chromium-family user-data roots (each holds Default/ and Profile N/ dirs).
_CHROMIUM_ROOTS = (
    "~/.config/google-chrome",
    "~/.config/BraveSoftware/Brave-Browser",
    "~/.config/chromium",
    "~/.config/microsoft-edge",
    "~/.config/vivaldi",
)
# …and where they live on Windows (under %LOCALAPPDATA%, Opera under %APPDATA%)
_WIN_CHROMIUM_ROOTS = (
    "%LOCALAPPDATA%/Google/Chrome/User Data",
    "%LOCALAPPDATA%/Microsoft/Edge/User Data",
    "%LOCALAPPDATA%/BraveSoftware/Brave-Browser/User Data",
    "%LOCALAPPDATA%/Chromium/User Data",
    "%LOCALAPPDATA%/Vivaldi/User Data",
    "%APPDATA%/Opera Software/Opera Stable",
    "%APPDATA%/Opera Software/Opera GX Stable",
)


# …and on macOS (Safari's history needs Full Disk Access, so it's left out —
# on a Mac we read Safari's open tabs directly via AppleScript instead)
_MAC_CHROMIUM_ROOTS = (
    "~/Library/Application Support/Google/Chrome",
    "~/Library/Application Support/Microsoft Edge",
    "~/Library/Application Support/BraveSoftware/Brave-Browser",
    "~/Library/Application Support/Chromium",
    "~/Library/Application Support/Vivaldi",
    "~/Library/Application Support/Arc/User Data",
    "~/Library/Application Support/com.operasoftware.Opera",
)


def _roots() -> list[str]:
    if IS_MAC:
        return [os.path.expanduser(r) for r in _MAC_CHROMIUM_ROOTS]
    if IS_WINDOWS:
        return [os.path.normpath(os.path.expandvars(r)) for r in _WIN_CHROMIUM_ROOTS
                if "%" not in os.path.expandvars(r)]
    return [os.path.expanduser(r) for r in _CHROMIUM_ROOTS]


def _chromium_dbs() -> list[str]:
    out: list[str] = []
    for base in _roots():
        if not os.path.isdir(base):
            continue
        profiles = ["Default"] + [os.path.basename(p)
                                  for p in glob.glob(os.path.join(base, "Profile*"))]
        for prof in profiles:
            db = os.path.join(base, prof, "History")
            if os.path.exists(db):
                out.append(db)
        if os.path.exists(os.path.join(base, "History")):     # Opera: no profiles
            out.append(os.path.join(base, "History"))
    return out


def _firefox_dbs() -> list[str]:
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return []
        return glob.glob(os.path.join(appdata, "Mozilla", "Firefox", "Profiles",
                                      "*", "places.sqlite"))
    if IS_MAC:
        return glob.glob(os.path.expanduser(
            "~/Library/Application Support/Firefox/Profiles/*/places.sqlite"))
    return glob.glob(os.path.expanduser("~/.mozilla/firefox/*/places.sqlite"))


def _lookup(db: str, titles: list[str], table: str, time_col: str) -> dict[str, str]:
    """Best (most recent) URL for each requested title in one history DB."""
    tmp = tempfile.mkdtemp(prefix="pisi-hist-")
    try:
        for ext in ("", "-wal", "-shm"):     # copy so browser locks don't block us
            if os.path.exists(db + ext):
                shutil.copy2(db + ext, os.path.join(tmp, "h" + ext))
        con = sqlite3.connect(os.path.join(tmp, "h"))
        found: dict[str, str] = {}
        for t in titles:
            try:
                row = con.execute(
                    f"SELECT url FROM {table} WHERE title=? "
                    f"ORDER BY {time_col} DESC LIMIT 1", (t,)).fetchone()
            except sqlite3.Error:
                row = None
            if row and row[0]:
                found[t] = row[0]
        con.close()
        return found
    except (OSError, sqlite3.Error):
        log.info("could not read browser history %s", db, exc_info=True)
        return {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def resolve_titles(titles: list[str]) -> dict[str, str]:
    """Map as many of the given tab titles as possible to their real URLs,
    searching every browser history DB. Titles not found are simply omitted."""
    want = [t for t in dict.fromkeys(titles) if t]
    if not want:
        return {}
    found: dict[str, str] = {}
    for db in _chromium_dbs():
        remaining = [t for t in want if t not in found]
        if not remaining:
            break
        found.update(_lookup(db, remaining, "urls", "last_visit_time"))
    for db in _firefox_dbs():
        remaining = [t for t in want if t not in found]
        if not remaining:
            break
        found.update(_lookup(db, remaining, "moz_places", "last_visit_date"))
    return found
