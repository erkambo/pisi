"""Tests for the smart planner (pure logic; a fake calendar, isolated store)."""
from datetime import date, datetime, timedelta


from companion.planner import Planner, habit_minutes, _clean_summary, _friendly_when
from helpers import sample_store


def _at(hour, minute=0):
    return datetime.now().astimezone().replace(hour=hour, minute=minute,
                                               second=0, microsecond=0)


class FakeCal:
    def __init__(self, events):
        self._events = events
    def _all(self):
        return list(self._events)
    def today(self):
        td = datetime.now().astimezone().date()
        return [e for e in self._events if e["start"].date() == td]
    def configured(self):
        return True
    def starting_within(self, minutes):
        return []


def _ev(h0, m0, h1, m1, summary="busy", all_day=False):
    return {"start": _at(h0, m0), "end": _at(h1, m1),
            "summary": summary, "location": "", "all_day": all_day}


def test_habit_minutes_by_keyword():
    assert habit_minutes({"name": "Workout"}) == 60
    assert habit_minutes({"name": "Quran / Surah"}) == 15
    assert habit_minutes({"name": "Something odd"}) == 30      # default
    assert habit_minutes({"name": "x", "minutes": 12}) == 12   # explicit override


def test_clean_summary_and_when():
    assert _clean_summary("ECE 313 assignment due") == "ECE 313 assignment"
    assert _clean_summary("Essay") == "Essay"
    now = _at(12)
    assert _friendly_when(now, now) == "today"
    assert _friendly_when(now, now + timedelta(days=1)) == "tomorrow"


def test_light_day_offers_focus_block():
    p = Planner(sample_store(), FakeCal([_ev(9, 0, 10, 0, "class")]))
    s = p.suggest(_at(13))
    assert s and s["kind"] == "focus" and s["action"] == "focus"
    assert s["minutes"] >= 25


def test_heavy_day_stays_quiet():
    evs = [_ev(8, 0, 9, 30), _ev(9, 30, 11, 0), _ev(11, 0, 12, 30),
           _ev(14, 0, 15, 30), _ev(15, 30, 17, 0)]
    p = Planner(sample_store(), FakeCal(evs))
    assert p.day_load(_at(13))["level"] == "heavy"
    # no soft nudges on a heavy day (no streaks set up here)
    assert p.suggest(_at(13)) is None


def test_deadline_triggers_study_block_with_clean_wording():
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    deadline = {"start": tomorrow, "end": tomorrow + timedelta(days=1),
                "summary": "ECE 313 assignment due", "location": "", "all_day": True}
    p = Planner(sample_store(), FakeCal([_ev(9, 0, 9, 30), deadline]))
    s = p.suggest(_at(13))
    assert s and s["kind"] == "deadline"
    assert "ECE 313 assignment is due tomorrow" in s["text"]
    assert "due is due" not in s["text"]


def test_allday_note_without_keyword_is_not_a_deadline():
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    note = {"start": tomorrow, "end": tomorrow + timedelta(days=1),
            "summary": "Grades available in Quest", "location": "", "all_day": True}
    p = Planner(sample_store(), FakeCal([_ev(9, 0, 9, 30), note]))
    s = p.suggest(_at(13))
    # a plain all-day note must not be treated as a deadline
    assert s is None or s["kind"] != "deadline"
    assert p.next_deadline(_at(13)) is None


def test_streak_at_risk_suggested_in_the_afternoon():
    store = sample_store()
    tb = next(h for h in store.habits if h["name"] == "Textbook")
    tb["history"] = [(date.today() - timedelta(days=d)).isoformat()
                     for d in range(1, 5)]                  # 4-day streak, not today
    p = Planner(store, FakeCal([_ev(9, 0, 10, 0)]))
    s = p.suggest(_at(17))
    assert s and s["kind"] == "streak" and "Textbook" in s["text"]
    # carries habit_id so the bubble can open (or offer) that habit's setup
    assert s["habit_id"] == tb["id"]


def test_habit_suggestion_carries_habit_id():
    store = sample_store()
    # an event covering "now" → no free gap right now (gap_now == 0), so the
    # planner skips the deadline/focus offers and reaches the due-habit branch,
    # fitting a habit into the free slot after the event.
    p = Planner(store, FakeCal([_ev(10, 30, 11, 30)]))
    s = p.suggest(_at(11, 0))              # morning (skips the streak branch too)
    assert s and s["kind"] == "habit"
    assert any(h["id"] == s["habit_id"] for h in store.habits)


def test_home_only_habit_gated_by_presence_toggle():
    store = sample_store()
    w = next(h for h in store.habits if h["name"] == "Workout")
    w["where"] = "home"
    w["history"] = []                       # overdue
    p = Planner(store, FakeCal([_ev(9, 0, 10, 0)]))

    store.config["presence"] = "out"        # you're out → no home-only workout
    plan_out = p.build_plan(_at(13, 0))
    assert not any("Workout" in b["title"] for b in plan_out)

    store.config["presence"] = "home"       # you're home → it can be placed
    plan_home = p.build_plan(_at(13, 0))
    assert any("Workout" in b["title"] for b in plan_home)


def test_reorder_then_pack_reflows_times():
    p = Planner(sample_store(), FakeCal([_ev(9, 0, 10, 0)]))
    items = p.plan_items(_at(13, 0))
    assert len(items) >= 2
    reversed_items = list(reversed(items))
    packed = p.pack(reversed_items, _at(13, 0))
    # the item we moved to the front now starts first
    assert packed[0]["key"] == reversed_items[0]["key"]


def test_build_plan_skips_taken_keys():
    store = sample_store()
    p = Planner(store, FakeCal([_ev(9, 0, 10, 0)]))
    full = p.build_plan(_at(13, 0))
    assert full
    taken = {full[0]["key"]}
    fewer = p.build_plan(_at(13, 0), taken_keys=taken)
    assert all(b["key"] != full[0]["key"] for b in fewer)


def test_planner_accepts_naive_now():
    # the app passes a naive datetime.now(); planner must not crash comparing it
    from datetime import datetime as _dt
    p = Planner(sample_store(), FakeCal([_ev(9, 0, 10, 0)]))
    naive = _dt.now().replace(hour=13, minute=0, second=0, microsecond=0)
    assert naive.tzinfo is None
    p.build_plan(naive)          # should not raise
    p.suggest(naive)


def test_free_slots_split_around_events():
    p = Planner(sample_store(), FakeCal([_ev(13, 0, 13, 20), _ev(15, 0, 16, 30)]))
    slots = p.free_slots(_at(12, 50), 30)
    labels = [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e, _ in slots]
    assert ("13:20", "15:00") in labels                     # gap between events
