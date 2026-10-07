"""Google Calendar two-way access (Option B) — stdlib only, no pip deps.

Read-only iCal (Option A, see calendar.py) needs no login. Writing to your
calendar needs OAuth, which this module implements by hand over urllib +
http.server using the loopback flow recommended for installed/"Desktop" apps:

    connect() → open the browser → you consent → Google redirects to a tiny
    local server on 127.0.0.1 → we exchange the code for tokens → store them.

PKCE (S256) is used, and the refresh token is kept in a local file (0600) so we
can mint access tokens later without asking again. All traffic is Google-only.

Design choices that keep it trustworthy:
* We only ever write to a dedicated secondary calendar named "PISI" that this
  app creates — never your academic/personal calendars.
* Nothing is written without explicit user consent (that lives in the caller).

It asks Google for the narrowest calendar permission there is (make its own
calendar, manage events on it), and uses PISI's own OAuth client in release
builds, so connecting is one click.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any
from collections.abc import Callable

from .log import get_logger
from .paths import asset_dir, google_token_file

log = get_logger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
# The least PISI needs: make its own "PISI" calendar and manage the events on
# it. Nothing else of yours is visible to it (your schedule is read through
# the iCal address instead).
SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
PISI_CALENDAR_NAME = "PISI"

# PISI's own OAuth client, baked into release builds from a CI secret
# (scripts/stage_google_client.py writes companion/_google_client.py, which is
# never in git). A copy run from source has none: it uses the client ID and
# secret in Settings instead. For a desktop app Google doesn't treat the
# "secret" as secret; it ships inside the app.
try:
    from ._google_client import CLIENT_ID as BUILTIN_ID, CLIENT_SECRET as BUILTIN_SECRET
except ImportError:
    BUILTIN_ID = BUILTIN_SECRET = ""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _write_private(path, text: str) -> None:
    """Write a file only this user can read, created that way (no moment
    where the token sits in a world-readable file), replaced in one step."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600)                  # (an older tmp file kept its mode)
    os.replace(tmp, path)


def _pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(40))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PISI · {title}</title>
<style>
:root {{ --bg: #fffaf2; --card: #ffffff; --ink: #2b2620; --quiet: #6d655c; --line: #e6dccd;
        --accent: {accent}; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #1f1b18; --card: #2a2420; --ink: #f1ebe2; --quiet: #b3a99c; --line: #3d362f; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px;
       background: var(--bg); color: var(--ink);
       font: 17px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
.card {{ width: 100%; max-width: 440px; text-align: center; background: var(--card);
        border: 1px solid var(--line); border-radius: 18px; padding: 36px 28px 30px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, .08); }}
img {{ width: 112px; height: 112px; image-rendering: pixelated; border-radius: 20px; }}
h1 {{ font-size: 24px; margin: 18px 0 6px; }}
.mark {{ display: inline-grid; place-items: center; width: 26px; height: 26px; margin-right: 6px;
        border-radius: 50%; background: var(--accent); color: #fff; font-size: 15px;
        vertical-align: 3px; }}
p {{ margin: 6px 0; color: var(--quiet); }}
.small {{ font-size: 14px; margin-top: 18px; }}
</style></head>
<body><main class="card">
  {img}
  <h1><span class="mark">{mark}</span>{title}</h1>
  {body}
  <p class="small">You can close this tab and go back to PISI.</p>
</main>
<script>setTimeout(function () {{ window.close(); }}, 4000);</script>
</body></html>"""


def _result_page(ok: bool) -> str:
    """What the browser shows when Google sends you back to PISI."""
    import html
    try:
        data = (asset_dir() / "icon.png").read_bytes()
        img = ('<img alt="PISI, a black pixel cat" src="data:image/png;base64,'
               + base64.b64encode(data).decode("ascii") + '">')
    except OSError:
        img = ""
    if ok:
        title, mark, accent = "PISI is connected", "\u2713", "#2e9e5b"
        body = ("<p>Your finished focus blocks and the plans you approve will go on a "
                "calendar of its own called <b>PISI</b> in your Google Calendar.</p>"
                "<p>It can't see or change your other calendars.</p>")
    else:
        title, mark, accent = "Not connected", "!", "#c0392b"
        body = ("<p>Google sign-in was cancelled, so nothing changed.</p>"
                "<p>To try again, open PISI's Settings and click <b>Connect</b>.</p>")
    return _PAGE.format(title=html.escape(title), mark=mark, accent=accent, img=img, body=body)


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


class GoogleCalendar:
    def __init__(self, store) -> None:
        self.store = store
        self._token: dict = {}          # {refresh_token, access_token, expiry, ...}
        self._lock = threading.Lock()
        self.expired = False            # set when Google rejects the refresh token
                                        # (invalid_grant) so the app can nudge a
                                        # reconnect once; cleared on (dis)connect
        self._load_token()

    # ---- config / credentials ---------------------------------------
    def _own_client(self) -> tuple[str, str]:
        cfg = self.store.config
        return ((cfg.get("google_client_id") or "").strip(),
                (cfg.get("google_client_secret") or "").strip())

    def _client(self) -> tuple[str, str]:
        """Your own client if you entered one (advanced), else PISI's."""
        cid, csec = self._own_client()
        if cid and csec:
            return cid, csec
        return BUILTIN_ID, BUILTIN_SECRET

    @staticmethod
    def built_in() -> bool:
        """Whether this copy of PISI ships with its own Google client."""
        return bool(BUILTIN_ID and BUILTIN_SECRET)

    def has_credentials(self) -> bool:
        cid, csec = self._client()
        return bool(cid and csec)

    def _token_client(self) -> str:
        return self._token.get("client_id") or self._own_client()[0]

    def uses_own_client(self) -> bool:
        """A client of your own is set in Settings (not just PISI's own
        client typed in by hand)."""
        cid = self._own_client()[0]
        return bool(cid) and cid != BUILTIN_ID

    def connected(self) -> bool:
        return bool(self._token.get("refresh_token")) and \
            self._token_client() == self._client()[0]

    def needs_reconnect(self) -> bool:
        """Connected once, but with another client (PISI now has its own, or
        you changed yours): Google won't accept that token any more."""
        return bool(self._token.get("refresh_token")) and not self.connected()

    def calendar_id(self) -> str | None:
        return self._token.get("pisi_calendar_id")

    # ---- token persistence ------------------------------------------
    def _load_token(self) -> None:
        try:
            p = google_token_file()
            if p.exists():
                self._token = json.loads(p.read_text("utf-8"))
        except Exception:
            log.warning("could not read stored Google token", exc_info=True)
            self._token = {}
        if self._token.get("refresh_token") and not self._token.get("client_id"):
            # an older PISI didn't record which client signed in: it was the
            # one in Settings then
            own = self._own_client()[0]
            if own:
                self._token["client_id"] = own
                self._save_token()

    def _save_token(self) -> None:
        try:
            _write_private(google_token_file(), json.dumps(self._token))
        except Exception:
            log.warning("could not save Google token", exc_info=True)

    def disconnect(self) -> None:
        self._token = {}
        self.expired = False
        try:
            google_token_file().unlink(missing_ok=True)
        except Exception:
            pass

    # ---- OAuth loopback connect flow --------------------------------
    def connect(self, on_status: Callable[[str], None]) -> None:
        """Run the browser consent flow on a background thread. Calls
        on_status(msg) as it progresses (safe to marshal to the GUI)."""
        if not self.has_credentials():
            on_status("Add your Google client ID and secret first.")
            return
        threading.Thread(target=self._connect_worker, args=(on_status,),
                          daemon=True).start()

    def _connect_worker(self, on_status: Callable[[str], None]) -> None:
        cid, csec = self._client()
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(16)
        captured: dict = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):        # silence
                pass

            def do_GET(self):
                q = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(q)
                if not ("code" in params or "error" in params):
                    self.send_response(404)       # not the sign-in redirect
                    self.end_headers()
                    return
                captured["code"] = params.get("code", [None])[0]
                captured["state"] = params.get("state", [None])[0]
                captured["error"] = params.get("error", [None])[0]
                ok = bool(captured["code"]) and captured["state"] == state
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_result_page(ok).encode("utf-8"))

        try:
            server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        except Exception as e:            # noqa: BLE001
            on_status(f"Couldn't open local port: {e}")
            return
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}"

        auth = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        })
        on_status("Opening your browser to sign in…")
        try:
            webbrowser.open(auth)
        except Exception:
            log.warning("could not open browser for OAuth", exc_info=True)

        # wait for the redirect itself: a browser may ask for /favicon.ico
        # first, and anything else that knocks on the port is ignored
        deadline = time.monotonic() + 180
        while "code" not in captured and time.monotonic() < deadline:
            server.timeout = max(1.0, deadline - time.monotonic())
            server.handle_request()
        server.server_close()

        if captured.get("error"):
            on_status(f"Sign-in was declined ({captured['error']}).")
            return
        if not captured.get("code") or captured.get("state") != state:
            on_status("Sign-in didn't complete. Try again.")
            return

        try:
            tok = _post_form(TOKEN_URL, {
                "client_id": cid,
                "client_secret": csec,
                "code": captured["code"],
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            })
        except urllib.error.HTTPError as e:
            log.warning("OAuth token exchange failed (HTTP %s)", e.code)
            on_status(f"Token exchange failed (HTTP {e.code}).")
            return
        except Exception as e:            # noqa: BLE001
            log.warning("OAuth token exchange failed", exc_info=True)
            on_status(f"Token exchange failed: {e}")
            return

        with self._lock:
            same = self._token_client() == cid
            keep = self._token.get("pisi_calendar_id") if same else None
            self._token = {"refresh_token": tok.get("refresh_token",
                                                    self._token.get("refresh_token") if same else None),
                           "client_id": cid, "scope": tok.get("scope", SCOPE)}
            if keep:
                self._token["pisi_calendar_id"] = keep
            self._apply_access(tok)
            self.expired = False          # fresh token — clear any stale warning
            self._save_token()

        if not self._token.get("refresh_token"):
            on_status("Connected, but Google sent no refresh token: "
                      "revoke access in your Google account and reconnect.")
            return

        on_status("Connected ✓, setting up your PISI calendar…")
        try:
            self.ensure_pisi_calendar()
            on_status("Connected ✓ · PISI calendar ready.")
        except Exception as e:            # noqa: BLE001
            log.warning("could not create PISI calendar", exc_info=True)
            on_status(f"Connected, but couldn't create the PISI calendar: {e}")

    # ---- access tokens ----------------------------------------------
    def _apply_access(self, tok: dict) -> None:
        self._token["access_token"] = tok.get("access_token")
        self._token["expiry"] = time.time() + int(tok.get("expires_in", 3600)) - 60

    def _access_token(self) -> str | None:
        with self._lock:
            if self._token.get("access_token") and \
                    time.time() < self._token.get("expiry", 0):
                return self._token["access_token"]
            rt = self._token.get("refresh_token")
        if not rt:
            return None
        cid, csec = self._client()
        try:
            tok = _post_form(TOKEN_URL, {
                "client_id": cid,
                "client_secret": csec,
                "refresh_token": rt,
                "grant_type": "refresh_token",
            })
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:        # noqa: BLE001
                pass
            if e.code == 400 and "invalid_grant" in body:
                # the refresh token is dead (expired or revoked) — no amount of
                # retrying fixes it, so drop it and flag a reconnect. Leaving it
                # in place would make connected() lie and every write fail silently.
                log.warning("Google refresh token expired/revoked — disconnecting")
                with self._lock:
                    self.expired = True
                    self._token = {}
                try:
                    google_token_file().unlink(missing_ok=True)
                except Exception:    # noqa: BLE001
                    pass
                return None
            log.warning("access-token refresh failed (HTTP %s)", e.code,
                        exc_info=True)
            return None
        except Exception:            # transient: offline, DNS, timeout, 5xx…
            log.warning("access-token refresh failed (offline?)", exc_info=True)
            return None
        with self._lock:
            self._apply_access(tok)
            self._save_token()
            return self._token.get("access_token")

    # ---- generic API call (used by Phase 2 writes too) --------------
    def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        token = self._access_token()
        if not token:
            raise RuntimeError("not connected")
        url = API + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    # ---- the dedicated PISI calendar --------------------------------
    def ensure_pisi_calendar(self) -> str:
        """Return the id of our PISI calendar, finding or creating it."""
        cid = self._token.get("pisi_calendar_id")
        if cid:
            return cid
        try:                       # one this client made earlier (e.g. before a reinstall)
            listing = self._api("GET", "/users/me/calendarList")
        except urllib.error.HTTPError:
            listing = {}           # (the narrow scope may not list calendars)
        for item in listing.get("items", []):
            if item.get("summary") == PISI_CALENDAR_NAME:
                cid = item["id"]
                break
        if not cid:
            created = self._api("POST", "/calendars", {
                "summary": PISI_CALENDAR_NAME,
                "description": "Focus blocks and plans suggested by your PISI "
                               "companion. Safe to hide or delete.",
            })
            cid = created["id"]
        with self._lock:
            self._token["pisi_calendar_id"] = cid
            self._save_token()
        return cid

    # ---- events on the PISI calendar (Phase 2) ----------------------
    def add_event(self, summary: str, start, end, description: str = "",
                  all_day: bool = False, key: str | None = None,
                  kind: str | None = None) -> dict:
        cid = self.ensure_pisi_calendar()
        if all_day:
            when = {"start": {"date": start.date().isoformat()},
                    "end": {"date": end.date().isoformat()}}
        else:
            when = {"start": {"dateTime": start.isoformat()},
                    "end": {"dateTime": end.isoformat()}}
        body: dict[str, Any] = {"summary": summary, **when}
        if description:
            body["description"] = description
        priv = {"pisi": "1"}
        if kind:
            priv["kind"] = kind
        if key:
            priv["key"] = key
        body["extendedProperties"] = {"private": priv}
        path = f"/calendars/{urllib.parse.quote(cid, safe='')}/events"
        return self._api("POST", path, body)

    def list_pisi_events(self, time_min, time_max) -> list[dict]:
        """PISI-created events in a window (used to dedupe and honor edits)."""
        cid = self.ensure_pisi_calendar()
        q = urllib.parse.urlencode({
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
            "privateExtendedProperty": "pisi=1",
        })
        path = f"/calendars/{urllib.parse.quote(cid, safe='')}/events?{q}"
        return self._api("GET", path).get("items", [])

    def taken_keys(self, time_min, time_max) -> set:
        """The plan-item keys already present on the PISI calendar in a window,
        so we don't propose the same block twice."""
        out = set()
        try:
            for ev in self.list_pisi_events(time_min, time_max):
                k = ev.get("extendedProperties", {}).get("private", {}).get("key")
                if k:
                    out.add(k)
        except Exception:
            log.warning("could not list PISI events (offline?)", exc_info=True)
        return out

    # ---- status -----------------------------------------------------
    def status_line(self) -> str:
        if not self.has_credentials():
            return "Not set up: add a Google client ID and secret, then Connect."
        if self.needs_reconnect():
            return "PISI's Google connection was updated. Click Connect once more."
        if not self.connected():
            return "Not connected. Click Connect to sign in with Google."
        if self.calendar_id():
            return "Connected ✓ · PISI calendar ready."
        return "Connected ✓ · calendar not set up yet."
