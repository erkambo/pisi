"""JSON-backed persistence. One file, atomically written, human-readable.

The store is deliberately a plain dict on disk so you can open it in a text
editor, back it up, or hand-edit it. Nothing here depends on Qt.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date, timedelta
from typing import Any

from .log import get_logger
from .paths import data_file


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _today() -> str:
    return date.today().isoformat()


# settings of features that are gone; dropped from saves on load (an API key
# shouldn't linger in a file nothing reads)
OBSOLETE_CONFIG = ("weather_location", "use_llm", "llm_provider", "llm_model",
                   "anthropic_api_key", "gemini_api_key", "checkin_times",
                   "experimental_pets", "cat_color", "sprite_dir", "sprite_sheet",
                   "sprite_scale", "cat_skin", "pet_look")

DEFAULT_CONFIG: dict[str, Any] = {
    "wander": True,
    "quiet_start": "23:00",
    "quiet_end": "08:00",
    "cat_name": "Pisi",
    "speed": 2.0,                  # movement speed multiplier
    "pet_genome": None,            # the procedural pet (companion.creatures)
    # focus (pomodoro) sessions
    "focus_min": 25,               # length of a focus block, minutes
    "break_min": 5,                # short break, minutes
    "long_break_min": 15,          # long break, minutes
    "sessions_before_long": 4,     # focus blocks between long breaks (0 = never)
    "focus_autostart_breaks": True,  # roll straight into a break when a block ends
    "focus_autostart_focus": False,  # after a break, auto-start the next focus block
                                     # (off = pause & wait for a manual ▶, so nothing
                                     #  keeps cycling/dinging while you're away)
    "focus_reward_treat": True,    # bank a fish treat per completed block
    "focus_dnd": True,             # hush chatter and nudges while focusing
    # calendar (read-only iCal — Option A). One "secret address in iCal
    # format" per line (commas also accepted) — several calendars are
    # merged. Empty disables calendar awareness.
    "ical_url": "",
    "smart_nudges": True,          # calendar-aware focus/habit suggestions
    "presence": "home",            # "home" | "out" — you toggle it; gates home-only habits
    # Google Calendar two-way (Option B). OAuth client from a Google Cloud
    # project (Desktop app). Empty = feature off; tokens live in a separate file.
    "google_client_id": "",
    "google_client_secret": "",
    "first_run_done": False,
}


class Store:
    def __init__(self) -> None:
        self.path = data_file()
        fresh = not self.path.exists()
        self.data: dict[str, Any] = self._load()
        if fresh:
            self._first_cat()

    def _first_cat(self) -> None:
        """A fresh install gets its own cat: one of Pet Studio's sample cats
        (each checked on the whole quality panel), not always the same one.
        Change it any time in Pet Studio."""
        cfg = self.data["config"]
        if cfg.get("pet_genome"):
            return
        try:
            import random
            from .creatures import api
            cfg["pet_genome"] = random.choice(api.samples("feline")).to_dict()
        except Exception:  # noqa: BLE001 - no genome: the default cat, still fine
            pass

    # ---- load / save -------------------------------------------------
    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
            except Exception:
                # Corrupt file: back it up and start fresh rather than crash.
                get_logger(__name__).error(
                    "data.json unreadable, backing up to .corrupt.json and "
                    "starting fresh", exc_info=True)
                try:
                    # os.replace, not rename: rename refuses to overwrite an
                    # older backup on Windows, which would lose this one
                    os.replace(self.path, self.path.with_suffix(".corrupt.json"))
                except Exception:
                    pass
                data = {}
        else:
            data = {}

        data.setdefault("config", {})
        if data["config"].get("pet_look") == "original":
            # the old "original" look: the black cat they chose stays black
            from .creatures import api
            data["config"]["pet_genome"] = api.classic_genome().to_dict()
        for k in OBSOLETE_CONFIG:
            data["config"].pop(k, None)
        for k, v in DEFAULT_CONFIG.items():
            data["config"].setdefault(k, v)
        data.setdefault("habits", [])
        data.setdefault("state", {})

        return data

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
        # On Windows an antivirus/indexer scan can hold data.json open for a
        # moment, making the atomic replace fail with PermissionError — retry.
        for attempt in range(8):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))

    # ---- config ------------------------------------------------------
    @property
    def config(self) -> dict:
        return self.data["config"]

    def refresh_from_disk(self, keys) -> None:
        """Pick up config keys another PISI process (e.g. the standalone Pet
        Studio) wrote, without clobbering this process's other in-memory
        state."""
        try:
            disk = json.loads(self.path.read_text("utf-8")).get("config", {})
        except Exception:                        # noqa: BLE001 - keep what we have
            return
        for k in keys:
            self.data["config"][k] = disk.get(k, DEFAULT_CONFIG.get(k))

    def set_config(self, key: str, value: Any) -> None:
        self.data["config"][key] = value
        self.save()

    # ---- habits ------------------------------------------------------
    @property
    def habits(self) -> list[dict]:
        return self.data["habits"]

    def habit(self, hid: str) -> dict | None:
        return next((h for h in self.habits if h["id"] == hid), None)

    def add_habit(self, name: str, emoji: str = "⭐", cadence: str = "daily",
                  where: str = "anywhere") -> dict:
        h = {"id": _new_id(), "name": name, "emoji": emoji, "cadence": cadence,
             "where": where, "history": [], "created": _today()}
        self.habits.append(h)
        self.save()
        return h

    def set_habit_where(self, hid: str, where: str) -> None:
        """Where a habit can happen: 'anywhere' or 'home' (used to keep the
        planner from scheduling e.g. a workout while you're on campus)."""
        h = self.habit(hid)
        if h:
            h["where"] = where
            self.save()

    def remove_habit(self, hid: str) -> None:
        self.data["habits"] = [h for h in self.habits if h["id"] != hid]
        self.save()

    def set_habit_workspace(self, hid: str, paths: list[str], urls: list[str],
                            cmds: list[str] | None = None) -> None:
        """Attach a 'setup' (files + links + app/shell commands) to a habit, so
        PISI can open everything you need for it in one click when it's that
        habit's time. Passing all-empty clears it."""
        h = self.habit(hid)
        if not h:
            return
        cmds = list(cmds or [])
        if paths or urls or cmds:
            h["workspace"] = {"paths": list(paths), "urls": list(urls),
                              "cmds": cmds}
        else:
            h.pop("workspace", None)
        self.save()

    def habit_workspace(self, hid: str) -> dict | None:
        h = self.habit(hid)
        ws = h.get("workspace") if h else None
        if ws and (ws.get("paths") or ws.get("urls") or ws.get("cmds")):
            return ws
        return None

    def mark_done(self, hid: str, on: str | None = None) -> None:
        h = self.habit(hid)
        if not h:
            return
        d = on or _today()
        if d not in h["history"]:
            h["history"].append(d)
            h["history"].sort()
        self.save()

    def unmark_done(self, hid: str, on: str | None = None) -> None:
        h = self.habit(hid)
        if not h:
            return
        d = on or _today()
        h["history"] = [x for x in h["history"] if x != d]
        self.save()

    def done_today(self, hid: str) -> bool:
        h = self.habit(hid)
        return bool(h and _today() in h["history"])

    def days_since(self, hid: str) -> int | None:
        h = self.habit(hid)
        if not h or not h["history"]:
            return None
        last = max(date.fromisoformat(x) for x in h["history"])
        return (date.today() - last).days

    def count_last_days(self, hid: str, days: int = 7) -> int:
        h = self.habit(hid)
        if not h:
            return 0
        cutoff = date.today() - timedelta(days=days - 1)
        return sum(1 for x in h["history"] if date.fromisoformat(x) >= cutoff)

    def streak(self, hid: str) -> int:
        """Consecutive days up to today (or yesterday) the habit was done."""
        h = self.habit(hid)
        if not h or not h["history"]:
            return 0
        done = set(h["history"])
        d = date.today()
        if d.isoformat() not in done:
            d = d - timedelta(days=1)  # allow "today not yet done" without breaking streak
        streak = 0
        while d.isoformat() in done:
            streak += 1
            d -= timedelta(days=1)
        return streak

    # ---- state -------------------------------------------------------
    @property
    def state(self) -> dict:
        return self.data["state"]

    def set_state(self, key: str, value: Any) -> None:
        self.data["state"][key] = value
        self.save()

    # ---- treats (reward currency) -----------------------------------
    def treats(self) -> int:
        return int(self.state.get("treats", 0))

    def add_treats(self, n: int = 1) -> int:
        self.set_state("treats", max(0, self.treats() + n))
        return self.treats()

    def spend_treat(self) -> bool:
        if self.treats() <= 0:
            return False
        self.set_state("treats", self.treats() - 1)
        return True

    def planned_today(self) -> list[str]:
        p = self.state.get("planned_today") or {}
        if p.get("date") == _today():
            return list(p.get("habit_ids", []))
        return []

    def set_planned_today(self, habit_ids: list[str]) -> None:
        self.set_state("planned_today", {"date": _today(), "habit_ids": habit_ids})

    # ---- pomodoros completed today (drives the long-break cadence) ---
    def pomodoros_today(self) -> int:
        """How many focus blocks finished today. Date-stamped, so it resets on
        its own at midnight (a stale count from yesterday reads as 0)."""
        p = self.state.get("pomodoros") or {}
        return int(p.get("count", 0)) if p.get("date") == _today() else 0

    def bump_pomodoro(self, n: int = 1) -> int:
        c = max(0, self.pomodoros_today() + n)
        self.set_state("pomodoros", {"date": _today(), "count": c})
        return c

    def set_pomodoros(self, n: int) -> None:
        self.set_state("pomodoros", {"date": _today(), "count": max(0, int(n))})
