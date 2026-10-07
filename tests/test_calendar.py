"""Tests for the iCal parser and CalendarService (no network, no GUI)."""
from datetime import datetime, timedelta, timezone

from companion import calendar as cal


def _now():
    return datetime.now().astimezone()


def _ics(body: str) -> str:
    return "BEGIN:VCALENDAR\n" + body + "\nEND:VCALENDAR"


def _fmt(dt):
    return dt.strftime("%Y%m%dT%H%M%S")


def _vevent(summary, dtstart, dtend=None, rrule=None, extra=""):
    lines = ["BEGIN:VEVENT", f"SUMMARY:{summary}", f"DTSTART:{dtstart}"]
    if dtend:
        lines.append(f"DTEND:{dtend}")
    if rrule:
        lines.append(f"RRULE:{rrule}")
    if extra:
        lines.append(extra)
    lines.append("END:VEVENT")
    return "\n".join(lines)


def test_single_timed_event_within_horizon():
    when = _now() + timedelta(days=1)
    text = _ics(_vevent("Meeting", _fmt(when), _fmt(when + timedelta(hours=1))))
    evs = cal.parse_ics(text)
    assert len(evs) == 1
    assert evs[0]["summary"] == "Meeting"
    assert evs[0]["all_day"] is False


def test_event_outside_horizon_dropped():
    far = _now() + timedelta(days=90)
    text = _ics(_vevent("Later", _fmt(far), _fmt(far + timedelta(hours=1))))
    assert cal.parse_ics(text) == []


def test_all_day_event():
    day = (_now() + timedelta(days=2)).strftime("%Y%m%d")
    text = _ics("BEGIN:VEVENT\nSUMMARY:Essay due\n"
                f"DTSTART;VALUE=DATE:{day}\nEND:VEVENT")
    evs = cal.parse_ics(text)
    assert len(evs) == 1 and evs[0]["all_day"] is True


def test_weekly_recurrence_expands_multiple():
    start = (_now() - timedelta(days=7)).replace(hour=10, minute=0,
                                                 second=0, microsecond=0)
    until = _now() + timedelta(days=30)
    text = _ics(_vevent("Class", _fmt(start), _fmt(start + timedelta(hours=1)),
                        rrule=f"FREQ=WEEKLY;BYDAY=MO,WE;UNTIL={_fmt(until)}"))
    evs = cal.parse_ics(text)
    assert len(evs) >= 2                       # several occurrences in 14d
    assert all(e["summary"] == "Class" for e in evs)
    # every occurrence lands on Monday or Wednesday
    assert all(datetime.fromisoformat(e["start"]).weekday() in (0, 2) for e in evs)


def test_yearly_birthday_projects_to_current_window_not_original_year():
    # a birthday defined years ago, recurring yearly, landing in the next week
    target = _now() + timedelta(days=5)
    old = target.replace(year=2016)
    text = _ics(_vevent("Birthday", _fmt(old), rrule="FREQ=YEARLY"))
    evs = cal.parse_ics(text)
    assert len(evs) == 1
    assert datetime.fromisoformat(evs[0]["start"]).year == target.year  # not 2016


def test_exdate_excludes_occurrence():
    start = _now().replace(hour=9, minute=0, second=0, microsecond=0) \
        - timedelta(days=1)
    # daily for the horizon, but exclude tomorrow
    skip = (_now() + timedelta(days=1)).replace(hour=9, minute=0, second=0,
                                                microsecond=0)
    text = _ics(_vevent("Standup", _fmt(start), _fmt(start + timedelta(minutes=15)),
                        rrule="FREQ=DAILY", extra=f"EXDATE:{_fmt(skip)}"))
    evs = cal.parse_ics(text)
    assert all(datetime.fromisoformat(e["start"]).date() != skip.date()
               for e in evs)


def test_utc_suffix_parsed():
    when = datetime.now(timezone.utc) + timedelta(days=1)
    text = _ics(_vevent("UTC ev", when.strftime("%Y%m%dT%H%M%S") + "Z"))
    evs = cal.parse_ics(text)
    assert len(evs) == 1


# ---- CalendarService: merge / dedup / prune / status --------------------
def _hydrated(summary, start):
    return {"start": start, "end": start + timedelta(hours=1),
            "summary": summary, "location": "", "all_day": False}


def test_merge_and_dedup_across_sources():
    from companion.store import Store
    svc = cal.CalendarService(Store())
    s = _now() + timedelta(days=1)
    svc._sources = {
        "a": {"etag": None, "last_modified": None,
              "events": [_hydrated("Shared", s), _hydrated("OnlyA", s + timedelta(hours=2))]},
        "b": {"etag": None, "last_modified": None,
              "events": [_hydrated("Shared", s)]},   # duplicate of A's Shared
    }
    svc._rebuild()
    summaries = sorted(e["summary"] for e in svc._all())
    assert summaries == ["OnlyA", "Shared"]          # deduped to one "Shared"


def test_urls_split_multiline_and_commas():
    from companion.store import Store
    store = Store()
    store.config["ical_url"] = "https://a.ics\nhttps://b.ics, https://c.ics"
    svc = cal.CalendarService(store)
    assert svc.urls() == ["https://a.ics", "https://b.ics", "https://c.ics"]


def test_fetch_304_keeps_events(monkeypatch):
    import io
    import urllib.error
    import urllib.request
    from companion.store import Store
    svc = cal.CalendarService(Store())
    s = _now() + timedelta(days=1)
    body = _ics(_vevent("E", _fmt(s), _fmt(s + timedelta(hours=1))))

    class FakeResp(io.BytesIO):
        def __init__(self, b, h):
            super().__init__(b.encode()); self.headers = h
        def __enter__(self): return self
        def __exit__(self, *a): self.close()

    calls = {"n": 0}

    def fake(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(body, {"ETag": '"v1"'})
        raise urllib.error.HTTPError(req.full_url, 304, "NM", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert svc._fetch_one("https://x.ics") is True         # 200: changed
    assert len(svc._sources["https://x.ics"]["events"]) == 1
    assert svc._fetch_one("https://x.ics") is False        # 304: unchanged
    assert len(svc._sources["https://x.ics"]["events"]) == 1
    assert svc._status["https://x.ics"]["ok"] is True
