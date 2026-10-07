"""Things that keep your data yours (see the security sweep in 1.4)."""
from __future__ import annotations

import os
import stat
import sys

import pytest

posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")


@posix
def test_sockets_live_in_this_users_own_folder(tmp_path, monkeypatch):
    from companion import paths
    monkeypatch.setattr(paths, "IS_MAC", False)
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    assert paths.private_socket("pisi-x") == str(run / "pisi-x")
    run.chmod(0o755)                        # not private: back to the bare name
    assert paths.private_socket("pisi-x") == "pisi-x"
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert paths.private_socket("pisi-x") == "pisi-x"


@posix
def test_the_data_folder_is_private(tmp_path, monkeypatch):
    from companion import paths
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d = paths.data_dir()
    assert stat.S_IMODE(d.stat().st_mode) == 0o700


@posix
def test_google_tokens_are_never_world_readable(tmp_path):
    from companion.gcal import _write_private
    p = tmp_path / "google-token.json"
    p.write_text("old")
    os.chmod(p, 0o644)
    _write_private(p, '{"refresh_token": "x"}')
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and "refresh_token" in p.read_text()


def test_calendar_addresses_are_http_only_and_never_logged_whole():
    from companion.calendar import CalendarService, _safe

    class S:
        config = {"ical_url": "webcal://cal.example.com/private-abc123/basic.ics\n"
                              "file:///etc/passwd, https://x.example.org/a.ics"}
    cal = CalendarService.__new__(CalendarService)
    cal.store = S()
    assert cal.urls() == ["https://cal.example.com/private-abc123/basic.ics",
                          "https://x.example.org/a.ics"]
    assert _safe("https://cal.example.com/private-abc123/basic.ics") == "https://cal.example.com/…"


def test_the_doctor_report_keeps_window_titles_out():
    from companion.doctor import window_summary
    status, detail = window_summary([{"kind": "url", "value": "Secret project plan - Docs"},
                                     {"kind": "file", "value": "/home/u/diary.txt"}])
    assert status == "OK" and "Secret" not in detail and "diary" not in detail
    assert "2 windows" in detail
