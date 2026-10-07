"""Tests for the stdlib Google Calendar OAuth logic (no real network)."""
import time

from companion import gcal
from companion.gcal import GoogleCalendar, _pkce, _b64url
from companion.store import Store


def _store_with_creds():
    s = Store()
    s.config["google_client_id"] = "cid.apps.googleusercontent.com"
    s.config["google_client_secret"] = "secret"
    return s


def test_pkce_challenge_is_url_safe_and_deterministic():
    v, c = _pkce()
    import hashlib
    expected = _b64url(hashlib.sha256(v.encode()).digest())
    assert c == expected
    assert "=" not in c and "+" not in c and "/" not in c   # url-safe, unpadded


def _no_builtin(monkeypatch):
    monkeypatch.setattr(gcal, "BUILTIN_ID", "")
    monkeypatch.setattr(gcal, "BUILTIN_SECRET", "")


def test_credentials_and_connected_flags(monkeypatch):
    _no_builtin(monkeypatch)
    g = GoogleCalendar(Store())
    assert g.has_credentials() is False
    g = GoogleCalendar(_store_with_creds())
    assert g.has_credentials() is True
    assert g.connected() is False                            # no refresh token yet


def test_access_token_refreshes_when_expired(monkeypatch):
    g = GoogleCalendar(_store_with_creds())
    g._token = {"refresh_token": "rt", "access_token": "old", "expiry": 0}  # expired

    calls = {}
    def fake_post(url, fields):
        calls["grant"] = fields["grant_type"]
        return {"access_token": "fresh", "expires_in": 3600}
    monkeypatch.setattr(gcal, "_post_form", fake_post)

    tok = g._access_token()
    assert tok == "fresh"
    assert calls["grant"] == "refresh_token"
    # a subsequent call reuses the cached, still-valid token (no second refresh)
    calls.clear()
    assert g._access_token() == "fresh"
    assert calls == {}


def test_refresh_flags_expired_on_invalid_grant(monkeypatch, tmp_path):
    """A revoked/expired refresh token (invalid_grant) must drop the token and
    flag a reconnect — not silently keep failing while connected() reports True."""
    import io
    import urllib.error

    # keep the unlink of the (fake) token file harmless
    monkeypatch.setattr(gcal, "google_token_file", lambda: tmp_path / "tok.json")

    g = GoogleCalendar(_store_with_creds())
    g._token = {"refresh_token": "dead", "access_token": "old", "expiry": 0}

    def boom(url, fields):
        raise urllib.error.HTTPError(
            url, 400, "Bad Request", {},
            io.BytesIO(b'{"error":"invalid_grant","error_description":"revoked"}'))
    monkeypatch.setattr(gcal, "_post_form", boom)

    assert g._access_token() is None
    assert g.expired is True
    assert g.connected() is False            # token dropped, no longer "connected"


def test_refresh_transient_error_keeps_token(monkeypatch):
    """A transient failure (offline, 5xx) must NOT discard the token or flag
    expiry — we just retry later."""
    import io
    import urllib.error

    g = GoogleCalendar(_store_with_creds())
    g._token = {"refresh_token": "rt", "access_token": "old", "expiry": 0}

    def boom(url, fields):
        raise urllib.error.HTTPError(url, 503, "Server Error", {}, io.BytesIO(b""))
    monkeypatch.setattr(gcal, "_post_form", boom)

    assert g._access_token() is None
    assert g.expired is False
    assert g.connected() is True             # still have the refresh token


def test_ensure_pisi_calendar_creates_when_absent(monkeypatch):
    g = GoogleCalendar(_store_with_creds())
    g._token = {"refresh_token": "rt", "access_token": "t",
                "expiry": time.time() + 9999}
    seen = {}

    def fake_api(method, path, body=None):
        if method == "GET" and path == "/users/me/calendarList":
            return {"items": [{"id": "primary", "summary": "erkam@x"}]}  # no PISI
        if method == "POST" and path == "/calendars":
            seen["created"] = body["summary"]
            return {"id": "pisi123"}
        raise AssertionError((method, path))
    monkeypatch.setattr(g, "_api", fake_api)

    cid = g.ensure_pisi_calendar()
    assert cid == "pisi123"
    assert seen["created"] == "PISI"
    assert g.calendar_id() == "pisi123"
    # cached: a second call doesn't hit the API again
    monkeypatch.setattr(g, "_api", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert g.ensure_pisi_calendar() == "pisi123"


def test_ensure_pisi_calendar_reuses_existing(monkeypatch):
    g = GoogleCalendar(_store_with_creds())
    g._token = {"refresh_token": "rt", "access_token": "t",
                "expiry": time.time() + 9999}

    def fake_api(method, path, body=None):
        assert method == "GET"
        return {"items": [{"id": "found", "summary": "PISI"}]}
    monkeypatch.setattr(g, "_api", fake_api)
    assert g.ensure_pisi_calendar() == "found"


def test_add_event_posts_with_pisi_marker(monkeypatch):
    from datetime import datetime, timedelta
    g = GoogleCalendar(_store_with_creds())
    g._token = {"refresh_token": "rt", "access_token": "t",
                "expiry": time.time() + 9999, "pisi_calendar_id": "cal@x"}
    captured = {}

    def fake_api(method, path, body=None):
        captured["method"] = method
        captured["path"] = path
        captured["body"] = body
        return {"id": "ev1"}
    monkeypatch.setattr(g, "_api", fake_api)

    start = datetime.now().astimezone()
    g.add_event("Focus: ECE", start, start + timedelta(minutes=50),
                key="2026-09-10|focus|ECE", kind="focus")
    assert captured["method"] == "POST"
    assert "cal%40x/events" in captured["path"]     # calendar id url-encoded
    priv = captured["body"]["extendedProperties"]["private"]
    assert priv["pisi"] == "1" and priv["kind"] == "focus"
    assert "dateTime" in captured["body"]["start"]


def test_taken_keys_extracts_private_keys(monkeypatch):
    from datetime import datetime, timedelta
    g = GoogleCalendar(_store_with_creds())
    g._token = {"refresh_token": "rt", "pisi_calendar_id": "c"}
    monkeypatch.setattr(g, "list_pisi_events", lambda a, b: [
        {"extendedProperties": {"private": {"pisi": "1", "key": "k1"}}},
        {"extendedProperties": {"private": {"pisi": "1", "key": "k2"}}},
        {"extendedProperties": {"private": {"pisi": "1"}}},   # no key
    ])
    now = datetime.now().astimezone()
    assert g.taken_keys(now, now + timedelta(days=1)) == {"k1", "k2"}


def test_status_line_progression(monkeypatch):
    _no_builtin(monkeypatch)
    assert "add" in GoogleCalendar(Store()).status_line().lower()
    g = GoogleCalendar(_store_with_creds())
    assert "not connected" in g.status_line().lower()
    g._token = {"refresh_token": "rt"}
    assert "connected" in g.status_line().lower()


# ---- trusted by default: the narrowest permission, PISI's own client ---------
def test_asks_only_for_its_own_calendar():
    assert gcal.SCOPE == "https://www.googleapis.com/auth/calendar.app.created"


def test_pisi_own_client_connects_with_nothing_to_paste(monkeypatch):
    monkeypatch.setattr(gcal, "BUILTIN_ID", "pisi.apps.googleusercontent.com")
    monkeypatch.setattr(gcal, "BUILTIN_SECRET", "s")
    g = GoogleCalendar(Store())
    assert g.built_in() and g.has_credentials()
    assert g._client() == ("pisi.apps.googleusercontent.com", "s")
    own = GoogleCalendar(_store_with_creds())               # your own client still wins
    assert own._client() == ("cid.apps.googleusercontent.com", "secret")


def test_a_token_from_another_client_asks_for_one_reconnect(monkeypatch):
    monkeypatch.setattr(gcal, "BUILTIN_ID", "pisi.apps.googleusercontent.com")
    monkeypatch.setattr(gcal, "BUILTIN_SECRET", "s")
    # connected before, with your own client (an older PISI didn't record which)
    s = _store_with_creds()
    g = GoogleCalendar(s)
    g._token = {"refresh_token": "rt"}
    assert g.connected() and not g.needs_reconnect()        # still yours: keeps working
    s.config["google_client_id"] = ""                       # back to PISI's own client
    s.config["google_client_secret"] = ""
    assert not g.connected() and g.needs_reconnect()
    assert "connect once more" in g.status_line().lower()
    g._token = {"refresh_token": "rt2", "client_id": "pisi.apps.googleusercontent.com"}
    assert g.connected() and not g.needs_reconnect()


def test_the_calendar_is_created_when_it_cannot_list_calendars(monkeypatch):
    import urllib.error
    g = GoogleCalendar(_store_with_creds())
    g._token = {"refresh_token": "rt"}
    calls = []

    def api(method, path, body=None):
        calls.append((method, path))
        if path == "/users/me/calendarList":
            raise urllib.error.HTTPError(path, 403, "insufficient scope", {}, None)
        return {"id": "pisi-cal"}
    monkeypatch.setattr(g, "_api", api)
    monkeypatch.setattr(g, "_save_token", lambda: None)
    assert g.ensure_pisi_calendar() == "pisi-cal"
    assert ("POST", "/calendars") in calls


def test_a_release_build_bakes_the_client_in_and_git_never_sees_it(tmp_path, monkeypatch):
    import importlib.util
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("stage", root / "scripts" / "stage_google_client.py")
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    out = tmp_path / "_google_client.py"
    monkeypatch.setattr(stage, "OUT", out)
    monkeypatch.delenv("PISI_GOOGLE_CLIENT_ID", raising=False)
    assert stage.main() == 0 and not out.exists()              # no secrets: nothing baked
    monkeypatch.setenv("PISI_GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("PISI_GOOGLE_CLIENT_SECRET", "shh")
    assert stage.main() == 0
    ns: dict = {}
    exec(out.read_text(), ns)
    assert (ns["CLIENT_ID"], ns["CLIENT_SECRET"]) == ("abc.apps.googleusercontent.com", "shh")
    ignored = subprocess.run(["git", "check-ignore", "companion/_google_client.py"], cwd=root,
                             capture_output=True, text=True)
    assert ignored.returncode == 0                              # never committed


def test_pisi_own_client_typed_into_settings_is_not_your_own(monkeypatch):
    monkeypatch.setattr(gcal, "BUILTIN_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(gcal, "BUILTIN_SECRET", "secret")
    g = GoogleCalendar(_store_with_creds())                  # the very same client, typed in
    assert not g.uses_own_client()                           # Settings shows just Connect
    other = _store_with_creds()
    other.config["google_client_id"] = "mine.apps.googleusercontent.com"
    assert GoogleCalendar(other).uses_own_client()


def test_an_older_token_is_stamped_with_the_client_that_made_it(monkeypatch, tmp_path):
    import json
    tok = tmp_path / "google_token.json"
    tok.write_text(json.dumps({"refresh_token": "rt", "pisi_calendar_id": "cal"}))
    monkeypatch.setattr(gcal, "google_token_file", lambda: tok)
    monkeypatch.setattr(gcal, "BUILTIN_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(gcal, "BUILTIN_SECRET", "secret")
    s = _store_with_creds()
    g = GoogleCalendar(s)
    assert json.loads(tok.read_text())["client_id"] == "cid.apps.googleusercontent.com"
    s.config["google_client_id"] = ""                        # Settings cleared: PISI's own client
    s.config["google_client_secret"] = ""
    assert g.connected() and g.calendar_id() == "cal"        # same client: nothing to redo


def test_the_page_after_google_says_what_happened():
    ok = gcal._result_page(True)
    assert "PISI is connected" in ok and "data:image/png;base64," in ok
    assert "other calendars" in ok
    no = gcal._result_page(False)
    assert "Not connected" in no and "PISI is connected" not in no and "Connect" in no
