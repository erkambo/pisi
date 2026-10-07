"""Windows-only system glue, via ctypes + winreg (stdlib — no pywin32 needed).

The Linux build leans on small CLIs (xprintidle, wmctrl, notify-send) and on
/proc + /sys. Windows has none of those, but every one of them has a direct
Win32 equivalent, so this module mirrors them:

    idle_ms()           GetLastInputInfo            (≈ xprintidle)
    fullscreen_busy()   SHQueryUserNotificationState + foreground-window check
    top_windows()       EnumWindows + QueryFullProcessImageNameW   (≈ wmctrl -lxp)
    process_cmdline()   NtQueryInformationProcess + CommandLineToArgvW  (≈ /proc/PID/cmdline)
    autostart_*()       HKCU\\...\\Run registry value  (≈ ~/.config/autostart)

Everything is best-effort: any failure returns None / [] / False, never raises.
Import this module only when ``sys.platform == "win32"``.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

from .log import get_logger

log = get_logger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# Hide the console window of any helper process we spawn (powershell etc.).
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


# ---------------------------------------------------------------------------
# idle time
class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL
kernel32.GetTickCount.restype = wintypes.DWORD


def idle_ms() -> int | None:
    """Milliseconds since the last keyboard/mouse input in this session."""
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return None
        # both are 32-bit tick counts that wrap every ~49.7 days
        return (kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
    except Exception:                        # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# windows
class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetWindow.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.GetShellWindow.restype = wintypes.HWND
# GetWindowLongPtrW doesn't exist in 32-bit user32; GetWindowLongW is fine for
# the style bits we read.
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

GW_OWNER = 4
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CAPTION = 0x00C00000
WS_EX_TOOLWINDOW = 0x00000080
MONITOR_DEFAULTTONEAREST = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DWMWA_CLOAKED = 14

try:
    _dwmapi = ctypes.WinDLL("dwmapi")
    _dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
except OSError:                              # pragma: no cover
    _dwmapi = None


def _text(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _cloaked(hwnd) -> bool:
    """UWP/background windows are 'visible' but cloaked (not on screen)."""
    if _dwmapi is None:
        return False
    val = wintypes.DWORD(0)
    try:
        hr = _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                           ctypes.byref(val), ctypes.sizeof(val))
    except Exception:                        # noqa: BLE001
        return False
    return hr == 0 and val.value != 0


def _pid(hwnd) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def process_path(pid: int) -> str:
    """Full path of a process's executable ('' if we may not ask)."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


# --- command line of another process ---------------------------------------
class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p)]


try:
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG)]
    _ntdll.NtQueryInformationProcess.restype = ctypes.c_long
except OSError:                              # pragma: no cover
    _ntdll = None

shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p

_ProcessCommandLineInformation = 60          # Windows 8.1+


def split_cmdline(cmdline: str) -> list[str]:
    """Split a Windows command line exactly the way programs themselves do."""
    if not cmdline.strip():
        return []
    argc = ctypes.c_int(0)
    argv = shell32.CommandLineToArgvW(cmdline, ctypes.byref(argc))
    if not argv:
        return []
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        kernel32.LocalFree(argv)


def process_cmdline(pid: int) -> list[str]:
    """argv of another (same-user) process, or [] if unavailable."""
    if _ntdll is None:
        return []
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return []
    try:
        need = wintypes.ULONG(0)
        _ntdll.NtQueryInformationProcess(h, _ProcessCommandLineInformation,
                                         None, 0, ctypes.byref(need))
        if not need.value or need.value > 1 << 20:
            return []
        buf = ctypes.create_string_buffer(need.value)
        st = _ntdll.NtQueryInformationProcess(h, _ProcessCommandLineInformation,
                                              buf, need, ctypes.byref(need))
        if st != 0:
            return []
        us = _UNICODE_STRING.from_buffer(buf)
        if not us.Buffer or not us.Length:
            return []
        return split_cmdline(ctypes.wstring_at(us.Buffer, us.Length // 2))
    except Exception:                        # noqa: BLE001
        return []
    finally:
        kernel32.CloseHandle(h)


def top_windows() -> list[dict]:
    """The windows you'd see in Alt-Tab: [{hwnd, title, pid, exe, cls}]."""
    out: list[dict] = []
    me = os.getpid()

    def cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindow(hwnd, GW_OWNER):             # dialogs/popups
                return True
            if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            if _cloaked(hwnd):
                return True
            title = _text(hwnd)
            if not title:
                return True
            pid = _pid(hwnd)
            if pid == me:
                return True
            out.append({"hwnd": int(hwnd or 0), "title": title, "pid": pid,
                        "exe": process_path(pid), "cls": _class(hwnd)})
        except Exception:                    # noqa: BLE001 - keep enumerating
            pass
        return True

    try:
        user32.EnumWindows(_WNDENUMPROC(cb), 0)
    except Exception:                        # noqa: BLE001
        log.info("EnumWindows failed", exc_info=True)
    return out


# ---------------------------------------------------------------------------
# "is the user in a fullscreen game / video / presentation?"
try:
    shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
    shell32.SHQueryUserNotificationState.restype = ctypes.c_long
except AttributeError:                       # pragma: no cover
    pass

# QUNS_BUSY (fullscreen app), QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE
_BUSY_STATES = (2, 3, 4)
_SHELL_CLASSES = ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")


def _foreground_covers_monitor() -> bool:
    """Borderless-fullscreen games/videos don't always flip the shell state, so
    also check: does the foreground window cover its whole monitor?"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd == user32.GetShellWindow():
        return False
    if _class(hwnd) in _SHELL_CLASSES or _pid(hwnd) == os.getpid():
        return False
    # a *maximized* normal window also covers the monitor when the taskbar is
    # auto-hidden — but it keeps its title bar; true fullscreen drops it
    if (user32.GetWindowLongW(hwnd, GWL_STYLE) & WS_CAPTION) == WS_CAPTION:
        return False
    r = _RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(_MONITORINFO)
    if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return False
    m = mi.rcMonitor
    return (r.left <= m.left and r.top <= m.top
            and r.right >= m.right and r.bottom >= m.bottom)


def fullscreen_busy() -> bool:
    try:
        state = ctypes.c_int(0)
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 \
                and state.value in _BUSY_STATES:
            return True
        return _foreground_covers_monitor()
    except Exception:                        # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# app identity (taskbar grouping + our own icon instead of python's)
def set_app_id(app_id: str = "PISI.DesktopCompanion") -> None:
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except Exception:                        # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# start on sign-in (per-user Run key; no admin needed)
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "PISI Desktop Companion"


def autostart_get() -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, RUN_VALUE)
            return str(val)
    except OSError:
        return None


def autostart_set(command: str | None) -> bool:
    """Write (or with None, delete) our Run entry."""
    import winreg
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
            if command is None:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, command)
        return True
    except OSError:
        log.warning("could not update the Run registry key", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Start-menu shortcut (via the WScript.Shell COM object, driven by PowerShell)
def start_menu_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "Microsoft", "Windows", "Start Menu", "Programs")


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def create_shortcut(lnk: str, target: str, args: str = "", workdir: str = "",
                    icon: str = "", description: str = "") -> bool:
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(lnk) + ");"
        "$s.TargetPath=" + _ps_quote(target) + ";"
        "$s.Arguments=" + _ps_quote(args) + ";"
        "$s.WorkingDirectory=" + _ps_quote(workdir) + ";"
        + ("$s.IconLocation=" + _ps_quote(icon) + ";" if icon else "")
        + "$s.Description=" + _ps_quote(description) + ";"
        "$s.Save()"
    )
    try:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            log.warning("shortcut creation failed: %s", r.stderr.strip())
        return r.returncode == 0 and os.path.exists(lnk)
    except (OSError, subprocess.SubprocessError):
        log.warning("could not create shortcut %s", lnk, exc_info=True)
        return False


# ---- staying above the taskbar ----------------------------------------------------
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x1, 0x2, 0x10, 0x200
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = wintypes.BOOL


def keep_on_top(hwnd: int) -> bool:
    """Put a window back at the top of the always-on-top band: the taskbar is
    always-on-top too and jumps in front whenever it's clicked, which would
    hide PISI's corner (it stands in the taskbar's strip). Never activates."""
    try:
        return bool(user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST),
                                        0, 0, 0, 0,
                                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER))
    except Exception:  # noqa: BLE001 - cosmetic; never fail the app over it
        return False
