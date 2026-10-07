"""Tests for FocusController: the focus/break cycle, honest skip logging, the
stop-resets-the-cycle fix, rewards, and long-break cadence. Needs a headless Qt
(the pill is a real widget) but drives the controller directly, no waiting."""
from datetime import datetime, timedelta

import pytest

from PyQt6.QtCore import QRect

from companion.store import Store
import companion.focus as focus_mod
from companion.focus import FocusController


class FakeSprite:
    """Records the cat cues so we can assert without a real sprite/screen."""
    def __init__(self):
        self.calls = []
    def begin_focus(self): self.calls.append("begin")
    def focus_pose(self, depth): self.calls.append(("pose", depth))
    def wake_stretch(self, celebrate=False): self.calls.append(("stretch", celebrate))
    def end_focus(self): self.calls.append("end")
    def body_anchor(self): return QRect(100, 100, 64, 64)


@pytest.fixture
def controller(qapp, monkeypatch):
    # never actually show/move the pill or defer real timers in tests
    monkeypatch.setattr(FocusController, "_update_pill", lambda self: None)
    # capture alert sounds instead of spawning a real audio player
    plays = []
    monkeypatch.setattr(focus_mod.chime, "play",
                        lambda key, vol=100, sp=None: plays.append((key, vol)))
    said = []
    store = Store()
    sprite = FakeSprite()
    rewards = []
    completes = []
    c = FocusController(sprite, store, lambda *a, **k: said.append(a),
                        on_reward=lambda: rewards.append(1),
                        on_complete=lambda s, e: completes.append((s, e)))
    c._said, c._rewards, c._completes, c._sprite = said, rewards, completes, sprite
    c._plays = plays
    return c


# ---- lifecycle ----------------------------------------------------------
def test_start_focus_enters_focus_phase(controller):
    controller.start_focus(25)
    assert controller.phase == "focus"
    assert controller.active()
    assert controller._session_start is not None
    assert "begin" in controller._sprite.calls


def test_stop_keeps_the_daily_count(controller):
    """The daily pomodoro tally is real work — stopping a session must NOT wipe
    it (it persists and resets on its own at midnight)."""
    controller.store.set_pomodoros(3)
    controller.start_focus(25)
    controller.stop()
    assert controller.phase == "idle"
    assert controller.store.pomodoros_today() == 3


# ---- finishing a full block --------------------------------------------
def test_finish_block_rewards_logs_and_counts(controller):
    controller.start_focus(25)
    controller._left = 0                            # countdown drained → block done
    controller._finish_phase()
    assert controller.store.pomodoros_today() == 1  # daily tally bumped
    assert controller._rewards == [1]               # a treat was banked
    assert len(controller._completes) == 1          # logged to the calendar
    assert ("stretch", True) in controller._sprite.calls   # celebrated


def test_finish_block_plays_the_focus_sound(controller):
    controller.store.config["focus_sound"] = "meow"
    controller.store.config["sound_volume"] = 55
    controller.start_focus(25)
    controller._left = 0
    controller._finish_phase()
    assert controller._plays == [("meow", 55)]


def test_a_break_wakes_the_cat_out_of_focus(controller):
    controller.start_focus(25)
    controller.start_break()
    calls = controller._sprite.calls
    assert calls.index("end") > calls.index("begin")          # not napping on the break


def test_finish_break_plays_the_break_sound(controller):
    controller.store.config["break_sound"] = "bowl"
    controller.start_break(long=False)
    controller._finish_phase()               # break → armed (paused) next focus
    assert ("bowl", 70) in controller._plays  # default volume 70


def test_break_end_arms_paused_focus_by_default(controller):
    """Default: after a break the next block is queued but paused, waiting for a
    manual ▶ — so nothing keeps cycling (or dinging) while you're away."""
    controller.start_break(long=False)
    controller._finish_phase()
    assert controller.phase == "focus"
    assert controller._armed is True
    assert controller._paused is True
    assert controller._session_start is None      # not counting yet
    assert not controller._timer.isActive()
    assert controller._rewards == []               # arming grants no treat

    # pressing ▶ (pause toggle) actually starts the block
    controller.toggle_pause()
    assert controller._armed is False
    assert controller._paused is False
    assert controller._session_start is not None
    assert controller._timer.isActive()


def test_break_end_can_autostart_focus_when_opted_in(controller):
    controller.store.config["focus_autostart_focus"] = True
    controller.start_break(long=False)
    controller._finish_phase()
    # autostart is deferred via a timer; nothing is armed/paused
    assert controller._armed is False


def test_finish_block_without_reward_config(controller):
    controller.store.config["focus_reward_treat"] = False
    controller.start_focus(25)
    controller._left = 0
    controller._finish_phase()
    assert controller._rewards == []                # no treat
    assert len(controller._completes) == 1          # still logged


# ---- custom focus length sticks across the cycle ------------------------
def test_custom_focus_length_survives_the_break(controller):
    """A custom 30-min pomodoro must not revert to the 25-min default after the
    break — the chosen length sticks for every block until Stop."""
    controller.store.config["focus_min"] = 25
    controller.start_focus(30)
    assert controller._total == 30 * 60
    controller._left = 0
    controller._finish_phase()                      # focus done → break
    controller.phase = "break"                      # (finish deferred the break)
    controller._finish_phase()                      # break done → next focus armed
    assert controller._total == 30 * 60             # still 30, not 25


def test_custom_length_reused_when_skipping_back_to_focus(controller):
    controller.store.config["focus_min"] = 25
    controller.start_focus(30)
    controller.skip()                               # focus → break
    controller.skip()                               # break → focus again
    assert controller._total == 30 * 60


def test_stop_resets_to_config_default(controller):
    controller.store.config["focus_min"] = 25
    controller.start_focus(30)
    controller.stop()
    controller.start_focus()                        # a brand-new session
    assert controller._total == 25 * 60


# ---- honest skip --------------------------------------------------------
def test_skip_focus_logs_actual_time_but_no_treat(controller):
    controller.start_focus(25)
    controller._left = controller._total - 10 * 60  # 10 real minutes ticked by
    controller.skip()
    assert controller.phase == "break"              # rolled into a break
    assert len(controller._completes) == 1          # logged the 10 real minutes
    s, e = controller._completes[0]
    assert 9 * 60 <= (e - s).total_seconds() <= 11 * 60   # ~10 min, not wall-clock
    assert controller._rewards == []                # but no treat — not a full block
    assert controller.store.pomodoros_today() == 0  # a skip doesn't count


def test_skip_focus_under_a_minute_is_not_logged(controller):
    controller.start_focus(25)
    controller._left = controller._total - 20       # only 20s ticked by
    controller.skip()
    assert controller._completes == []              # too short to record
    assert controller.phase == "break"


def test_finish_logs_ticked_time_not_wall_clock(controller):
    """A block left running across a suspend once logged 670 min. The countdown
    freezes while suspended, so we log the *ticked* focus time (≈ block length),
    not the overnight wall-clock span from session_start."""
    controller.start_focus(25)
    controller._session_start = (datetime.now().astimezone()
                                 - timedelta(hours=11))   # "started last night"
    controller._left = 0                                  # 25 min actually ticked
    controller._finish_phase()
    assert len(controller._completes) == 1
    s, e = controller._completes[0]
    assert (e - s).total_seconds() <= 26 * 60             # ~25 min, not ~670
    assert (e - s).total_seconds() >= 24 * 60


def test_skip_break_returns_to_focus(controller):
    """Skip moves to the next phase, it does not end the session (that's Stop)."""
    controller.start_break(long=False)
    assert controller.phase == "break"
    controller.skip()
    assert controller.phase == "focus"          # straight back to work
    assert controller.active()


# ---- long/short-break glance (pips) -------------------------------------
def test_cycle_info_counts_toward_long_break(controller):
    controller.store.config["sessions_before_long"] = 4
    controller.start_focus(25)
    controller.store.set_pomodoros(2)               # 2 banked this cycle
    long, pips = controller._cycle_info()
    assert pips == (2, 4) and long is False          # not the last block yet


def test_cycle_info_flags_the_block_before_a_long_break(controller):
    controller.store.config["sessions_before_long"] = 4
    controller.start_focus(25)
    controller.store.set_pomodoros(3)               # doing the 4th → long next
    long, pips = controller._cycle_info()
    assert pips == (3, 4) and long is True


def test_cycle_info_on_break_reports_break_length(controller):
    controller.store.config["sessions_before_long"] = 2
    controller.start_break(long=True)
    long, pips = controller._cycle_info()
    assert long is True and pips == (0, 0)


# ---- pause --------------------------------------------------------------
def test_toggle_pause_flips_and_stops_timer(controller):
    controller.start_focus(25)
    assert controller._timer.isActive()
    controller.toggle_pause()
    assert controller._paused and not controller._timer.isActive()
    controller.toggle_pause()
    assert not controller._paused and controller._timer.isActive()


def test_pausing_a_focus_block_wakes_the_cat_and_resuming_naps_again(controller):
    controller.start_focus(25)
    calls = controller._sprite.calls
    calls.clear()
    controller.toggle_pause()
    assert calls == [("stretch", False), "end"]          # up out of its nap
    calls.clear()
    controller.toggle_pause()
    assert calls == ["begin"]                            # and back to it


def test_toggle_pause_noop_when_idle(controller):
    controller.toggle_pause()
    assert not controller._paused
    assert controller.phase == "idle"


# ---- long-break cadence -------------------------------------------------
def test_long_break_every_n_sessions(controller, monkeypatch):
    """After `sessions_before_long` completed blocks, the auto-break is long."""
    controller.store.config["focus_autostart_breaks"] = True
    controller.store.config["sessions_before_long"] = 2
    breaks = []
    monkeypatch.setattr(controller, "start_break",
                        lambda long=False: breaks.append(long))
    # fire the deferred break immediately instead of after 1500 ms
    monkeypatch.setattr(focus_mod.QTimer, "singleShot",
                        staticmethod(lambda ms, fn: fn()))

    for _ in range(4):
        controller.phase = "focus"
        controller._session_start = None            # skip completion logging here
        controller._finish_phase()
    assert breaks == [False, True, False, True]     # long on every 2nd block


def test_the_pill_stays_where_it_is_and_goes_where_you_put_it(controller):
    """It used to follow the cat, all the way down to its bed in the corner."""
    from PyQt6.QtCore import QPoint
    c = controller
    c.start_focus(25)
    first = c.pill.pos()
    c._sprite.body_anchor = lambda: QRect(600, 500, 64, 64)   # the cat walks off to its bed
    c.skip()                                                   # focus -> break
    assert c.phase == "break" and c.pill.pos() == first        # the pill stays put
    c.pill.move(300, 200)                                      # you drag it somewhere
    c.pill.moved.emit(QPoint(300, 200))
    assert c.store.config["pill_pos"] == [300, 200]
    c.stop()
    assert not c.pill.isVisible()
    c.start_focus(25)                                          # next session: where you put it
    assert c.pill.pos() == QPoint(300, 200)
    c.pill.unpinned.emit()                                     # "Back beside PISI"
    assert c.store.config.get("pill_pos") is None
    beside = QRect(600, 500, 64, 64)
    assert c.pill.x() >= beside.right() or c.pill.x() + c.pill.width() <= beside.left() \
        or c.pill.y() + c.pill.height() <= beside.top()       # next to the cat, not on it
