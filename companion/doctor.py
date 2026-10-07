"""`--doctor`: a quick health check of everything PISI touches on this machine.

Meant for "it doesn't work on my PC" moments: run ``PISI.exe --doctor`` (or
``python -m companion --doctor``; add ``--quiet`` to never pop a window) and it
writes a report — each subsystem with
OK / WARN / FAIL — to ``doctor.txt`` in the data folder, prints it if there is a
console, and otherwise opens it. Nothing here changes any state.
"""
from __future__ import annotations

import os
import platform
import sys
import time
import traceback


def _checks():
    """Yield (status, name, detail). Each check is isolated from the others."""
    from . import __version__
    yield "OK", "PISI", f"{__version__} on {platform.platform()} (Python {platform.python_version()})"
    yield "OK", "frozen .exe" if getattr(sys, "frozen", False) else "source", sys.executable

    def run(name, fn):
        t0 = time.perf_counter()
        try:
            status, detail = fn()
        except Exception as e:               # noqa: BLE001
            status, detail = "FAIL", f"{type(e).__name__}: {e}"
            traceback.print_exc(file=_TB)
        ms = (time.perf_counter() - t0) * 1000
        return status, name, f"{detail}  [{ms:.0f} ms]"

    def qt():
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        return "OK", f"PyQt {PYQT_VERSION_STR}, Qt {QT_VERSION_STR}"
    yield run("Qt", qt)

    def data():
        from .paths import data_dir
        d = data_dir()
        probe = d / ".write-test"
        probe.write_text("ok", "utf-8")
        probe.unlink()
        return "OK", f"writable: {d}"
    yield run("data folder", data)

    def store():
        from .store import Store
        s = Store()
        return "OK", f"{len(s.habits)} habits loaded"
    yield run("saved data", store)

    def browser_bridge():
        from . import bridge
        ext = bridge.extension_dir() / "manifest.json"
        if not ext.exists():
            return "WARN", f"extension missing under {bridge.extension_dir()}"
        have = bridge.installed()
        if not have:
            return "OK", "not set up (optional: Settings -> Web pages)"
        return "OK", "set up for " + ", ".join(have)
    yield run("browser bridge", browser_bridge)

    def assets():
        from .paths import asset_dir, sounds_dir
        icon = asset_dir() / "icon.png"
        wavs = sorted(p.name for p in sounds_dir().glob("*.wav"))
        if not icon.exists() or not wavs:
            return "FAIL", f"assets missing under {asset_dir()}"
        return "OK", f"icon + {len(wavs)} sounds ({', '.join(wavs)})"
    yield run("assets", assets)

    def cat():
        from . import pixelsheet
        from .store import Store
        sheet = pixelsheet.load(Store().config)
        if sheet is None:
            return "FAIL", "the cat couldn't be drawn (see companion.log)"
        return "OK", f"{len(sheet.anims)} animations"
    yield run("the cat", cat)

    def tray():
        from PyQt6.QtWidgets import QSystemTrayIcon
        ok = QSystemTrayIcon.isSystemTrayAvailable()
        return ("OK" if ok else "WARN"), ("available" if ok else "no system tray found")
    yield run("system tray", tray)

    if sys.platform == "darwin":
        def spaces():
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QGuiApplication
            from PyQt6.QtWidgets import QWidget

            from . import macapi
            if QGuiApplication.platformName() != "cocoa":
                return "OK", f"skipped ({QGuiApplication.platformName()} platform)"
            w = QWidget(None)
            w.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
            w.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
            w.resize(8, 8)
            w.show()
            beh = macapi.float_everywhere(w)
            w.close()
            if beh is None:
                return "FAIL", "could not reach the NSWindow"
            ok = beh & macapi.CAN_JOIN_ALL_SPACES and not beh & macapi.FULLSCREEN_AUXILIARY
            return ("OK" if ok else "FAIL"), f"on all Spaces, not over fullscreen (0x{beh:x})"
        yield run("cat on all desktops", spaces)

        def applescript():
            from . import macapi
            out = macapi.osascript("return 6 * 7", timeout=15)
            return ("OK" if (out or "").strip() == "42" else "WARN"), \
                f"osascript {'works' if out else 'unavailable'}"
        yield run("AppleScript", applescript)

    def idle():
        from .sysinfo import idle_ms
        v = idle_ms()
        if v is None:
            return "WARN", "unknown (nudges won't wait for you to come back)"
        return "OK", f"{v / 1000:.1f} s since last input"
    yield run("idle detection", idle)

    def fullscreen():
        from .sysinfo import fullscreen_busy
        return "OK", ("a fullscreen app is active" if fullscreen_busy()
                      else "no fullscreen app right now")
    yield run("fullscreen guard", fullscreen)

    def snap():
        from . import windows
        return window_summary(windows.snapshot())
    yield run("open windows", snap)

    def hist():
        from . import browsers
        dbs = browsers._chromium_dbs() + browsers._firefox_dbs()
        return ("OK" if dbs else "WARN"), (f"{len(dbs)} history DB(s)" if dbs
                                           else "no browser history found")
    yield run("browser history", hist)

    def sound():
        from . import chime
        keys = [k for k, _ in chime.available() if k != "none"]
        backend = ("winsound" if sys.platform == "win32" else
                   "afplay" if sys.platform == "darwin" else
                   (chime._linux_cmd("x.wav", 100) or ["none found"])[0])
        return ("OK" if keys else "WARN"), f"{len(keys)} tones, player: {backend}"
    yield run("alert sounds", sound)

    def tz():
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Istanbul")
        ZoneInfo("America/New_York")
        return "OK", f"tz database OK, local now {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}"
    yield run("time zones", tz)

    def auto():
        from . import autostart
        on = autostart.is_enabled()
        detail = f"{'on' if on else 'off'}, launches: {' '.join(autostart.launch_argv())}"
        if sys.platform == "win32":
            lnk = os.path.exists(autostart.shortcut_path())
            detail += f"; Start menu shortcut {'present' if lnk else 'missing'}"
        return "OK", detail
    yield run("start at sign-in", auto)

    def net():
        import urllib.request
        req = urllib.request.Request("https://www.gstatic.com/generate_204",
                                     headers={"User-Agent": "PISI-doctor"})
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                return "OK", f"HTTPS works (HTTP {r.status})"
        except OSError as e:                 # offline is a warning, not a broken install
            return "WARN", f"no internet? the calendar needs it ({e})"
    yield run("internet / TLS", net)


class _TBBuf:
    def __init__(self):
        self.parts: list[str] = []

    def write(self, s):
        self.parts.append(s)

    def flush(self):
        pass


_TB = _TBBuf()


def window_summary(rows: list[dict]) -> tuple[str, str]:
    """Counts only: this report gets attached to public issues, and window
    titles, file paths and tab addresses are nobody else's business."""
    kinds: dict = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return ("OK", f"{len(rows)} windows {kinds}") if rows else ("WARN", "none found")


def run(quiet: bool = False) -> int:
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)   # tray check needs it
    lines = []
    worst = "OK"
    for status, name, detail in _checks():
        lines.append(f"[{status:4}] {name:18} {detail}")
        if status == "FAIL" or (status == "WARN" and worst == "OK"):
            worst = status
    if _TB.parts:
        lines += ["", "Tracebacks:", "".join(_TB.parts)]
    report = "\n".join(lines) + f"\n\nOverall: {worst}\n"
    home = os.path.expanduser("~")
    if len(home) > 1:
        report = report.replace(home, "~")      # (it's shared in issues: no user names)

    from .paths import data_dir
    out = data_dir() / "doctor.txt"
    try:
        out.write_text(report, "utf-8")
    except OSError:
        pass
    if sys.stdout is not None:
        try:
            print(report)
            print(f"(saved to {out})")
        except UnicodeEncodeError:           # legacy console code page
            print(report.encode("ascii", "replace").decode())
    elif sys.platform == "win32" and not quiet:
        os.startfile(str(out))               # windowed .exe: show the report
    return 0 if worst != "FAIL" else 1
