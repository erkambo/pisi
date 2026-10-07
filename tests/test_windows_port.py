"""Windows-port logic, tested on any OS: the Win32 layer (companion.winapi) is
replaced by a fake module, and platform switches are monkeypatched."""
import os
import sys
import types
from datetime import datetime

import pytest

import companion


@pytest.fixture
def fake_winapi(monkeypatch):
    """Install a stand-in for companion.winapi (the real one needs Windows)."""
    w = types.ModuleType("companion.winapi")
    w.CREATE_NO_WINDOW = 0x08000000
    w.DETACHED_PROCESS = 0x8
    w.CREATE_NEW_PROCESS_GROUP = 0x200
    w.run_value = None
    w.autostart_get = lambda: w.run_value
    def _set(cmd):
        w.run_value = cmd
        return True
    w.autostart_set = _set
    w.idle_ms = lambda: 1234
    w.fullscreen_busy = lambda: True
    w.windows = []
    w.cmdlines = {}
    w.top_windows = lambda: list(w.windows)
    w.process_cmdline = lambda pid: w.cmdlines.get(pid, [])
    monkeypatch.setitem(sys.modules, "companion.winapi", w)
    monkeypatch.setattr(companion, "winapi", w, raising=False)
    return w


# ---- strftime: %-H / %-d are glibc-only and raise on Windows ---------------
def test_no_glibc_only_strftime_left():
    root = os.path.dirname(companion.__file__)
    for name in os.listdir(root):
        if name.endswith(".py"):
            src = open(os.path.join(root, name), encoding="utf-8").read()
            for bad in ("%-H", "%-d", "%-m", "%-I", "%-M"):
                assert f"strftime('{bad}" not in src and f'strftime("{bad}' not in src \
                    and f" {bad}\")" not in src, (name, bad)


def test_time_helpers_drop_leading_zero():
    from companion.calendar import fmt_time
    from companion.planner import fmt_time as pfmt
    assert fmt_time(datetime(2026, 1, 2, 9, 5)) == "9:05"
    assert pfmt(datetime(2026, 1, 2, 14, 0)) == "14:00"


# ---- data location ----------------------------------------------------------
def test_data_dir_uses_appdata_on_windows(tmp_path, monkeypatch):
    import companion.paths as paths
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    assert paths.data_dir() == tmp_path / "Roaming" / "desktop-companion"


def test_frozen_assets_come_from_bundle(tmp_path, monkeypatch):
    import companion.paths as paths
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.asset_dir() == tmp_path / "assets"


# ---- system info dispatch ---------------------------------------------------
def test_sysinfo_routes_to_winapi(fake_winapi, monkeypatch):
    import companion.sysinfo as si
    monkeypatch.setattr(si, "IS_WINDOWS", True)
    assert si.idle_ms() == 1234
    assert si.fullscreen_busy() is True


def test_fullscreen_guard_is_off_elsewhere(monkeypatch):
    import companion.sysinfo as si
    monkeypatch.setattr(si, "IS_WINDOWS", False)
    monkeypatch.setattr(si, "IS_MAC", False)
    assert si.fullscreen_busy() is False


# ---- launching things -------------------------------------------------------
def test_open_command_windows_uses_createprocess_then_start(fake_winapi, monkeypatch):
    import companion.actions as actions
    calls = []

    def fake_popen(cmd, **kw):
        calls.append((cmd, kw))
        if not kw.get("shell"):
            raise FileNotFoundError(cmd)     # e.g. `code` is code.cmd, not an .exe
        return object()
    monkeypatch.setattr(actions, "IS_WINDOWS", True)
    monkeypatch.setattr(actions.subprocess, "Popen", fake_popen)
    assert actions.open_command(r"code C:\dev\proj")
    assert calls[0][0] == r"code C:\dev\proj"             # CreateProcess first
    assert calls[1][0] == r'start "" code C:\dev\proj'     # then ShellExecute
    assert calls[1][1]["creationflags"] == fake_winapi.CREATE_NO_WINDOW


def test_open_command_windows_keeps_backslashes(fake_winapi, monkeypatch):
    """shlex (POSIX rules) would eat the backslashes of a Windows path."""
    import companion.actions as actions
    seen = []
    monkeypatch.setattr(actions, "IS_WINDOWS", True)
    monkeypatch.setattr(actions.subprocess, "Popen", lambda cmd, **kw: seen.append(cmd))
    exe = r'"C:\Program Files\Spotify\Spotify.exe"'
    assert actions.open_command(exe)
    assert seen == [exe]


def test_notify_falls_back_to_tray(monkeypatch):
    import companion.actions as actions
    got = []
    monkeypatch.setattr(actions, "IS_WINDOWS", True)
    monkeypatch.setattr(actions, "IS_MAC", False)
    actions.set_notifier(lambda t, b: got.append((t, b)))
    try:
        actions.notify("Hi", "there")
    finally:
        actions.set_notifier(None)
    assert got == [("Hi", "there")]


# ---- "save what's open" on Windows -------------------------------------------
def test_edge_title_cleanup_and_variants():
    from companion.windows import _clean_browser_title, _title_variants
    t = "LeetCode - The World's Leading Platform and 3 more pages - Personal - Microsoft\u200b Edge"
    assert _clean_browser_title("Inbox - Google Chrome") == "Inbox"
    v = _title_variants(t)
    assert "LeetCode - The World's Leading Platform" in v
    assert _clean_browser_title("Docs — Mozilla Firefox") == "Docs"


def test_windows_snapshot_classifies_rows(fake_winapi, monkeypatch, tmp_path):
    import companion.windows as win
    book = tmp_path / "book.pdf"
    book.write_text("x")
    fake_winapi.windows = [
        {"hwnd": 1, "title": "book.pdf - Adobe Acrobat", "pid": 10,
         "exe": r"C:\Program Files\Adobe\Acrobat.exe", "cls": "AcrobatSDIWindow"},
        {"hwnd": 2, "title": "Two Sum - LeetCode - Google Chrome", "pid": 11,
         "exe": r"C:\Program Files\Google\Chrome\Application\chrome.exe", "cls": "Chrome"},
        {"hwnd": 3, "title": "Spotify Premium", "pid": 12,
         "exe": r"C:\Users\me\AppData\Roaming\Spotify\Spotify.exe", "cls": "Chrome"},
        {"hwnd": 4, "title": "File Explorer", "pid": 13,
         "exe": r"C:\Windows\explorer.exe", "cls": "CabinetWClass"},
    ]
    # pretend `book` is an absolute Windows path
    winpath = "C:\\Users\\me\\book.pdf"
    fake_winapi.cmdlines = {10: ["Acrobat.exe", winpath]}
    real_exists, real_isfile = os.path.exists, os.path.isfile
    monkeypatch.setattr(win.os.path, "exists", lambda p: p == winpath or real_exists(p))
    monkeypatch.setattr(win.os.path, "isfile", lambda p: p == winpath or real_isfile(p))
    monkeypatch.setattr(win, "IS_WINDOWS", True)
    import companion.browsers as browsers
    monkeypatch.setattr(browsers, "resolve_titles",
                        lambda ts: {"Two Sum - LeetCode": "https://leetcode.com/problems/two-sum/"}
                        if "Two Sum - LeetCode" in ts else {})
    rows = win.snapshot()
    kinds = [(r["kind"], r["value"]) for r in rows]
    assert ("file", winpath) in kinds
    assert ("url", "https://leetcode.com/problems/two-sum/") in kinds
    app = next(r for r in rows if r["kind"] == "app")
    assert app["app"] == r'"C:\Users\me\AppData\Roaming\Spotify\Spotify.exe"'
    assert all("explorer" not in r["app"] for r in rows)     # shell windows skipped
    assert all("_variants" not in r for r in rows)           # internal key removed


def test_windows_argv_ignores_program_files(monkeypatch):
    import companion.windows as win
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setattr(win.os.path, "exists", lambda p: True)
    monkeypatch.setattr(win.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(win.os.path, "normcase", lambda p: p.lower())
    monkeypatch.setattr(win.os, "sep", "\\")
    got = win._win_file_from_argv(
        ["app.exe", "--flag", r"C:\Program Files\App\plugin.dll", r"D:\notes\todo.txt"])
    assert got == r"D:\notes\todo.txt"
    assert win._win_file_from_argv(["app.exe", "--new-window"]) is None


def test_dialog_recognises_windows_paths():
    from companion.dialogs import _as_item
    assert _as_item(r"C:\Users\me\book.pdf") == ("file", r"C:\Users\me\book.pdf")
    assert _as_item("D:/music/a.mp3")[0] == "file"
    assert _as_item(r"\\nas\share\x.docx")[0] == "file"
    assert _as_item("Spotify Premium") is None


# ---- start at sign-in ----------------------------------------------------------
def test_autostart_windows_registry_roundtrip(fake_winapi, monkeypatch):
    import companion.autostart as auto
    monkeypatch.setattr(auto, "IS_WINDOWS", True)
    monkeypatch.setattr(auto, "IS_MAC", False)
    monkeypatch.setattr(auto, "launch_argv", lambda: [r"C:\PISI\PISI.exe"])
    assert not auto.is_enabled()
    auto.enable()
    assert fake_winapi.run_value == r"C:\PISI\PISI.exe"
    assert auto.is_enabled()
    # the .exe got moved: refresh() repoints the Run entry
    monkeypatch.setattr(auto, "launch_argv", lambda: [r"D:\Apps\PISI\PISI.exe"])
    auto.refresh()
    assert fake_winapi.run_value == r"D:\Apps\PISI\PISI.exe"
    auto.disable()
    assert fake_winapi.run_value is None


def test_autostart_quotes_paths_with_spaces(fake_winapi, monkeypatch):
    import companion.autostart as auto
    monkeypatch.setattr(auto, "IS_WINDOWS", True)
    monkeypatch.setattr(auto, "IS_MAC", False)
    monkeypatch.setattr(auto, "launch_argv",
                        lambda: [r"C:\Users\A B\.venv\Scripts\pythonw.exe", r"C:\Users\A B\pisi.pyw"])
    auto.enable()
    assert fake_winapi.run_value == \
        r'"C:\Users\A B\.venv\Scripts\pythonw.exe" "C:\Users\A B\pisi.pyw"'


def test_autostart_linux_desktop_file(tmp_path, monkeypatch):
    import companion.autostart as auto
    f = tmp_path / "autostart" / "desktop-companion.desktop"
    monkeypatch.setattr(auto, "IS_WINDOWS", False)
    monkeypatch.setattr(auto, "IS_MAC", False)
    monkeypatch.setattr(auto, "_DESKTOP_FILE", str(f))
    assert auto.set_enabled(True) and f.exists() and auto.is_enabled()
    assert "run.sh" in f.read_text("utf-8")
    assert auto.set_enabled(False) and not f.exists()


def test_frozen_launch_is_just_the_exe(monkeypatch):
    import companion.autostart as auto
    monkeypatch.setattr(auto, "IS_MAC", False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert auto.launch_argv() == [sys.executable]


# ---- storage robustness ----------------------------------------------------------
def test_store_save_retries_when_file_briefly_locked(monkeypatch):
    import companion.store as store_mod
    s = store_mod.Store()
    real = os.replace
    fails = {"n": 2}

    def flaky(a, b):
        if fails["n"]:
            fails["n"] -= 1
            raise PermissionError("in use by another process")
        return real(a, b)
    monkeypatch.setattr(store_mod.os, "replace", flaky)
    monkeypatch.setattr(store_mod.time, "sleep", lambda s: None)
    s.set_config("cat_name", "Tekir")
    assert store_mod.Store().config["cat_name"] == "Tekir"


# ---- single instance ---------------------------------------------------------------
def test_second_launch_pokes_the_first(qapp, monkeypatch):
    """A real second process (as when the Start-menu icon is clicked again)
    must hand its message to the running one — on Windows too (named pipes)."""
    import subprocess
    import time

    from PyQt6.QtCore import QEventLoop

    import companion.__main__ as cli
    name = f"pisitest{os.getpid()}"
    monkeypatch.setattr(cli, "_server_name", lambda: name)
    assert cli._poke_running(b"show") is False          # nobody listening yet
    got = []
    server = cli._listen(got.append)
    assert server is not None
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("from PyQt6.QtCore import QCoreApplication; import sys; "
            "a = QCoreApplication(sys.argv); import companion.__main__ as c; "
            f"c._server_name = lambda: {name!r}; "
            "print(c._poke_running(b'show'))")
    child = subprocess.Popen([sys.executable, "-c", code], cwd=root,
                             stdout=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 15
    while (not got or child.poll() is None) and time.monotonic() < deadline:
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)
    out = child.communicate(timeout=10)[0]
    server.close()
    assert got == ["show"]
    assert out.strip() == "True"


# ---- the cat on a fresh install ---------------------------------------------------
def test_a_fresh_install_draws_its_own_cat(qapp):
    import companion.pixelsheet as ps
    sheet = ps.load({})
    assert sheet is not None and sheet.procedural
    assert {"sit", "walk", "sleep", "turn"} <= set(sheet.anims)
