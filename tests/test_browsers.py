"""Tests for browsers.resolve_titles — the title→URL lookup against a browser
history DB. Uses a throwaway SQLite DB shaped like Chromium's History."""
import sqlite3


import companion.browsers as browsers


def _make_chromium_history(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, "
                "title TEXT, last_visit_time INTEGER)")
    con.executemany("INSERT INTO urls (url, title, last_visit_time) VALUES (?,?,?)", [
        ("https://old.example.com/x", "Project X", 100),
        ("https://new.example.com/x", "Project X", 200),   # newer wins
        ("https://docs.google.com/d/1", "My Doc - Google Docs", 150),
    ])
    con.commit()
    con.close()


def test_resolve_picks_most_recent(tmp_path, monkeypatch):
    db = tmp_path / "History"
    _make_chromium_history(db)
    monkeypatch.setattr(browsers, "_chromium_dbs", lambda: [str(db)])
    monkeypatch.setattr(browsers, "_firefox_dbs", lambda: [])
    got = browsers.resolve_titles(["Project X", "My Doc - Google Docs"])
    assert got["Project X"] == "https://new.example.com/x"     # newest visit
    assert got["My Doc - Google Docs"] == "https://docs.google.com/d/1"


def test_resolve_omits_unknown_titles(tmp_path, monkeypatch):
    db = tmp_path / "History"
    _make_chromium_history(db)
    monkeypatch.setattr(browsers, "_chromium_dbs", lambda: [str(db)])
    monkeypatch.setattr(browsers, "_firefox_dbs", lambda: [])
    got = browsers.resolve_titles(["Nothing Like This"])
    assert got == {}


def test_resolve_handles_no_databases(monkeypatch):
    monkeypatch.setattr(browsers, "_chromium_dbs", lambda: [])
    monkeypatch.setattr(browsers, "_firefox_dbs", lambda: [])
    assert browsers.resolve_titles(["anything"]) == {}


def test_resolve_empty_input():
    assert browsers.resolve_titles([]) == {}
