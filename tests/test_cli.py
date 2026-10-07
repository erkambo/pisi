"""Tests for the `--open <habit>` one-shot in __main__ (open a setup and exit).
The Qt bits are stubbed so no event loop spins and nothing actually launches."""
import pytest

import companion.__main__ as cli
from helpers import sample_store


class _FakeApp:
    def __init__(self, *a): pass
    def exec(self): return 0
    def quit(self): pass


@pytest.fixture(autouse=True)
def _stub_qt(monkeypatch):
    monkeypatch.setattr(cli, "QApplication", _FakeApp)
    monkeypatch.setattr(cli.QTimer, "singleShot", staticmethod(lambda ms, fn: None))


def test_open_missing_habit_returns_2(capsys):
    assert cli._open_setup("No Such Habit") == 2
    assert "No habit named" in capsys.readouterr().out


def test_open_habit_without_setup_returns_1():
    s = sample_store()
    name = s.habits[0]["name"]            # seeded, no setup attached
    assert cli._open_setup(name) == 1


def test_open_habit_with_setup_launches_and_returns_0(monkeypatch):
    import companion.actions as actions
    s = sample_store()
    hid = s.habits[0]["id"]
    s.set_habit_workspace(hid, ["/tmp/x.pdf"], ["https://x"], ["code ~/p"])
    opened = {}
    monkeypatch.setattr(actions, "open_workspace", lambda ws: opened.update(ws))
    rc = cli._open_setup(s.habits[0]["name"])
    assert rc == 0
    assert opened["cmds"] == ["code ~/p"] and opened["urls"] == ["https://x"]


def test_open_is_case_insensitive():
    s = sample_store()
    hid = s.habits[0]["id"]
    s.set_habit_workspace(hid, [], ["https://x"])
    assert cli._open_setup(s.habits[0]["name"].upper()) == 0
