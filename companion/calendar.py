"""Offline-first calendar awareness (Option A: read-only iCal).

PISI reads one or more Google Calendar "secret addresses in iCal format" (or any
.ics URLs — academic, personal, a club) and merges them. It parses locally with
no third-party dependency and caches the upcoming events on disk, per source.
**Every query here reads only the local cache**, so schedule nudges, the morning
briefing and free-gap detection all keep working with no network — a background
refresh (see CalendarService.refresh) just tops each calendar up whenever you
happen to be online.

Nothing is ever sent anywhere: the only network call is an HTTPS GET of your own
calendar URL.

------------------------------------------------------------------------------
NOTE — Option B (planned): full Google Calendar API via OAuth.
    This module is deliberately read-only. Two-way sync — writing completed
    focus sessions back as events, creating/editing entries, live push updates —
    needs the Google Calendar REST API with OAuth (a one-time browser consent +
    a locally stored refresh token + a Google Cloud client credential). When we
    add it, keep the same offline-first shape: OAuth/network only tops up the
    same on-disk cache these query methods already read, so offline behaviour is
    unchanged. Slot the API fetch in alongside _fetch_ics as an alternate source
    feeding the same _parse -> cache pipeline. We expect to incorporate this soon.
------------------------------------------------------------------------------

Parser scope: single VEVENTs and simple DAILY/WEEKLY recurrence (INTERVAL,
BYDAY, COUNT, UNTIL, EXDATE) — which covers weekly classes and one-off
deadlines. MONTHLY/YEARLY rules fall back to their first occurrence.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:                       # pragma: no cover - very old Python
    ZoneInfo = None                     # type: ignore

from .log import get_logger
from .paths import calendar_cache_file

MAX_ICS = 20 * 1024 * 1024          # a calendar bigger than this isn't one


def _safe(url: str) -> str:
    """A calendar address fit for the log: a private iCal address works like
    a password (anyone with it can read the calendar), so only its site."""
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.hostname or '?'}/…"

log = get_logger(__name__)

HORIZON_DAYS = 14                       # how far ahead we keep events
_WEEKDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _now() -> datetime:
    return datetime.now().astimezone()


def _ago(when: datetime) -> str:
    secs = int((_now() - when).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} d ago"


# ---------------------------------------------------------------------------
# iCal parsing (stdlib only)
# ---------------------------------------------------------------------------
def _unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with space/tab continues the
    previous one."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _split_prop(line: str) -> tuple[str, dict[str, str], str]:
    """'DTSTART;TZID=Europe/Istanbul:20260908T090000' ->
    ('DTSTART', {'TZID': 'Europe/Istanbul'}, '20260908T090000')."""
    if ":" not in line:
        return line, {}, ""
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v
    return name, params, value


def _parse_dt(value: str, params: dict[str, str]) -> tuple[datetime, bool]:
    """Return (aware datetime, is_all_day)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d.replace(tzinfo=_local_tz()), True
    fmt = "%Y%m%dT%H%M%S"
    if value.endswith("Z"):
        dt = datetime.strptime(value[:15], fmt).replace(tzinfo=timezone.utc)
        return dt.astimezone(_local_tz()), False
    tz = _local_tz()
    tzid = params.get("TZID")
    if tzid and ZoneInfo is not None:
        try:
            tz = ZoneInfo(tzid)
        except Exception:
            tz = _local_tz()
    dt = datetime.strptime(value[:15], fmt).replace(tzinfo=tz)
    return dt, False


def _parse_exdates(value: str, params: dict[str, str]) -> list[datetime]:
    out = []
    for chunk in value.split(","):
        try:
            out.append(_parse_dt(chunk, params)[0])
        except Exception:
            pass
    return out


def _parse_rrule(value: str) -> dict[str, Any]:
    rule: dict[str, Any] = {}
    for part in value.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.upper()
        if k == "BYDAY":
            # strip any ordinal prefix like "2MO" -> "MO"
            rule[k] = [d[-2:].upper() for d in v.split(",") if d[-2:].upper() in _WEEKDAY]
        elif k == "UNTIL":
            try:
                rule[k] = _parse_dt(v, {})[0]
            except Exception:
                pass
        elif k in ("INTERVAL", "COUNT"):
            try:
                rule[k] = int(v)
            except Exception:
                pass
        else:
            rule[k] = v.upper()
    return rule


def _expand(dtstart: datetime, dur: timedelta, rule: dict[str, Any],
            exdates: list[datetime], win_start: datetime,
            win_end: datetime) -> list[tuple[datetime, datetime]]:
    freq = rule.get("FREQ")
    interval = max(1, int(rule.get("INTERVAL", 1) or 1))
    count = rule.get("COUNT")
    until = rule.get("UNTIL")
    ex_dt = set(exdates)
    ex_dates = {e.date() for e in exdates}
    out: list[tuple[datetime, datetime]] = []

    def emit(cand: datetime) -> None:
        if cand < dtstart or cand in ex_dt or cand.date() in ex_dates:
            return
        if win_start <= cand <= win_end and (until is None or cand <= until):
            out.append((cand, cand + dur))

    if freq in ("DAILY", "WEEKLY"):
        byday = rule.get("BYDAY")
        days_of_week = {_WEEKDAY[d] for d in byday} if byday else {dtstart.weekday()}
        start_date = dtstart.date()
        week_monday = start_date - timedelta(days=start_date.weekday())
        # if COUNT is set we must count from the start; else begin near the
        # window to stay cheap.
        walk = start_date if count is not None else max(
            start_date, (win_start - timedelta(days=1)).date())
        hard_end = win_end.date()
        if until:
            hard_end = min(hard_end, until.date())
        emitted, day, guard = 0, walk, 0
        while day <= hard_end and guard < 1200:
            guard += 1
            if freq == "DAILY":
                match = (day - start_date).days % interval == 0
            else:
                week_idx = (day - week_monday).days // 7
                match = week_idx % interval == 0 and day.weekday() in days_of_week
            if match and day >= start_date:
                emitted += 1
                if count is not None and emitted > count:
                    break
                emit(datetime.combine(day, dtstart.timetz()))
            day += timedelta(days=1)
        return out

    if freq == "YEARLY":
        # e.g. birthdays: same month/day each year, projected into the window
        for y in range(win_start.year, win_end.year + 1):
            if (y - dtstart.year) % interval != 0:
                continue
            try:
                emit(dtstart.replace(year=y))
            except ValueError:            # Feb 29 in a non-leap year
                pass
        return out

    if freq == "MONTHLY":
        # same day-of-month each interval months, projected into the window
        y, m = win_start.year, win_start.month
        for _ in range(HORIZON_DAYS // 28 + 3):
            months = (y - dtstart.year) * 12 + (m - dtstart.month)
            if months >= 0 and months % interval == 0:
                try:
                    emit(dtstart.replace(year=y, month=m))
                except ValueError:        # e.g. day 31 in a short month
                    pass
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return out

    return [(dtstart, dtstart + dur)] if win_start <= dtstart <= win_end else []


def parse_ics(text: str) -> list[dict[str, Any]]:
    """Parse an .ics document into a flat list of occurrences within the
    horizon. Robust: any malformed event is skipped, never raised."""
    now = _now()
    win_start = now - timedelta(days=1)
    win_end = now + timedelta(days=HORIZON_DAYS)
    events: list[dict[str, Any]] = []

    in_event = False
    cur: dict[str, Any] = {}
    for line in _unfold(text):
        u = line.strip()
        if u == "BEGIN:VEVENT":
            in_event, cur = True, {"exdates": []}
            continue
        if u == "END:VEVENT":
            in_event = False
            try:
                events.extend(_finish_event(cur, win_start, win_end))
            except Exception:
                pass
            continue
        if not in_event:
            continue
        name, params, value = _split_prop(line)
        try:
            if name == "DTSTART":
                cur["start"], cur["all_day"] = _parse_dt(value, params)
            elif name == "DTEND":
                cur["end"], _ = _parse_dt(value, params)
            elif name == "SUMMARY":
                cur["summary"] = value.replace("\\,", ",").replace("\\n", " ").strip()
            elif name == "LOCATION":
                cur["location"] = value.replace("\\,", ",").strip()
            elif name == "RRULE":
                cur["rrule"] = _parse_rrule(value)
            elif name == "EXDATE":
                cur["exdates"].extend(_parse_exdates(value, params))
        except Exception:
            pass

    events.sort(key=lambda e: e["start"])
    return events


def _finish_event(cur: dict, win_start: datetime,
                  win_end: datetime) -> list[dict[str, Any]]:
    if "start" not in cur:
        return []
    start = cur["start"]
    all_day = cur.get("all_day", False)
    end = cur.get("end") or (start + timedelta(days=1 if all_day else 0, hours=0 if all_day else 1))
    dur = end - start
    summary = cur.get("summary", "(untitled)")
    location = cur.get("location", "")

    if "rrule" in cur:
        occ = _expand(start, dur, cur["rrule"], cur["exdates"], win_start, win_end)
    else:
        occ = [(start, end)] if win_start <= start <= win_end else []

    return [{
        "start": s.isoformat(),
        "end": e.isoformat(),
        "summary": summary,
        "location": location,
        "all_day": all_day,
    } for s, e in occ]


# ---------------------------------------------------------------------------
# Service: fetch (background) + on-disk cache + offline queries
# ---------------------------------------------------------------------------
class CalendarService:
    def __init__(self, store) -> None:
        self.store = store
        # one entry per subscribed calendar URL, each with its own HTTP
        # validators and event list, so they refresh independently.
        self._sources: dict[str, dict] = {}   # url -> {etag, last_modified, events}
        self._events: list[dict] = []          # merged, deduped, sorted
        self._status: dict[str, dict] = {}     # url -> {ok, code, n, error}
        self._last_sync: datetime | None = None
        self._lock = threading.Lock()
        self._load_cache()

    # ---- config -----------------------------------------------------
    def urls(self) -> list[str]:
        """The subscribed calendar URLs. The `ical_url` config holds one per
        line (commas also accepted), so several calendars — academic, personal,
        a club — can be merged."""
        try:
            raw = self.store.config.get("ical_url") or ""
        except Exception:
            return []
        out = []
        for u in (u.strip() for u in re.split(r"[\n,]+", raw)):
            if u.lower().startswith("webcal://"):
                u = "https://" + u[len("webcal://"):]        # what calendar apps mean by it
            if u.lower().startswith(("https://", "http://")):
                out.append(u)                               # (never file:// and the like)
        return out

    def configured(self) -> bool:
        return bool(self.urls())

    # ---- cache ------------------------------------------------------
    def _load_cache(self) -> None:
        try:
            path = calendar_cache_file()
            if not path.exists():
                return
            data = json.loads(path.read_text("utf-8"))
            for url, src in (data.get("sources") or {}).items():
                self._sources[url] = {
                    "etag": src.get("etag"),
                    "last_modified": src.get("last_modified"),
                    "events": self._hydrate(src.get("events", [])),
                }
            self._rebuild()
        except Exception:
            self._sources, self._events = {}, []

    def _save_cache(self) -> None:
        try:
            out = {url: {"etag": s.get("etag"),
                         "last_modified": s.get("last_modified"),
                         "events": self._dehydrate(s["events"])}
                   for url, s in self._sources.items()}
            calendar_cache_file().write_text(
                json.dumps({"fetched": _now().isoformat(), "sources": out},
                           ensure_ascii=False), "utf-8")
        except Exception:
            pass

    def _rebuild(self) -> None:
        """Merge every source into one deduped, time-sorted list."""
        merged: dict[tuple, dict] = {}
        for s in self._sources.values():
            for e in s["events"]:
                key = (e["start"].isoformat(), e["summary"])
                merged.setdefault(key, e)      # drop duplicates across calendars
        self._events = sorted(merged.values(), key=lambda e: e["start"])

    @staticmethod
    def _hydrate(raw: list[dict]) -> list[dict]:
        out = []
        for e in raw:
            try:
                out.append({
                    "start": datetime.fromisoformat(e["start"]),
                    "end": datetime.fromisoformat(e["end"]),
                    "summary": e.get("summary", "(untitled)"),
                    "location": e.get("location", ""),
                    "all_day": bool(e.get("all_day", False)),
                })
            except Exception:
                pass
        out.sort(key=lambda e: e["start"])
        return out

    @staticmethod
    def _dehydrate(events: list[dict]) -> list[dict]:
        return [{"start": e["start"].isoformat(), "end": e["end"].isoformat(),
                 "summary": e["summary"], "location": e["location"],
                 "all_day": e["all_day"]} for e in events]

    # ---- refresh (network; safe to call anytime) --------------------
    def refresh(self) -> None:
        """Kick a background fetch of every subscribed calendar. Each uses a
        conditional GET (ETag / If-Modified-Since), so frequent polling is
        cheap: unchanged calendars answer 304 and cost nothing. No-op (keeps the
        cache) when not configured or offline."""
        urls = self.urls()
        if not urls:
            return

        def work():
            changed = False
            # forget calendars the user removed
            with self._lock:
                for gone in [u for u in list(self._sources) if u not in urls]:
                    del self._sources[gone]
                    changed = True
                for gone in [u for u in list(self._status) if u not in urls]:
                    del self._status[gone]
            for url in urls:
                if self._fetch_one(url):
                    changed = True
            self._last_sync = _now()
            if changed:
                with self._lock:
                    self._rebuild()
                self._save_cache()

        threading.Thread(target=work, daemon=True).start()

    def _fetch_one(self, url: str) -> bool:
        """Fetch a single calendar; record its status; return True if its events
        changed."""
        src = self._sources.get(url, {})
        headers = {"User-Agent": "PISI/1.0"}
        if src.get("etag"):
            headers["If-None-Match"] = src["etag"]
        if src.get("last_modified"):
            headers["If-Modified-Since"] = src["last_modified"]
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read(MAX_ICS + 1)
                if len(body) > MAX_ICS:
                    raise ValueError("calendar is larger than 20 MB")
                text = body.decode("utf-8", "replace")
                etag = resp.headers.get("ETag")
                last_mod = resp.headers.get("Last-Modified")
            raw = parse_ics(text)
        except urllib.error.HTTPError as e:
            if e.code == 304:                       # unchanged but reachable: OK
                self._status[url] = {"ok": True, "code": 304,
                                     "n": len(src.get("events", []))}
                return False
            log.warning("calendar fetch %s → HTTP %s", _safe(url), e.code)
            self._status[url] = {"ok": False, "code": e.code,
                                 "error": f"HTTP {e.code}"}
            return False
        except Exception as e:                      # offline / bad URL / DNS
            log.info("calendar fetch %s failed: %s", _safe(url), e)
            self._status[url] = {"ok": False, "code": None, "error": str(e)}
            return False
        events = self._hydrate(raw)
        with self._lock:
            self._sources[url] = {"etag": etag, "last_modified": last_mod,
                                  "events": events}
            self._status[url] = {"ok": True, "code": 200, "n": len(events)}
        return True

    # ---- status (for the Settings UI) -------------------------------
    def status_line(self) -> str:
        urls = self.urls()
        if not urls:
            return "No calendars added yet."
        if self._last_sync is None and not self._status:
            return f"{len(urls)} calendar(s) · not synced yet…"
        bad = [u for u in urls if u in self._status and not self._status[u]["ok"]]
        codes = {self._status[u].get("code") for u in bad}
        parts = [f"{len(urls)} calendar(s)"]
        if self._last_sync:
            parts.append("synced " + _ago(self._last_sync))
        parts.append(f"{len(self._all())} upcoming events")
        if bad:
            why = "404, check the address" if codes == {404} else "couldn't be reached"
            parts.append(f"⚠ {len(bad)} {why}")
        else:
            parts.append("all OK ✓")
        return " · ".join(parts)

    # ---- offline queries --------------------------------------------
    def _all(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def today(self) -> list[dict]:
        td = _now().date()
        return [e for e in self._all() if e["start"].date() == td]

    def ongoing_now(self) -> dict | None:
        now = _now()
        for e in self._all():
            if e["all_day"]:
                continue
            if e["start"] <= now < e["end"]:
                return e
        return None

    def next_event(self, timed_only: bool = True) -> dict | None:
        now = _now()
        for e in self._all():
            if timed_only and e["all_day"]:
                continue
            if e["start"] > now:
                return e
        return None

    def starting_within(self, minutes: int) -> list[dict]:
        """Timed events starting in (0, minutes] from now."""
        now = _now()
        horizon = now + timedelta(minutes=minutes)
        return [e for e in self._all()
                if not e["all_day"] and now < e["start"] <= horizon]

    def free_gap_minutes(self) -> int | None:
        """If nothing is happening right now, how many free minutes until the
        next timed event (None if unknown / an event is ongoing)."""
        if self.ongoing_now():
            return None
        nxt = self.next_event()
        if not nxt:
            return None
        return int((nxt["start"] - _now()).total_seconds() // 60)


def fmt_time(dt: datetime) -> str:
    """'9:05', '14:00' — a compact local clock time."""
    return f"{dt.hour}:{dt.minute:02d}"   # not %-H: glibc-only, crashes on Windows
