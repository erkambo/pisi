"""Smart, calendar-aware suggestions — the bit that reasons about your day.

Given the calendar (free time, deadlines) and your habits (what's due, what's on
a streak), the Planner produces at most ONE gentle, well-timed suggestion at a
time:

* a focus block sized to a real free gap ("you've 80 free min — a block?"),
* study time before a nearby deadline,
* protecting a habit streak that's about to lapse,
* fitting a due habit into an actual free slot ("free 15:00–16:30 — Workout?").

It adapts to how busy the day is: on a heavy day it stays quiet and only raises
the single most important thing, gently; on a light day it's happy to nudge a
habit into a free slot. Everything here is pure/read-only and returns text +
optional action for the orchestrator to speak — it never nags on its own.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any


CADENCE_GAP = {           # how many days may pass before a habit is gently resurfaced
    "daily": 1,
    "often": 2,
    "every2-3": 3,
    "weekly": 7,
    "flexible": 4,
}

# Rough minutes a habit tends to take — used to fit it into a free slot. Matched
# by keyword against the habit name; falls back to DEFAULT. A habit may override
# with an explicit `minutes` field.
DURATION_KEYWORDS = [
    (("workout", "gym", "run", "exercise", "lift"), 60),
    (("read", "textbook", "book", "study", "lecture", "review"), 45),
    (("leetcode", "code", "coding", "project", "job app", "application"), 45),
    (("quran", "surah", "pray", "meditate", "journal"), 15),
    (("baglama", "guitar", "practice", "music", "instrument"), 30),
]
DEFAULT_HABIT_MIN = 30
DEADLINE_WORDS = re.compile(r"\b(due|deadline|assignment|submit|exam|midterm|"
                            r"final|quiz|hand ?in|paper|essay)\b", re.I)


def habit_minutes(habit: dict) -> int:
    if isinstance(habit.get("minutes"), int) and habit["minutes"] > 0:
        return habit["minutes"]
    name = (habit.get("name") or "").lower()
    for keys, mins in DURATION_KEYWORDS:
        if any(k in name for k in keys):
            return mins
    return DEFAULT_HABIT_MIN


def _parse_hhmm(s: str, default: time) -> time:
    try:
        return datetime.strptime(s, "%H:%M").time()
    except Exception:
        return default


def _aware(dt: datetime) -> datetime:
    """Calendar events are timezone-aware; make `now` aware too so comparisons
    don't blow up when the app passes a naive datetime.now()."""
    return dt if dt.tzinfo is not None else dt.astimezone()


class Planner:
    def __init__(self, store, calendar) -> None:
        self.store = store
        self.calendar = calendar

    # ---- the day's shape --------------------------------------------
    def _waking_window(self, now: datetime) -> tuple[datetime, datetime]:
        """Today's active window: from now until the quiet-hours start (or a
        sensible late-evening default)."""
        cfg = self.store.config
        q_start = _parse_hhmm(cfg.get("quiet_start", "23:00"), time(23, 0))
        end = now.replace(hour=q_start.hour, minute=q_start.minute,
                          second=0, microsecond=0)
        if end <= now:                       # quiet start already passed today
            end = now
        return now, end

    def free_slots(self, now: datetime, min_minutes: int = 30) -> list[tuple]:
        """Free intervals between now and end-of-day, with timed events removed.
        Returns [(start, end, minutes)] sorted by start."""
        now = _aware(now)
        start, day_end = self._waking_window(now)
        if day_end <= start:
            return []
        busy = []
        for e in self.calendar._all() if self.calendar else []:
            if e.get("all_day"):
                continue
            s, en = e["start"], e["end"]
            if en <= start or s >= day_end:
                continue
            busy.append((max(s, start), min(en, day_end)))
        busy.sort()
        # merge overlaps
        merged = []
        for s, en in busy:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], en))
            else:
                merged.append((s, en))
        # gaps between busy blocks
        slots = []
        cursor = start
        for s, en in merged:
            if s - cursor >= timedelta(minutes=min_minutes):
                slots.append((cursor, s, int((s - cursor).total_seconds() // 60)))
            cursor = max(cursor, en)
        if day_end - cursor >= timedelta(minutes=min_minutes):
            slots.append((cursor, day_end, int((day_end - cursor).total_seconds() // 60)))
        return slots

    def day_load(self, now: datetime) -> dict[str, Any]:
        """How busy today is, for adapting tone/expectations."""
        now = _aware(now)
        events = [e for e in (self.calendar.today() if self.calendar else [])
                  if not e.get("all_day")]
        booked = 0
        for e in events:
            booked += max(0, int((e["end"] - e["start"]).total_seconds() // 60))
        free = sum(m for *_, m in self.free_slots(now, 15))
        if booked >= 360 or len(events) >= 5:
            level = "heavy"
        elif booked <= 60 and len(events) <= 1:
            level = "light"
        else:
            level = "normal"
        return {"events": len(events), "booked_min": booked,
                "free_min": free, "level": level}

    # ---- location gating (a simple manual toggle) -------------------
    def presence(self) -> str:
        """'home' or 'out' — set by you (a tray toggle). Simpler and more
        reliable than guessing from your class schedule, since you might skip a
        class or leave early."""
        try:
            return "out" if self.store.config.get("presence") == "out" else "home"
        except Exception:
            return "home"

    def _allowed(self, where: str) -> bool:
        """A 'home'-only habit is allowed only when you're home."""
        return where != "home" or self.presence() == "home"

    def _fit_slot(self, slots, need_min: int, where: str = "anywhere"):
        if not self._allowed(where):
            return None
        for s, e, m in slots:
            if m >= need_min:
                return (s, e, m)
        return None

    # ---- deadlines --------------------------------------------------
    def next_deadline(self, now: datetime, within_days: int = 3) -> dict | None:
        horizon = now + timedelta(days=within_days)
        best = None
        for e in self.calendar._all() if self.calendar else []:
            if e["start"] < now:
                continue
            # A deadline is recognised by its title (works for timed or all-day
            # events). We no longer treat *every* all-day event as a deadline —
            # that flagged informational notes like "grades available in Quest".
            looks_due = bool(DEADLINE_WORDS.search(e.get("summary", "")))
            if looks_due and e["start"] <= horizon:
                if best is None or e["start"] < best["start"]:
                    best = e
        return best

    # ---- the single best nudge --------------------------------------
    def suggest(self, now: datetime) -> dict | None:
        """Return one suggestion {text, kind, action?, minutes?} or None.
        Ordering encodes priority; day-load gates the softer suggestions."""
        now = _aware(now)
        load = self.day_load(now)
        slots = self.free_slots(now, 30)
        gap_now = slots[0][2] if slots and slots[0][0] <= now + timedelta(minutes=2) else 0

        # 1) A nearby deadline + free time now → offer to work on it.
        dl = self.next_deadline(now, within_days=3)
        if dl and gap_now >= 30:
            when = _friendly_when(now, dl["start"])
            mins = min(50, max(25, gap_now - 5))
            return {"kind": "deadline",
                    "text": f"{_clean_summary(dl['summary'])} is due {when}: "
                            f"a {mins}-min focus block now? 🌙",
                    "action": "focus", "minutes": mins}

        # 2) Protect a daily streak that's about to lapse (afternoon+).
        if now.hour >= 15:
            risk = self._streak_at_risk()
            if risk:
                h, streak = risk
                slot = self._first_fitting_slot(slots, habit_minutes(h))
                where = f", free {_slot_label(slot)}" if slot else ""
                return {"kind": "streak", "habit_id": h["id"],
                        "text": f"{h.get('emoji','⭐')} {h['name']} keeps your "
                                f"🔥{streak} streak alive{where}. Up for it?"}

        # On a heavy day, stop here — don't pile on softer nudges.
        if load["level"] == "heavy":
            return None

        # 3) A generous free gap now → offer a plain focus block.
        if gap_now >= 50:
            mins = min(50, gap_now - 5)
            return {"kind": "focus",
                    "text": f"you've got {gap_now} free min. A {mins}-min focus block? 🌙",
                    "action": "focus", "minutes": mins}

        # 4) Fit a due habit into an actual upcoming free slot (location-aware).
        due = self._due_habits()
        for h in due:
            slot = self._fit_slot(slots, habit_minutes(h), h.get("where", "anywhere"))
            if slot:
                return {"kind": "habit", "habit_id": h["id"],
                        "text": f"free {_slot_label(slot)}: good time for "
                                f"{h.get('emoji','⭐')} {h['name']}?"}
        return None

    # ---- full-day plan (for the "Plan my day" consent dialog) -------
    def plan_items(self, now: datetime, taken_keys=()) -> list[dict]:
        """The ORDERED list of things worth doing today (no times yet): each a
        {title, minutes, kind, key, reason, where, habit_id?}. Deadline focus
        first, then due habits by priority. Skips items already on the PISI
        calendar (taken_keys). The dialog can reorder these, then call pack()."""
        now = _aware(now)
        day = now.date()
        taken = set(taken_keys)
        items: list[dict] = []

        dl = self.next_deadline(now, within_days=3)
        if dl:
            key = f"{day}|focus|{dl['summary']}"
            if key not in taken:
                items.append({"title": f"Focus: {_clean_summary(dl['summary'])}",
                              "minutes": 50, "kind": "focus", "key": key,
                              "reason": f"due {_friendly_when(now, dl['start'])}",
                              "where": "anywhere"})

        for pr, h, streak in self._ranked_due(now):
            key = f"{day}|habit|{h['id']}"
            if key in taken:
                continue
            items.append({"title": f"{h.get('emoji','⭐')} {h['name']}",
                          "minutes": habit_minutes(h), "kind": "habit",
                          "key": key, "habit_id": h["id"],
                          "where": h.get("where", "anywhere"),
                          "reason": (f"protects your 🔥{streak} streak"
                                     if streak >= 2 else "due today")})
        return items

    def pack(self, items: list[dict], now: datetime) -> list[dict]:
        """Lay an ORDERED item list into today's free time, in order. Uses a
        forward-moving cursor so the result is strictly sequential — item order
        == time order — which is what makes reordering feel predictable. Honors
        the home/out toggle and 10-min buffers; items that don't fit are dropped."""
        now = _aware(now)
        slots = self.free_slots(now, 30)
        cursor = None                          # earliest time still free
        placed = []
        for it in items:
            if not self._allowed(it.get("where", "anywhere")):
                continue
            need = timedelta(minutes=it["minutes"])
            for s, e, _m in slots:
                avail = s if (cursor is None or cursor < s) else cursor
                if avail < e and e - avail >= need:
                    start, end = avail, avail + need
                    cursor = end + timedelta(minutes=10)
                    placed.append({**it, "start": start, "end": end})
                    break
        return placed                          # already in start-time order

    def build_plan(self, now: datetime, taken_keys=()) -> list[dict]:
        """Convenience: choose items then pack them into today's free time."""
        return self.pack(self.plan_items(now, taken_keys), now)

    def _ranked_due(self, now: datetime):
        """Due habits with a priority score and streak, most important first."""
        scored = []
        for h in self.store.habits:
            if self.store.done_today(h["id"]):
                continue
            cad = h.get("cadence", "daily")
            gap = CADENCE_GAP.get(cad, 2)
            since = self.store.days_since(h["id"])
            due = cad in ("daily", "often") or since is None or since >= gap
            if not due:
                continue
            streak = self.store.streak(h["id"])
            pr = (10 if (cad in ("daily", "often") and streak >= 2) else 0)
            pr += (since if since is not None else 5)
            scored.append((pr, h, streak))
        scored.sort(key=lambda x: -x[0])
        return scored

    # ---- helpers ----------------------------------------------------
    def _due_habits(self) -> list[dict]:
        """Not done today, most overdue first."""
        scored = []
        for h in self.store.habits:
            if self.store.done_today(h["id"]):
                continue
            gap = CADENCE_GAP.get(h.get("cadence", "daily"), 2)
            since = self.store.days_since(h["id"])
            if since is None or since >= gap:
                scored.append((since if since is not None else 999, h))
        scored.sort(key=lambda x: -x[0])
        return [h for _, h in scored]

    def _streak_at_risk(self) -> tuple[dict, int] | None:
        best = None
        for h in self.store.habits:
            if h.get("cadence") not in ("daily", "often"):
                continue
            if self.store.done_today(h["id"]):
                continue
            st = self.store.streak(h["id"])
            if st >= 2 and (best is None or st > best[1]):
                best = (h, st)
        return best

    @staticmethod
    def _first_fitting_slot(slots: list[tuple], need_min: int):
        for s, e, m in slots:
            if m >= need_min:
                return (s, e, m)
        return None


def fmt_time(dt: datetime) -> str:
    return f"{dt.hour}:{dt.minute:02d}"      # not %-H: glibc-only, crashes on Windows


def _slot_label(slot) -> str:
    s, e, _ = slot
    return f"{fmt_time(s)}–{fmt_time(e)}"


def _friendly_when(now: datetime, when: datetime) -> str:
    days = (when.date() - now.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"on {when.strftime('%A')}"


def _clean_summary(summary: str) -> str:
    """Drop a trailing 'due'/'deadline' from an event title so we don't say
    'assignment due is due tomorrow'."""
    cleaned = re.sub(r"\s*[-–:]?\s*\b(due|deadline)\b\s*$", "", summary, flags=re.I)
    return cleaned.strip() or summary
