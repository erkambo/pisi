"""Tests for the JSON-backed Store: habits, streaks, treats, per-habit setups,
state, config defaults, and load/save resilience. Pure logic, no Qt."""
import json
from datetime import date, timedelta


from companion.store import Store, DEFAULT_CONFIG
from helpers import sample_store
from companion.paths import data_file


def _iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


# ---- load / seed / config ----------------------------------------------
def test_fresh_store_starts_with_no_habits_and_defaults():
    s = Store()
    assert s.habits == []                           # habits are personal: none seeded
    # every default config key is present
    for k, v in DEFAULT_CONFIG.items():
        assert k in s.config
    assert s.config["focus_min"] == 25
    assert s.config["presence"] == "home"


def test_save_is_readable_json_and_reloads():
    s = Store()
    s.set_config("cat_name", "Zelda")
    raw = json.loads(data_file().read_text("utf-8"))
    assert raw["config"]["cat_name"] == "Zelda"
    assert Store().config["cat_name"] == "Zelda"    # a fresh load sees it


def test_corrupt_file_is_backed_up_not_fatal():
    p = data_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not json", "utf-8")
    s = Store()                                     # must not raise
    assert s.habits == []                           # recovered, empty
    assert p.with_suffix(".corrupt.json").exists()


def test_missing_config_keys_are_backfilled():
    p = data_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"config": {"cat_name": "Keep"},
                             "habits": [], "state": {}}), "utf-8")
    s = Store()
    assert s.config["cat_name"] == "Keep"           # existing value preserved
    assert s.config["focus_min"] == 25              # missing default filled in


# ---- habits: CRUD -------------------------------------------------------
def test_add_and_remove_habit():
    s = Store()
    n = len(s.habits)
    h = s.add_habit("Meditate", "🧘", "daily", where="home")
    assert len(s.habits) == n + 1
    assert h["where"] == "home" and h["history"] == []
    assert Store().habit(h["id"]) is not None       # persisted
    s.remove_habit(h["id"])
    assert s.habit(h["id"]) is None


def test_set_habit_where():
    s = sample_store()
    h = s.habits[0]
    s.set_habit_where(h["id"], "home")
    assert Store().habit(h["id"])["where"] == "home"


# ---- habits: completion / streaks --------------------------------------
def test_mark_done_is_idempotent_and_deduped():
    s = sample_store()
    hid = s.habits[0]["id"]
    s.mark_done(hid)
    s.mark_done(hid)                                # same day again
    assert s.done_today(hid)
    assert s.habits[0]["history"].count(date.today().isoformat()) == 1


def test_unmark_done():
    s = sample_store()
    hid = s.habits[0]["id"]
    s.mark_done(hid)
    s.unmark_done(hid)
    assert not s.done_today(hid)


def test_days_since_and_count_last_days():
    s = sample_store()
    hid = s.habits[0]["id"]
    assert s.days_since(hid) is None                # never done
    for d in (0, 1, 2, 9):
        s.mark_done(hid, on=_iso(d))
    assert s.days_since(hid) == 0                   # done today
    assert s.count_last_days(hid, 7) == 3           # 0,1,2 within 7d; 9 excluded


def test_streak_counts_consecutive_including_today():
    s = sample_store()
    hid = s.habits[0]["id"]
    for d in (0, 1, 2, 3):
        s.mark_done(hid, on=_iso(d))
    assert s.streak(hid) == 4


def test_streak_survives_today_not_done_yet():
    s = sample_store()
    hid = s.habits[0]["id"]
    for d in (1, 2, 3):                             # yesterday back, not today
        s.mark_done(hid, on=_iso(d))
    assert s.streak(hid) == 3                        # today-not-done doesn't break it


def test_streak_breaks_on_gap():
    s = sample_store()
    hid = s.habits[0]["id"]
    for d in (1, 2, 4, 5):                          # gap at day 3
        s.mark_done(hid, on=_iso(d))
    assert s.streak(hid) == 2                        # only 1,2 count back from today


# ---- per-habit setup (workspace) ---------------------------------------
def test_habit_workspace_roundtrip_and_clear():
    s = sample_store()
    hid = s.habits[1]["id"]
    assert s.habit_workspace(hid) is None
    s.set_habit_workspace(hid, ["/tmp/a.pdf"], ["https://leetcode.com"])
    got = Store().habit_workspace(hid)              # persisted
    assert got["paths"] == ["/tmp/a.pdf"]
    assert got["urls"] == ["https://leetcode.com"]
    assert got["cmds"] == []                        # commands default to empty
    s.set_habit_workspace(hid, [], [])              # clear
    assert s.habit_workspace(hid) is None


def test_habit_workspace_keeps_commands():
    s = sample_store()
    hid = s.habits[1]["id"]
    s.set_habit_workspace(hid, [], [], ["code ~/dev/Baglama-Tuner"])
    got = Store().habit_workspace(hid)
    assert got["cmds"] == ["code ~/dev/Baglama-Tuner"]
    # a command-only setup still counts as a setup
    assert got is not None


def test_habit_workspace_ignores_empty_bundle():
    s = sample_store()
    hid = s.habits[0]["id"]
    s.set_habit_workspace(hid, [], [])              # nothing to attach
    assert "workspace" not in s.habits[0]           # not stored
    assert s.habit_workspace(hid) is None


def test_set_workspace_on_missing_habit_is_noop():
    s = Store()
    s.set_habit_workspace("nope", ["/x"], [])       # must not raise
    assert s.habit_workspace("nope") is None


# ---- treats -------------------------------------------------------------
def test_treats_add_spend_and_floor():
    s = Store()
    assert s.treats() == 0
    assert not s.spend_treat()                      # nothing to spend
    s.add_treats(2)
    assert s.treats() == 2
    assert s.spend_treat() and s.treats() == 1
    s.add_treats(-5)                                # never goes negative
    assert s.treats() == 0


# ---- state / planned-today ---------------------------------------------
def test_state_setget_persists():
    s = Store()
    s.set_state("setup_offered", ["abc"])
    assert Store().state.get("setup_offered") == ["abc"]


def test_planned_today_is_date_gated():
    s = sample_store()
    ids = [h["id"] for h in s.habits[:2]]
    s.set_planned_today(ids)
    assert s.planned_today() == ids
    # a stale plan (yesterday) is ignored
    s.set_state("planned_today", {"date": _iso(1), "habit_ids": ids})
    assert s.planned_today() == []


# ---- pomodoros today ----------------------------------------------------
def test_pomodoros_bump_set_and_persist():
    s = Store()
    assert s.pomodoros_today() == 0
    assert s.bump_pomodoro() == 1
    assert s.bump_pomodoro() == 2
    assert Store().pomodoros_today() == 2           # persisted across reload
    s.set_pomodoros(0)                              # clear
    assert s.pomodoros_today() == 0


def test_pomodoros_reset_at_midnight():
    s = Store()
    # a count stamped yesterday reads as 0 today (auto-reset)
    s.set_state("pomodoros", {"date": _iso(1), "count": 5})
    assert s.pomodoros_today() == 0
    assert s.bump_pomodoro() == 1                    # starts today fresh


def test_set_pomodoros_floors_at_zero():
    s = Store()
    s.set_pomodoros(-3)
    assert s.pomodoros_today() == 0
