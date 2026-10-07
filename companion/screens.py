"""The part of a screen the cat can use: above the taskbar / panel.

Qt's ``availableGeometry()`` is right on Windows, macOS and single-monitor
X11, but on multi-monitor X11 it often reports the whole screen: the window
manager publishes one usable rectangle for all monitors together
(_NET_WORKAREA), which Qt can't split per monitor. Cinnamon's panel then
isn't subtracted, and the cat (and its corner) stood on the taskbar. Here
each monitor is intersected with that rectangle, in real pixels.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication


def usable(screen) -> QRect:
    """``screen.availableGeometry()``, corrected for panels on X11."""
    avail = screen.availableGeometry()
    if QApplication.platformName() != "xcb":
        return avail
    geo = screen.geometry()
    if avail != geo:
        return avail                      # Qt already knows about a panel here
    from . import xwin
    wa = xwin.workarea()
    if wa is None:
        return avail
    dpr = screen.devicePixelRatio() or 1.0
    # Qt keeps a screen's top-left in real pixels and scales from there
    px, py = geo.x(), geo.y()
    pw, ph = round(geo.width() * dpr), round(geo.height() * dpr)
    wx, wy, ww, wh = wa
    x0, y0 = max(px, wx), max(py, wy)
    x1, y1 = min(px + pw, wx + ww), min(py + ph, wy + wh)
    if x1 - x0 < pw * 0.5 or y1 - y0 < ph * 0.5:
        return avail                      # nonsense (another desktop layout): don't trust it
    return QRect(px + round((x0 - px) / dpr), py + round((y0 - py) / dpr),
                 round((x1 - x0) / dpr), round((y1 - y0) / dpr))
