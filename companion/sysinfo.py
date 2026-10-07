"""Small, dependency-free readers for local system state the companion uses to
be situationally aware: user-idle time, fullscreen apps, time of day.

Linux reads /sys + xprintidle; Windows goes through Win32 (winapi.py) and
macOS through CoreGraphics + pmset (macapi.py)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
_HAS_XPRINTIDLE = sys.platform.startswith("linux") and shutil.which("xprintidle") is not None


def idle_ms() -> int | None:
    """Milliseconds since last input (xprintidle / GetLastInputInfo). None if
    unavailable."""
    if IS_WINDOWS:
        from . import winapi
        return winapi.idle_ms()
    if IS_MAC:
        from . import macapi
        return macapi.idle_ms()
    if not _HAS_XPRINTIDLE:
        return None
    try:
        out = subprocess.run(["xprintidle"], capture_output=True, text=True,
                             timeout=2)
        return int(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return None


def fullscreen_busy() -> bool:
    """True while a fullscreen game / video / presentation has the screen, so
    the cat can step out of the way. Windows only: on macOS fullscreen apps
    get their own Space, which the cat doesn't join (see macapi.float_everywhere)."""
    if IS_WINDOWS:
        from . import winapi
        return winapi.fullscreen_busy()
    return False


def part_of_day(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    if h < 5:
        return "night"
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    if h < 22:
        return "evening"
    return "night"
