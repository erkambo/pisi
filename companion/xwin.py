"""Where the browser's windows really are, from the X server (X11 only).

Brave on X11 doesn't tell its pages where they are: its window numbers leave
out the tab strip and toolbar (and scale with the page zoom). The X server
knows each window's real place and size, and a page always runs to the bottom
of its window, so the page's top is the window's bottom minus the page's
height (which the browser does report right). Exact on any page, even ones
with hardly any text to match against the screen.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time

BROWSERS = ("brave-browser", "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
            "vivaldi", "vivaldi-stable", "opera", "firefox", "navigator")
_LINE = re.compile(r'^\s*(0x[0-9a-f]+) .*?: \("([^"]*)" "([^"]*)"\)\s+(\d+)x(\d+)[+-]\d+[+-]\d+\s+'
                   r'([+-]\d+)([+-]\d+)')
_cache: tuple[float, list] = (0.0, [])


def available() -> bool:
    return shutil.which("xwininfo") is not None


def browser_windows(max_age: float = 1.0) -> list[tuple[int, str, int, int, int, int]]:
    """(window id, class, x, y, w, h) in real screen pixels, for every browser
    window on screen (cached for ``max_age`` seconds)."""
    global _cache
    now = time.monotonic()
    if now - _cache[0] < max_age:
        return _cache[1]
    out = []
    try:
        tree = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True,
                              timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        tree = ""
    for line in tree.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        wid, inst, cls = m.group(1), m.group(2).lower(), m.group(3).lower()
        if not any(b in (inst, cls) for b in BROWSERS):
            continue
        w, h, x, y = int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
        if w < 200 or h < 150:
            continue                          # helper windows (clipboard, popups)
        out.append((int(wid, 16), cls, x, y, w, h))
    _cache = (now, out)
    return out


def to_logical(x: float, y: float, w: float, h: float, screens: list[tuple]) -> tuple | None:
    """Real pixels -> Qt's units, on whichever screen holds the rect's middle
    (Qt keeps a screen's top-left in real pixels and scales from there)."""
    cx, cy = x + w / 2, y + h / 2
    for sx, sy, sw, sh, dpr in screens:
        if sx <= cx < sx + sw * dpr and sy <= cy < sy + sh * dpr:
            return (sx + (x - sx) / dpr, sy + (y - sy) / dpr, w / dpr, h / dpr)
    return None


_wa_cache: tuple[float, tuple | None] = (0.0, None)


def workarea(max_age: float = 5.0) -> tuple[int, int, int, int] | None:
    """The desktop's usable area (x, y, w, h) in real pixels from
    _NET_WORKAREA (the current desktop's): everything minus the panels.
    One rectangle for all monitors together. None if unknown."""
    global _wa_cache
    now = time.monotonic()
    if now - _wa_cache[0] < max_age:
        return _wa_cache[1]
    val = None
    if shutil.which("xprop"):
        try:
            out = subprocess.run(["xprop", "-root", "_NET_WORKAREA", "_NET_CURRENT_DESKTOP"],
                                 capture_output=True, text=True, timeout=2).stdout
            nums = re.search(r"_NET_WORKAREA\(CARDINAL\) = ([\d, ]+)", out)
            cur = re.search(r"_NET_CURRENT_DESKTOP\(CARDINAL\) = (\d+)", out)
            if nums:
                v = [int(n) for n in nums.group(1).split(",")]
                k = int(cur.group(1)) if cur else 0
                if len(v) >= 4 * (k + 1):
                    val = tuple(v[4 * k:4 * k + 4])
        except (OSError, subprocess.SubprocessError, ValueError):
            val = None
    _wa_cache = (now, val)
    return val
