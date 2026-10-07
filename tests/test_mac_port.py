"""macOS-port logic, tested on any OS: system calls (osascript, pmset, the
LaunchAgent file) are faked and platform switches monkeypatched."""
import sys

import companion.macapi as macapi


# ---- idle ---------------------------------------------------------------------
def test_sysinfo_routes_to_macapi(monkeypatch):
    import companion.sysinfo as si
    monkeypatch.setattr(si, "IS_MAC", True)
    monkeypatch.setattr(si, "IS_WINDOWS", False)
    monkeypatch.setattr(macapi, "idle_ms", lambda: 4321)
    assert si.idle_ms() == 4321


def test_data_dir_is_application_support(tmp_path, monkeypatch):
    import companion.paths as paths
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(paths.os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path), 1))
    monkeypatch.setattr(paths, "IS_MAC", True)
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    assert paths.data_dir() == tmp_path / "Library" / "Application Support" / "desktop-companion"


# ---- AppleScript helpers -------------------------------------------------------
def test_applescript_string_escaping():
    assert macapi.as_string('say "hi" \\ bye') == '"say \\"hi\\" \\\\ bye"'


def test_notify_uses_notification_center(monkeypatch):
    import companion.actions as actions
    got = []
    monkeypatch.setattr(actions, "IS_MAC", True)
    monkeypatch.setattr(macapi, "notify", lambda t, b: got.append((t, b)) or True)
    actions.notify("Coming up", 'Lecture "A"')
    assert got == [("Coming up", 'Lecture "A"')]


def test_commands_run_in_login_shell(monkeypatch):
    """Apps started from Finder get a bare PATH; `code` lives in Homebrew's."""
    import companion.actions as actions
    seen = []
    monkeypatch.setattr(actions, "IS_MAC", True)
    monkeypatch.setattr(actions, "IS_WINDOWS", False)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(actions.subprocess, "Popen", lambda argv, **kw: seen.append(argv))
    assert actions.open_command("code ~/dev/proj")
    assert seen == [["/bin/zsh", "-lc", "code ~/dev/proj"]]


# ---- "save what's open" ------------------------------------------------------------
PROCS = "\n".join([
    "APP\tSafari\t/Applications/Safari.app/",
    "WIN\tSafari\tTwo Sum - LeetCode\t",
    "APP\tPreview\t/System/Applications/Preview.app/",
    "WIN\tPreview\tbook.pdf\tfile:///Users/me/Books/my%20book.pdf",
    "APP\tSpotify\t/Applications/Spotify.app/",
    "WIN\tSpotify\tSpotify Premium\t",
    "APP\tFirefox\t/Applications/Firefox.app/",
    "WIN\tFirefox\tInbox (3) — Mozilla Firefox\t",
    "APP\tFinder\t/System/Library/CoreServices/Finder.app/",
    "APP\tTerminal\t/System/Applications/Utilities/Terminal.app/",
]) + "\n"


def test_mac_snapshot(monkeypatch):
    import companion.windows as win
    monkeypatch.setattr(win, "IS_MAC", True)
    monkeypatch.setattr(win, "IS_WINDOWS", False)

    def fake_osa(src, timeout=60):
        if "System Events" in src:
            return PROCS
        if 'tell application "Safari"' in src:
            assert "current tab" in src
            return "https://leetcode.com/problems/two-sum/\nmissing value\n"
        return None
    monkeypatch.setattr(macapi, "osascript", fake_osa)
    monkeypatch.setattr(win.os.path, "exists",
                        lambda p: p == "/Users/me/Books/my book.pdf")
    import companion.browsers as browsers
    monkeypatch.setattr(browsers, "resolve_titles",
                        lambda ts: {"Inbox (3)": "https://mail.google.com/"} if "Inbox (3)" in ts else {})
    rows = win.snapshot()
    got = {(r["kind"], r["value"], r["suggested"]) for r in rows}
    assert ("url", "https://leetcode.com/problems/two-sum/", True) in got     # real tab URL
    assert ("file", "/Users/me/Books/my book.pdf", True) in got              # Preview's document
    assert ("url", "https://mail.google.com/", True) in got                  # Firefox via history
    spotify = next(r for r in rows if r["kind"] == "app")
    assert spotify["app"] == "open -a /Applications/Spotify.app"
    assert not any(r["app"] in ("Finder", "Terminal") for r in rows)


def test_mac_snapshot_without_permission_is_empty(monkeypatch):
    import companion.windows as win
    monkeypatch.setattr(win, "IS_MAC", True)
    monkeypatch.setattr(win, "IS_WINDOWS", False)
    monkeypatch.setattr(macapi, "osascript", lambda src, timeout=60: None)
    assert win.snapshot() == []


def test_mac_snapshot_browser_denied_falls_back_to_titles(monkeypatch):
    """If Automation access to Safari is refused, keep the tab title as a hint."""
    import companion.windows as win
    monkeypatch.setattr(win, "IS_MAC", True)
    monkeypatch.setattr(win, "IS_WINDOWS", False)
    monkeypatch.setattr(macapi, "osascript",
                        lambda src, timeout=60: PROCS if "System Events" in src else None)
    import companion.browsers as browsers
    monkeypatch.setattr(browsers, "resolve_titles", lambda ts: {})
    rows = win.snapshot()
    assert {"kind": "url", "app": "Safari", "title": "Two Sum - LeetCode",
            "value": "Two Sum - LeetCode", "suggested": False} in rows


# ---- open at login ------------------------------------------------------------------
def test_launch_agent_roundtrip(tmp_path, monkeypatch):
    import companion.autostart as auto
    monkeypatch.setattr(auto, "IS_MAC", True)
    monkeypatch.setattr(auto, "IS_WINDOWS", False)
    monkeypatch.setattr(macapi, "agent_path", lambda: tmp_path / "LaunchAgents" / "x.plist")
    monkeypatch.setattr(auto, "launch_argv", lambda: ["/usr/bin/open", "/Applications/PISI.app"])
    assert not auto.is_enabled()
    assert auto.enable() and auto.is_enabled()
    assert macapi.agent_get() == ["/usr/bin/open", "/Applications/PISI.app"]
    # app moved to ~/Applications: refresh repoints the agent
    monkeypatch.setattr(auto, "launch_argv", lambda: ["/usr/bin/open", "/Users/me/Applications/PISI.app"])
    auto.refresh()
    assert macapi.agent_get() == ["/usr/bin/open", "/Users/me/Applications/PISI.app"]
    assert auto.disable() and not auto.is_enabled()


def test_frozen_mac_launches_the_bundle(monkeypatch):
    import companion.autostart as auto
    monkeypatch.setattr(auto, "IS_MAC", True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/PISI.app/Contents/MacOS/PISI")
    assert auto.launch_argv() == ["/usr/bin/open", "/Applications/PISI.app"]


def test_app_bundle_lookup():
    assert macapi.app_bundle("/Applications/PISI.app/Contents/MacOS/PISI") == "/Applications/PISI.app"
    assert macapi.app_bundle("/usr/bin/python3") is None


def test_float_everywhere_is_a_noop_off_cocoa(qapp):
    """Under the offscreen/xcb platform it must not touch the Objective-C runtime."""
    from PyQt6.QtWidgets import QWidget
    assert macapi.float_everywhere(QWidget()) is None
    assert macapi.hide_dock_icon() is False


def test_window_levels_are_left_alone_off_cocoa(qapp):
    """Off a real Mac (tests run offscreen) the level call must do nothing:
    messaging a non-Cocoa winId would crash."""
    from PyQt6.QtWidgets import QWidget
    from companion import macapi
    w = QWidget()
    assert macapi.ABOVE_DOCK == 21
    assert macapi.set_level(w, macapi.ABOVE_DOCK) is False
