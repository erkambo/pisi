"""macOS-only system glue — stdlib only (ctypes + the built-in osascript
tool), no PyObjC. Mirrors winapi.py:

    idle_ms()             CGEventSourceSecondsSinceLastEventType   (≈ xprintidle)
    float_everywhere(w)   NSWindow collection behaviour: the cat follows you
                          across Spaces/desktops and never hides when PISI
                          isn't the active app
    hide_dock_icon()      NSApp.setActivationPolicy(.accessory) — a menu-bar app
    osascript(src)        run AppleScript (browser tabs, notifications, windows)
    notify(title, body)   Notification Center banner
    launch agent          ~/Library/LaunchAgents plist = start at login

Everything is best-effort: failures return None / False, never raise. Import
only when ``sys.platform == "darwin"``.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import plistlib
import subprocess
from pathlib import Path, PurePosixPath

from .log import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# idle time (CoreGraphics; needs no special permission)
try:
    _cg = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    _cg.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
    _cg.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_int32, ctypes.c_uint32]
except (OSError, AttributeError):           # pragma: no cover
    _cg = None

_kCGEventSourceStateHIDSystemState = 1
_kCGAnyInputEventType = 0xFFFFFFFF


def idle_ms() -> int | None:
    if _cg is None:
        return None
    try:
        secs = _cg.CGEventSourceSecondsSinceLastEventType(
            _kCGEventSourceStateHIDSystemState, _kCGAnyInputEventType)
        return int(secs * 1000) if secs >= 0 else None
    except Exception:                        # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Objective-C runtime, just enough to talk to NSApplication / NSWindow
try:
    _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
    _objc.objc_getClass.restype = ctypes.c_void_p
    _objc.objc_getClass.argtypes = [ctypes.c_char_p]
    _objc.sel_registerName.restype = ctypes.c_void_p
    _objc.sel_registerName.argtypes = [ctypes.c_char_p]
    _MSGSEND = ctypes.cast(_objc.objc_msgSend, ctypes.c_void_p).value
except (OSError, AttributeError):           # pragma: no cover
    _objc = None
    _MSGSEND = None


def _send(restype, *argtypes):
    """A correctly-typed objc_msgSend (arm64 must not call it as variadic)."""
    return ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(_MSGSEND)


def _sel(name: str):
    return _objc.sel_registerName(name.encode())


# NSWindowCollectionBehavior bits
CAN_JOIN_ALL_SPACES = 1 << 0
MOVE_TO_ACTIVE_SPACE = 1 << 1
STATIONARY = 1 << 4          # stays put in Mission Control
IGNORES_CYCLE = 1 << 6       # not part of Cmd-` window cycling
FULLSCREEN_AUXILIARY = 1 << 8


def _is_cocoa() -> bool:
    """winId() is an NSView* only on the real Cocoa platform — under Qt's
    `offscreen` platform (tests/CI) messaging it would crash."""
    from PyQt6.QtGui import QGuiApplication
    return QGuiApplication.platformName() == "cocoa"


def _nswindow(widget):
    view = int(widget.winId())                   # a QWidget's winId is its NSView*
    if not view:
        return None
    return _send(ctypes.c_void_p)(view, _sel("window"))


ABOVE_DOCK = 21               # kCGDockWindowLevel (20) + 1: over the Dock, under menus


def set_level(widget, level: int) -> bool:
    """Put `widget`'s window at an NSWindow level. PISI's corner stands in the
    Dock's strip: at Qt's usual "stay on top" level (floating, 3) the Dock
    covers it and keeps the clicks, so the corner and the cat (which must stay
    in front of the corner) go just above the Dock."""
    if _objc is None or not _is_cocoa():
        return False
    try:
        win = _nswindow(widget)
        if not win:
            return False
        _send(None, ctypes.c_long)(win, _sel("setLevel:"), int(level))
        return int(_send(ctypes.c_long)(win, _sel("level"))) == int(level)
    except Exception:                        # noqa: BLE001
        log.info("could not set the window level", exc_info=True)
        return False


def float_everywhere(widget) -> int | None:
    """Show `widget` on every Space and keep it up when PISI isn't frontmost.
    Deliberately NOT fullscreen-auxiliary, so the cat stays out of fullscreen
    apps/videos (the macOS counterpart of the Windows fullscreen guard).
    Returns the resulting collection behaviour, or None on failure."""
    if _objc is None or not _is_cocoa():
        return None
    try:
        win = _nswindow(widget)
        if not win:
            return None
        cur = _send(ctypes.c_ulong)(win, _sel("collectionBehavior"))
        new = (cur | CAN_JOIN_ALL_SPACES | STATIONARY | IGNORES_CYCLE) \
            & ~(MOVE_TO_ACTIVE_SPACE | FULLSCREEN_AUXILIARY)
        _send(None, ctypes.c_ulong)(win, _sel("setCollectionBehavior:"), new)
        _send(None, ctypes.c_bool)(win, _sel("setHidesOnDeactivate:"), False)
        return int(_send(ctypes.c_ulong)(win, _sel("collectionBehavior")))
    except Exception:                        # noqa: BLE001
        log.info("could not set window collection behaviour", exc_info=True)
        return None


def hide_dock_icon() -> bool:
    """Run as a menu-bar ("accessory") app: no Dock icon, no Cmd-Tab entry.
    The packaged PISI.app does this via LSUIElement; this covers source runs."""
    if _objc is None or not _is_cocoa():
        return False
    try:
        app = _send(ctypes.c_void_p)(_objc.objc_getClass(b"NSApplication"),
                                     _sel("sharedApplication"))
        return bool(_send(ctypes.c_bool, ctypes.c_long)(
            app, _sel("setActivationPolicy:"), 1))       # .accessory
    except Exception:                        # noqa: BLE001
        return False


def activate_app() -> None:
    """Bring PISI's windows forward (an accessory app isn't activated by a click
    on its non-activating panels, so a fresh dialog could open behind others)."""
    if _objc is None or not _is_cocoa():
        return
    try:
        app = _send(ctypes.c_void_p)(_objc.objc_getClass(b"NSApplication"),
                                     _sel("sharedApplication"))
        _send(None, ctypes.c_bool)(app, _sel("activateIgnoringOtherApps:"), True)
    except Exception:                        # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# AppleScript
def osascript(source: str, timeout: float = 60) -> str | None:
    """Run AppleScript; stdout on success, None on error/denied permission."""
    try:
        r = subprocess.run(["osascript", "-"], input=source, capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        log.info("osascript failed: %s", r.stderr.strip()[:300])
        return None
    return r.stdout


def as_string(s: str) -> str:
    """An AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, body: str) -> bool:
    """Fire-and-forget (never blocks the UI on osascript)."""
    src = f"display notification {as_string(body)} with title {as_string(title)}"
    try:
        subprocess.Popen(["osascript", "-e", src], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# start at login: a per-user LaunchAgent (no admin; shows up in System
# Settings → General → Login Items as a background item)
AGENT_LABEL = "com.erkambo.pisi"


def agent_path() -> Path:
    return Path(os.path.expanduser(f"~/Library/LaunchAgents/{AGENT_LABEL}.plist"))


def agent_get() -> list[str] | None:
    try:
        with open(agent_path(), "rb") as fh:
            return list(plistlib.load(fh).get("ProgramArguments", []))
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def agent_set(argv: list[str] | None) -> bool:
    p = agent_path()
    try:
        if argv is None:
            p.unlink(missing_ok=True)
            return True
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as fh:
            plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": argv,
                           "RunAtLoad": True, "ProcessType": "Interactive"}, fh)
        return True
    except OSError:
        log.warning("could not update the LaunchAgent", exc_info=True)
        return False


def app_bundle(executable: str) -> str | None:
    """/Applications/PISI.app for …/PISI.app/Contents/MacOS/PISI, else None."""
    for parent in PurePosixPath(executable).parents:    # a macOS path, always
        if parent.suffix == ".app":
            return str(parent)
    return None
