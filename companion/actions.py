"""Opening files, links and workspaces via the desktop's default handlers."""
from __future__ import annotations

import html
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from .log import get_logger

log = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Set by the app to its tray balloon (QSystemTrayIcon.showMessage). Used on
# Windows, and on Linux when notify-send isn't installed.
_notifier: Callable[[str, str], None] | None = None


def set_notifier(fn: Callable[[str, str], None] | None) -> None:
    global _notifier
    _notifier = fn


def _expand(path: str) -> str:
    path = os.path.expanduser(path.strip())
    return os.path.expandvars(path) if IS_WINDOWS else path   # %USERPROFILE%…


def open_path(path: str) -> bool:
    path = _expand(path)
    if not path:
        return False
    if QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
        return True
    try:  # fallback
        if IS_WINDOWS:
            os.startfile(path)              # noqa: S606 - the user's own file
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except OSError:
        return False


def open_url(url: str) -> bool:
    url = url.strip()
    if not url:
        return False
    if "://" not in url:
        url = "https://" + url
    return QDesktopServices.openUrl(QUrl(url))


def _open_command_windows(cmd: str) -> bool:
    from .winapi import CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW, DETACHED_PROCESS
    cmd = os.path.expandvars(cmd)
    try:
        # A plain command line straight to CreateProcess — handles
        # "C:\Program Files\App\app.exe" "C:\some file.txt" natively.
        subprocess.Popen(cmd, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                         close_fds=True)
        return True
    except OSError:
        pass
    try:
        # Not a bare .exe (e.g. `code C:\dev\proj` is code.cmd, `spotify` lives
        # in App Paths, `ms-settings:` is a URI): `start` goes through
        # ShellExecute, which resolves all of those. No console flashes.
        subprocess.Popen(f'start "" {cmd}', shell=True, creationflags=CREATE_NO_WINDOW,
                         close_fds=True)
        return True
    except OSError:
        log.warning("could not run command %r", cmd, exc_info=True)
        return False


def _open_command_mac(cmd: str) -> bool:
    """An app launched from Finder/login gets a bare PATH (/usr/bin:/bin…), so
    `code ~/proj` (Homebrew / VS Code's shell command) wouldn't be found. Run it
    through the user's login shell, which sets up their real PATH."""
    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        subprocess.Popen([shell, "-lc", cmd], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        log.warning("could not run command %r", cmd, exc_info=True)
        return False


def open_command(cmd: str) -> bool:
    """Launch an app / shell command detached (e.g. `code ~/project`, `spotify`).
    Tries argv first, falls back to the shell for pipes/&&/globs."""
    cmd = cmd.strip()
    if not cmd:
        return False
    if IS_WINDOWS:
        return _open_command_windows(cmd)
    if IS_MAC:
        return _open_command_mac(cmd)
    try:
        subprocess.Popen(shlex.split(cmd), start_new_session=True)
        return True
    except (OSError, ValueError):
        try:
            subprocess.Popen(cmd, shell=True, start_new_session=True)
            return True
        except OSError:
            log.warning("could not run command %r", cmd, exc_info=True)
            return False


def open_workspace(ws: dict) -> None:
    for pth in ws.get("paths", []):
        open_path(pth)
    for u in ws.get("urls", []):
        open_url(u)
    for c in ws.get("cmds", []):
        open_command(c)


def notify(title: str, body: str) -> None:
    if IS_MAC:
        from . import macapi
        if macapi.notify(title, body):
            return
    elif not IS_WINDOWS and shutil.which("notify-send"):
        try:
            # notification daemons read the body as markup: show it as text
            subprocess.Popen(["notify-send", "-a", "PISI", title, html.escape(body, quote=False)])
            return
        except OSError:
            pass
    if _notifier is not None:
        try:
            _notifier(title, body)
        except Exception:                    # noqa: BLE001 - never break a nudge
            log.info("tray notification failed", exc_info=True)
