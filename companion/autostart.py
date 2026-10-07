"""Start PISI when you sign in — one toggle, both platforms.

    Linux    ~/.config/autostart/desktop-companion.desktop  (what install.sh writes)
    Windows  HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run  (no admin needed)
    macOS    ~/Library/LaunchAgents/com.erkambo.pisi.plist

Also owns the Windows Start-menu shortcut and the ``--uninstall`` cleanup, since
they all hinge on the same question: what command launches this copy of PISI?
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .log import get_logger
from .paths import app_root

log = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
SHORTCUT_NAME = "PISI.lnk"
_DESKTOP_FILE = os.path.expanduser("~/.config/autostart/desktop-companion.desktop")
_APPS_FILE = os.path.expanduser("~/.local/share/applications/desktop-companion.desktop")


def appimage() -> str | None:
    """The AppImage file this PISI runs from (Linux), if it's one: its
    insides live in a temporary mount, so launchers must point at the file."""
    p = os.environ.get("APPIMAGE")
    return p if p and not IS_WINDOWS and not IS_MAC and os.path.isfile(p) else None


def launch_argv() -> list[str]:
    """The command that starts this copy of PISI, without a console window."""
    if appimage():
        return [appimage()]
    if getattr(sys, "frozen", False):                    # packaged PISI.exe / PISI.app
        if IS_MAC:
            from . import macapi
            bundle = macapi.app_bundle(sys.executable)
            if bundle:
                return ["/usr/bin/open", bundle]
        return [sys.executable]
    root = app_root()
    if IS_MAC:
        return [sys.executable, str(root / "pisi.pyw")]
    if IS_WINDOWS:
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")               # no console flash
        return [str(pyw if pyw.exists() else exe), str(root / "pisi.pyw")]
    return [str(root / "run.sh")]


def _win_command() -> str:
    return subprocess.list2cmdline(launch_argv())


def is_enabled() -> bool:
    if IS_WINDOWS:
        from . import winapi
        return winapi.autostart_get() is not None
    if IS_MAC:
        from . import macapi
        return macapi.agent_get() is not None
    return os.path.exists(_DESKTOP_FILE)


def desktop_exec(argv: list[str]) -> str:
    """An Exec= value for a .desktop file, quoted the way the Desktop Entry
    spec says, so a folder called "Erkam's Apps" (or one with $ or a quote
    in it) still starts PISI and can never run anything else."""
    def arg(a: str) -> str:
        for c in ("\\", '"', "`", "$"):
            a = a.replace(c, "\\" + c)
        return '"' + a.replace("%", "%%") + '"'
    return " ".join(arg(a) for a in argv).replace("\\", "\\\\")   # then as a string value


def enable() -> bool:
    if IS_WINDOWS:
        from . import winapi
        return winapi.autostart_set(_win_command())
    if IS_MAC:
        from . import macapi
        return macapi.agent_set(launch_argv())
    try:
        os.makedirs(os.path.dirname(_DESKTOP_FILE), exist_ok=True)
        run = launch_argv()[0]
        cmd = desktop_exec(["bash", "-lc", 'sleep 6; exec "$0"', run])   # a moment after sign-in
        with open(_DESKTOP_FILE, "w", encoding="utf-8") as fh:
            fh.write(
                "[Desktop Entry]\nType=Application\nName=PISI\n"
                "Comment=A desktop cat that keeps you company while you focus\n"
                f"Exec={cmd}\n"
                f"Icon={_linux_icon()}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")
        return True
    except OSError:
        log.warning("could not write autostart entry", exc_info=True)
        return False


def disable() -> bool:
    if IS_WINDOWS:
        from . import winapi
        return winapi.autostart_set(None)
    if IS_MAC:
        from . import macapi
        return macapi.agent_set(None)
    try:
        os.remove(_DESKTOP_FILE)
    except FileNotFoundError:
        pass
    except OSError:
        log.warning("could not remove autostart entry", exc_info=True)
        return False
    return True


def set_enabled(on: bool) -> bool:
    return enable() if on else disable()


def refresh() -> None:
    """If autostart is on but points at an old location (the folder or .exe was
    moved), repoint it at this copy."""
    if IS_MAC:
        from . import macapi
        cur = macapi.agent_get()
        if cur is not None and cur != launch_argv():
            macapi.agent_set(launch_argv())
        return
    if not IS_WINDOWS:
        if appimage():                               # the AppImage was moved: follow it
            if is_enabled() and launch_argv()[0] not in _read(_DESKTOP_FILE):
                enable()
            if os.path.exists(_APPS_FILE) and launch_argv()[0] not in _read(_APPS_FILE):
                linux_app_entry()
        return
    from . import winapi
    cur = winapi.autostart_get()
    if cur is not None and cur != _win_command():
        winapi.autostart_set(_win_command())


# ---- Linux app menu (the AppImage puts itself there; install.sh does it from source)
_ICON_FILE = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/pisi.png")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _linux_icon() -> str:
    """PISI's own icon, copied where the desktop finds icons (an AppImage's
    insides go away when it quits)."""
    import shutil
    src = app_root() / "assets" / "icon.png"
    try:
        if src.exists():
            os.makedirs(os.path.dirname(_ICON_FILE), exist_ok=True)
            shutil.copyfile(src, _ICON_FILE)
            return "pisi"
    except OSError:
        pass
    return "face-smile"


def linux_app_entry() -> bool:
    """PISI in the app menu (Linux)."""
    try:
        os.makedirs(os.path.dirname(_APPS_FILE), exist_ok=True)
        run = launch_argv()[0]
        with open(_APPS_FILE, "w", encoding="utf-8") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=PISI\n"
                     "Comment=A desktop cat that keeps you company while you focus\n"
                     f"Exec={desktop_exec([run])}\nIcon={_linux_icon()}\nTerminal=false\n"
                     "Categories=Utility;\n")
        return True
    except OSError:
        log.warning("could not write the app-menu launcher", exc_info=True)
        return False


# ---- Windows Start menu -------------------------------------------------------
def shortcut_path() -> str:
    from . import winapi
    return os.path.join(winapi.start_menu_dir(), SHORTCUT_NAME)


def ensure_start_menu_shortcut() -> bool:
    """Create Start → PISI if it doesn't exist yet (the installer may already
    have made one under the same name)."""
    if not IS_WINDOWS:
        return False
    from . import winapi
    lnk = shortcut_path()
    if os.path.exists(lnk):
        return True
    argv = launch_argv()
    frozen = getattr(sys, "frozen", False)
    icon = argv[0] if frozen else str(app_root() / "assets" / "icon.ico")
    return winapi.create_shortcut(
        lnk, argv[0], subprocess.list2cmdline(argv[1:]),
        workdir=str(app_root() if not frozen else Path(sys.executable).parent),
        icon=icon, description="PISI, a desktop cat that keeps you company while you focus")


def first_run_setup() -> None:
    """Windows has no install.sh step, so the first launch does its job: start
    on sign-in and appear in the Start menu. Both can be undone in Settings /
    with ``--uninstall``. On macOS the packaged app does the same (it was
    dragged to Applications — there's no install step to do it)."""
    if IS_MAC and getattr(sys, "frozen", False):
        if not is_enabled():
            enable()
        return
    if appimage():
        # an AppImage has no install step either: start at sign-in, sit in the
        # app menu, and make the corner clickable on the panel
        if not is_enabled():
            enable()
        linux_app_entry()
        from . import shellext
        if shellext.needed(shellext.desktop()):
            shellext.install()
        return
    if not IS_WINDOWS:
        return
    if not is_enabled():
        enable()
    ensure_start_menu_shortcut()


def uninstall(purge: bool = False) -> list[str]:
    """Remove autostart + launchers (and, with purge, all saved data)."""
    done: list[str] = []
    if disable():
        done.append("autostart entry")
    if IS_WINDOWS:
        try:
            os.remove(shortcut_path())
            done.append("Start menu shortcut")
        except OSError:
            pass
    elif not IS_MAC:
        try:
            os.remove(_APPS_FILE)
            done.append("app-menu launcher")
        except OSError:
            pass
    if purge:
        import shutil

        from .paths import data_dir
        shutil.rmtree(data_dir(), ignore_errors=True)
        done.append("saved data")
    return done
