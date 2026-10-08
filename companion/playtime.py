"""Playing with the cat: toys on the floor, the laser, a wind-up mouse.

The cat stays on the floor (it runs and leaps; it never flies to the
cursor) and plays like a cat, using the rig so its paw and mouth land on
the toy:

* **toy**: a toy lies on the floor. Throw it (grab and flick) and the cat
  runs to where it's going, bats it when it's in reach, stalks and pounces
  on it from further off, and now and then picks it up and brings it back
  to you (it drops it by your cursor, ready for another throw).
* **laser**: the dot on or near the floor gets chased and pounced; up on the
  screen within a leap it jumps for it; higher up it sits and watches,
  tail twitching.
* **hunt**: a wind-up mouse scurries about; the cat stalks and pounces, and
  after a few catches carries it off proudly.

Everything is measured from the cat (``things.fit.CatFit``): where its paw
lands on a swipe, where its mouth reaches the floor, its size on screen.
"""
from __future__ import annotations

import math
import random
import time

from PyQt6.QtCore import QObject, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

from .playground import FeatherWand, FloorToy, PixelLaser, puff
from .screens import usable

TICK = 70                    # ms, the cat's own tick
FETCH_CHANCE = 0.35          # after a pounce, carry it back to you instead
TURN_SLACK = 30              # px behind its middle before it turns round
# stamina (0..1): what moves cost, how fast it comes back
COST = {"pounce": 0.07, "bat": 0.025, "run_s": 0.012, "climb": 0.06, "leap": 0.03}
RECOVER_S = 0.03             # per second resting (in a play pose)
REFILL_S = 150.0             # seconds away from play to get all its breath back
TIRED = 0.35                 # below: walks, pounces less, pauses to think
SPENT = 0.12                 # below: lies down for a breather
WORN_OUT = 3                 # breathers before it calls it a day
DOT_SETTLE_S = 0.5           # a laser dot must stay put this long before it climbs for it
REST = ("sit", "watch", "watchup", "sleep", "crouch", "pant")   # poses it gets its breath back in
BAT_NEAR = -34               # px: a toy this far inside the paw's reach is still batted
BORED_S = 9.0                # nobody threw it for this long: the cat brings it to you
REFETCH_S = 45.0             # ... at most this often (otherwise it plays on its own)


class PlayTime(QObject):
    ended = pyqtSignal(str)              # why: "stopped", "caught", "bored", "worn out"
    note = pyqtSignal(str)               # something worth a speech bubble

    def __init__(self, sprite, fit_fn, toy_fn) -> None:
        """``fit_fn()`` -> the cat's CatFit; ``toy_fn(item_id)`` -> a toy
        Rendered for this cat."""
        super().__init__()
        self.sprite = sprite
        self.fit_fn = fit_fn
        self.toy_fn = toy_fn
        self.mode: str | None = None
        self.toy: FloorToy | None = None
        self.laser: PixelLaser | None = None
        self.wand: FeatherWand | None = None
        self.fit = None
        self.catches = 0
        self.pounces = 0
        self.stamina = 1.0                   # carried from one play to the next
        self._played_until: float | None = None   # when play last stopped
        self.misses = 0
        self.breathers = 0
        self.trips = 0                       # legs of the way up (or down) the page
        self._dot_at = None                  # (x, y, since): where the laser dot is resting
        self._trip_retry = 0.0
        self._unreachable = None             # a toy it can't get to: until when it just watches
        self._said_unreachable = -1e9
        self.show_meter = True               # the energy pips above the cat while playing
        self._missing = False
        self._zoom_back = None
        self._pounce_choice: bool | None = None  # decided once per approach, not per tick
        self._plan: str | None = None          # what the cat is doing right now
        self._plan_until = 0.0
        self._last_throw = 0.0
        self._last_fetch = -1e9
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ---- starting / stopping -------------------------------------------------
    def active(self) -> bool:
        return self.mode is not None

    def _begin(self, mode: str) -> bool:
        self.stop(quiet=True)
        sp = self.sprite
        if not sp.can_play():
            return False
        self.fit = self.fit_fn()
        if self.fit is None:
            return False
        sp._drop_thing()
        if not (mode == "laser" and sp.ledge() is not None):   # the laser can be chased up there
            sp._leave_surface()
            if sp.y() < sp._floor_y() - 2:
                sp._vy = 0.0
                sp.state = "fall"               # down from a page first
        sp.in_play = True
        self.mode = mode
        self.catches = 0
        self.pounces = 0
        self.misses = 0
        self.breathers = 0
        self.trips = 0
        self._dot_at = None
        self._unreachable = None
        self._catch_breath()
        self._plan = None
        self._last_throw = time.monotonic()
        self._timer.start(TICK)
        return True

    def start_toy(self, item_id: str, at_x: float | None = None, carried: bool = False,
                  drop_y: float | None = None) -> bool:
        """A toy on the floor (at ``at_x``, or just ahead of the cat), or
        already in the cat's mouth (``carried``), or dropped from ``drop_y``
        at ``at_x`` (right-clicked on a page: it falls onto the text below)."""
        if not self._begin("toy"):
            return False
        self._make_toy(item_id)
        if carried:
            self.toy.pick_up()
            self.sprite.carry(self.toy.toy, self.toy.scale)
            self._fetch_to_cursor()
        else:
            self._drop_toy_at(at_x if at_x is not None else self._ahead_of_cat(140))
            if drop_y is not None and drop_y < self.toy.ground_y() - self.toy.th:
                self.toy.ledge = None
                self.toy.y_f = drop_y - self.toy.th
                self.toy.vy = 0.0
                self.toy._sync()
        return True

    def start_hunt(self, item_id: str = "toy.mouse") -> bool:
        if not self._begin("hunt"):
            return False
        self._make_toy(item_id)
        self.toy.windup = True
        self._drop_toy_at(self._ahead_of_cat(260))
        self.toy.scurry()
        QTimer.singleShot(25_000, lambda: self._hunt_over("bored"))
        return True

    def start_laser(self) -> bool:
        if not self._begin("laser"):
            return False
        if self.laser is None:
            self.laser = PixelLaser(self.sprite.pixel_scale())
        self.laser.start()
        self.sprite.chase_boost = 1.6
        return True

    def start_wand(self) -> bool:
        """The feather wand: you hold the stick, the cat goes for the feather."""
        if not self._begin("wand"):
            return False
        if self.wand is None:
            self.wand = FeatherWand(self.sprite.pixel_scale())
        floor, _b = self._floor()
        self.wand.floor_y = floor
        self.wand.start()
        self._swatted = False
        return True

    def stop(self, quiet: bool = False) -> None:
        was = self.mode
        if was is not None:
            self._played_until = time.monotonic()
        self._timer.stop()
        self.mode = None
        self._plan = None
        sp = self.sprite
        sp.chase_boost = 1.0
        sp.in_play = False
        sp.tired = False
        sp.set_meter(None)
        if sp._next_decision >= 10 ** 6:          # held in a play pose: let it go about its day
            sp._next_decision = sp._state_ticks + 20
        if self.laser:
            self.laser.stop()
        if self.wand:
            self.wand.stop()
        if self.toy:
            self.toy.stop()
            self.toy.deleteLater()
            self.toy = None
        if self.sprite.carrying() is not None and not quiet:
            self.sprite.let_go()
        if was and not quiet:
            self.ended.emit("stopped")

    # ---- the toy ----------------------------------------------------------------
    def _make_toy(self, item_id: str) -> None:
        if self.toy is not None:
            self.toy.stop()
            self.toy.deleteLater()
        r = self.toy_fn(item_id)
        self.toy = FloorToy(r, self.sprite.pixel_scale())
        if self.mode == "toy":
            self.toy.ledges_fn = self._toy_ledges     # thrown onto the text, it stays up there
        self.toy.thrown.connect(self._thrown)
        self.toy.grabbed.connect(self._grabbed)
        self.toy.landed.connect(self._toy_landed)

    def _toy_ledges(self) -> list:
        """The lines of text on the page in front (x0, x1, y, key), for a
        toy to land on: anything solid at least as wide as the toy."""
        sp = self.sprite
        sf = sp.surfaces
        if sf is None or not sf.active or sp._focus:
            return []
        tw = self.toy.tw if self.toy is not None else 0
        return [(b.x0, b.x1, b.edge, (b.x0, b.x1, b.kind, b.block)) for b in sf.boxes()
                if b.x1 - b.x0 >= tw]

    def _toy_landed(self, x: float, speed: float) -> None:
        y = self.toy.ground_y() if self.toy is not None else self._floor()[0]
        puff(x, y, self.sprite.pixel_scale(), n=4, strength=min(1.0, speed / 900.0))

    def _dust_at_paw(self, n: int = 6, strength: float = 1.0) -> None:
        floor, _b = self._floor()
        paw = self.sprite.paw_global()
        x = paw.x() if paw else self._ahead_of_cat(20)
        puff(x, floor, self.sprite.pixel_scale(), n=n, strength=strength)

    def _floor(self) -> tuple[int, tuple[int, int]]:
        """What the cat stands on (global y: the floor, or its ledge on a
        page) and the screen's left and right."""
        scr = self.sprite.screen() or QApplication.primaryScreen()
        g = usable(scr)
        return self.sprite.ground_line(), (g.left(), g.right() + 1)

    def _drop_toy_at(self, x: float) -> None:
        """Put the toy down at x, where the cat stands (the floor, or its
        line of text)."""
        sp = self.sprite
        _g, bounds = self._floor()
        floor = sp.floor_line(sp.screen() or QApplication.primaryScreen())
        x = min(max(x, bounds[0] + 20), bounds[1] - 20)
        ledge = None
        if sp.ledge() is not None and self.toy.ledges_fn is not None:
            feet = sp.ground_line()
            near = [ln for ln in self._toy_ledges() if ln[0] <= x <= ln[1] and abs(ln[2] - feet) <= 3]
            ledge = near[0] if near else None
        self.toy.place(x, floor, bounds, ledge)

    def _thrown(self) -> None:
        self._last_throw = time.monotonic()
        self._pounce_choice = None
        self._plan = None                        # whatever it was doing: after it!

    def _grabbed(self) -> None:
        self._last_throw = time.monotonic()
        if self._plan in ("fetch", "drop"):
            self._plan = None

    # ---- geometry, from the rig ---------------------------------------------------
    def _scale(self) -> float:
        cur = self.sprite._current_frame()
        return cur[1] if cur else float(self.sprite.pixel_scale())

    def _frame_x(self, fx: float, facing: int) -> float:
        """Global x of frame column ``fx`` (a facing-right frame px) now."""
        bx, _by, _w, _h = self.sprite._sprite_box()
        fw = self.sprite.sheet.frame_w if self.sprite.sheet else 48
        col = fx if facing > 0 else fw - 1 - fx
        return self.sprite.x() + bx + (col + 0.5) * self._scale()

    def _window_x_for(self, fx: float, facing: int, target_x: float) -> float:
        """Window x that puts frame column ``fx`` over ``target_x``."""
        return self.sprite.x() + (target_x - self._frame_x(fx, facing))

    def _cat_x(self) -> float:
        from .sprite import W
        return self.sprite.x() + W / 2

    def _facing_to(self, x: float) -> int:
        """Which way to face for something at x: keep facing the way it is
        unless the thing is clearly behind (no flip-flopping over a toy right
        under its nose)."""
        f = self.sprite.facing
        return -f if (x - self._cat_x()) * f < -TURN_SLACK else f

    def _ahead_of_cat(self, px: float) -> float:
        return self._cat_x() + self.sprite.facing * px

    # ---- personality ----------------------------------------------------------------
    def _energy(self) -> float:
        return float(getattr(self.fit, "energy", 0.5)) if self.fit is not None else 0.5

    def _spend(self, what: str, amount: float | None = None) -> None:
        self.stamina = max(0.0, self.stamina - (COST[what] if amount is None else amount))

    def _tired(self) -> bool:
        return self.stamina < TIRED

    def _show_energy(self) -> None:
        """What the player can see of it: the trudge, and the blue pips."""
        sp = self.sprite
        sp.tired = self._tired()
        sp.set_meter(self.stamina if self.show_meter else None)

    def _catch_breath(self) -> None:
        """Back to play: it got its breath back while it wasn't playing (all
        of it after a couple of minutes, so after any nap or focus block)."""
        if self._played_until is not None:
            away = max(0.0, time.monotonic() - self._played_until)
            self.stamina = min(1.0, self.stamina + away / REFILL_S)
        self._played_until = None

    def _recover(self) -> None:
        sp = self.sprite
        if sp.state in REST and not sp.busy():
            self.stamina = min(1.0, self.stamina + RECOVER_S * TICK / 1000.0)

    def _gait(self, far: bool) -> str:
        return "run" if far and not self._tired() else "walk"

    def _breather(self) -> bool:
        """Worn out: flop down flat and pant for a bit. After a few of these
        it's had enough (True: play is over)."""
        sp = self.sprite
        self.breathers += 1
        if self.breathers >= WORN_OUT and self.mode in ("toy", "wand", "laser", "hunt"):
            self._worn_out()
            return True
        sp.state = "pant" if "pant" in sp.sheet.anims else "crouch"
        sp._state_ticks = 0
        sp._next_decision = 10 ** 6
        self._set_plan("breather", random.uniform(6.0, 12.0) * (1.4 - self._energy() * 0.6))
        if self.breathers == 1:
            self.note.emit("tired")
        return False

    def _worn_out(self) -> None:
        """All played out: it stops for good (the app sends it off to bed)."""
        sp = self.sprite
        if sp.carrying() is not None:
            sp.let_go()
        self.stop(quiet=True)
        self.ended.emit("worn out")

    def _watch(self, x: float, up: bool = False, seconds: float = 0.0) -> None:
        """Eyes on it: sitting up, ears up, tail tip going."""
        sp = self.sprite
        sp.face(x)
        want = "watchup" if up else "watch"
        if want in sp.sheet.anims and not sp.busy():
            sp.state = want
            sp._state_ticks = 0
            sp._next_decision = 10 ** 6
        if seconds:
            self._set_plan("watch", seconds)

    # ---- the cat's moves ---------------------------------------------------------------
    def _set_plan(self, plan: str, seconds: float = 0.0) -> None:
        self._plan = plan
        self._plan_until = time.monotonic() + seconds

    def _approach(self, x: float, facing: int, fx: float) -> None:
        """Run so that frame column ``fx`` ends up at ``x`` facing ``facing``."""
        sp = self.sprite
        tx = self._window_x_for(fx, facing, x)
        if abs(tx - sp.x()) > 4:
            gait = self._gait(abs(tx - sp.x()) > 140)
            sp.chase_boost = ((1.1 + 0.7 * self._energy()) if gait == "run"
                              else 0.75 if self._tired() else 1.0)
            sp.run_to(tx, gait)
            if gait == "run":
                self._spend("run", COST["run_s"] * TICK / 1000.0)
        self._set_plan("approach")

    def _bat(self) -> None:
        sp = self.sprite
        toy = self.toy

        def tap():
            if self.toy is toy and toy is not None:
                self._pounce_choice = None
                k = random.uniform(170.0, 430.0)
                toy.hit(sp.facing * k, -random.uniform(0.0, 240.0))
                floor, _b = self._floor()
                puff(toy.center_x(), floor, self.sprite.pixel_scale(), n=3, strength=0.5)
        sp.on_frame("bat", 5, tap)
        sp.do_anim("bat")
        self._spend("bat")
        self._set_plan("bat", 0.9)

    def _stalk_then_pounce(self, x: float) -> None:
        sp = self.sprite
        sp.state = "stalk" if "stalk" in sp.sheet.anims else "crouch"
        sp._state_ticks = 0
        sp._next_decision = 10 ** 6
        self._pounce_x = x
        # a fresh cat wiggles long and hard; a tired one barely bothers
        self._set_plan("stalk", random.uniform(0.5, 1.1) * (0.35 + 0.65 * self.stamina))

    def _pounce(self) -> None:
        """Leap at it. Tired or unlucky, it misses: lands short or overshoots."""
        sp = self.sprite
        miss_p = 0.2 + 0.3 * (1.0 - self.stamina) - 0.12 * self._energy()
        target = self._pounce_x
        self._missing = random.random() < miss_p
        if self._missing:
            target += sp.facing * random.choice((-1, 1)) * random.uniform(40, 70)
        land = self._window_x_for(self.fit.bat_target[0], sp.facing, target)
        sp.pounce_to(land, lift=random.uniform(22, 40) * (0.8 + 0.4 * self._energy()))
        self.pounces += 1
        self._spend("pounce")
        self._set_plan("pounce")

    def _shrug(self) -> None:
        """Missed. Pretend nothing happened."""
        sp = self.sprite
        self.misses += 1
        for a in random.sample(("tailswish", "lookaround"), 2):
            if sp.do_anim(a):
                break
        self._set_plan("shrug", random.uniform(0.6, 1.4))

    def _zoomies(self) -> None:
        """Too excited to stand still: tear off one way and back."""
        if self.mode is None:
            return
        sp = self.sprite
        _floor, (lo, hi) = self._floor()
        d = random.choice((-1, 1))
        far = sp.x() + d * random.uniform(260, 460)
        if not (lo + 40 < far < hi - 200):
            far = sp.x() - d * random.uniform(260, 460)
        self._zoom_back = sp.x()
        sp.chase_boost = 2.2
        sp.run_to(far, "run")
        self._dust_at_paw(5, 0.7)
        self._spend("pounce", 0.05)
        self._set_plan("zoomies")

    def _pick_up(self) -> None:
        sp = self.sprite
        toy = self.toy

        def bite():
            if self.toy is toy and toy is not None:
                toy.pick_up()
                sp.carry(toy.toy, toy.scale)
        sp.on_frame("pickup", 5, bite)
        sp.do_anim("pickup")
        self._set_plan("pickup", 1.2)

    def _fetch_to_cursor(self) -> None:
        """Carry it over to you (down off the page first)."""
        sp = self.sprite
        cx = QCursor.pos().x()
        if sp.state == "walk" and sp._web_after is not None:
            return                                    # on its way to the edge to get down
        if sp.ledge() is not None and sp.get_down(sp.x() + (cx - self._cat_x())):
            self._spend("leap")
            self._set_plan("pickup")                  # (lands, then carries on over to you)
            return
        side = -1 if cx < self._cat_x() else 1
        # stop a cat-length short of the cursor, facing it
        target = cx - side * 70
        sp.run_to(self._window_x_for(24, side, target), "walk")
        self._set_plan("fetch")

    def _put_down(self) -> None:
        sp = self.sprite
        toy = self.toy

        def release():
            m = sp.mouth_global()
            if self.toy is toy and toy is not None:
                sp.let_go()
                self._drop_toy_at(m.x() if m else self._ahead_of_cat(40))
                self.note.emit("dropped")
        sp.on_frame("drop", 4, release)
        sp.do_anim("drop")
        self._set_plan("drop", 1.4)
        self._last_throw = time.monotonic()

    # ---- the loop -----------------------------------------------------------------
    def _tick(self) -> None:
        sp = self.sprite
        if self.mode is None:
            return
        was_jump = getattr(self, "_jumping", False)
        self._jumping = sp.state == "hop" and bool(sp._hop) and sp._hop.get("anim") == "jump"
        if was_jump and not self._jumping:
            self._dust_at_paw(6, 0.9)
        self._show_energy()
        if sp._dragging or sp.state in ("fall", "climb"):
            return
        now = time.monotonic()
        if self.mode == "laser":
            self._laser_tick(now)
            return
        if self.mode == "wand":
            self._wand_tick(now)
            return
        toy = self.toy
        if toy is None:
            return
        plan = self._plan
        # finishing moves: let them play out
        if plan == "stalk":
            if now >= self._plan_until:
                self._pounce()
            return
        if plan == "pounce":
            if sp.state != "hop":
                self._dust_at_paw(7, 1.0)              # landing
                near = abs(toy.center_x() - self._frame_x(self.fit.bat_target[0], sp.facing))
                if self._missing or near >= 36:
                    if toy.on_floor() and near < 90 and not toy.held:
                        toy.hit((1 if toy.center_x() > self._cat_x() else -1) * random.uniform(120, 260),
                                -random.uniform(80, 200))   # startled, it skitters off
                    self._missing = False
                    self._shrug()
                    return
                if toy.on_floor():
                    toy.pin()
                    toy.freeze(0.14)
                    sp.hit_pause(0.14)                  # the catch: a beat
                    self.catches += 1
                    if self.mode == "hunt":
                        if self.catches >= 3:
                            self._hunt_over("caught")
                            return
                        QTimer.singleShot(900, lambda t=toy: t.scurry(self._cat_x()) if self.toy is t else None)
                    elif random.random() < FETCH_CHANCE:
                        self._plan = None
                        self._go_pick_up()
                        return
                    elif (self.stamina > 0.6 and self._energy() > 0.45
                          and random.random() < 0.12 + 0.12 * self._energy()):
                        QTimer.singleShot(400, self._zoomies)
                        self._set_plan("wait", 0.5)
                        return
                self._plan = None
            return
        self._recover()
        if plan in ("bat", "pickup", "drop", "shrug", "wait") and (sp.busy() or now < self._plan_until):
            return
        if plan == "breather":
            if now < self._plan_until and not (toy.speed() > 600 and abs(toy.center_x() - self._cat_x()) < 250):
                return
            self.stamina = max(self.stamina, 0.45 + 0.2 * self._energy())
            sp.state = "sit"
            self._plan = None
            return
        if plan == "watch":
            if now < self._plan_until and toy.speed() < 200:
                return
            self._plan = None
        if plan == "zoomies":
            if sp.state == "walk":
                return
            if self._zoom_back is not None:
                back, self._zoom_back = self._zoom_back, None
                sp.run_to(back, "run")
                return
            sp.chase_boost = 1.0
            self._plan = None
            return
        if plan == "pickup":
            if sp.carrying() is not None:
                if self.mode == "tidy":
                    self._to_basket()
                elif self.mode == "hunt":
                    self._parade()
                else:
                    self._fetch_to_cursor()
            else:
                self._plan = None
            return
        if plan == "fetch":
            if sp.state == "walk":
                return
            sp.face(QCursor.pos().x())
            self._put_down()
            return
        if plan == "parade":
            if sp.state != "walk":
                self._hunt_over("caught", parade_done=True)
            return
        if sp.carrying() is not None:
            if self.mode == "tidy":
                self._to_basket()
            else:
                self._fetch_to_cursor()
            return
        if sp.busy():
            return
        if sp.state == "walk" and sp._web_after is not None:
            return                                   # on its way up / along the page
        if self._to_toys_level(now):
            return
        if self.mode == "tidy":
            if self._plan != "to_pickup" and toy.resting():
                self._go_pick_up()
            elif self._plan == "to_pickup" and sp.state != "walk":
                self._pick_up()
            elif not toy.resting():
                self._approach(toy.center_x(), self._facing_to(toy.center_x()), self.fit.toy_spot[0])
            return
        if toy.held:
            self._watch(toy.center_x(), up=toy.y_f < self._floor()[0] - sp._body().stand)
            return
        if self.stamina < SPENT and self.mode != "tidy":
            self._breather()
            return
        if (toy.resting() and self._plan in (None, "approach") and
                random.random() < (0.04 + 0.1 * (1.0 - self.stamina)) * (1.2 - self._energy())):
            self._watch(toy.center_x(), seconds=random.uniform(0.5, 1.6))   # considering it
            return
        self._chase(now)

    def tidy(self, basket_fn) -> None:
        """Playtime's over: pick the toy up and put it back in the basket
        (``basket_fn()`` -> True if the cat set off to put it there)."""
        if self.mode is None:
            return
        self._basket_fn = basket_fn
        if self.laser:
            self.laser.stop()
        if self.mode == "laser" or self.toy is None:
            self.stop()
            return
        self.toy.windup = False
        self.mode = "tidy"
        self._plan = None

    def _to_basket(self) -> None:
        sp = self.sprite
        fn = getattr(self, "_basket_fn", None)
        # play's over like any other way it ends: the energy pips go, the
        # cat's out of play mode, and it starts getting its breath back
        self.stop(quiet=True)                  # (quiet: it keeps the toy in its mouth)
        if fn is None or not fn():
            sp.let_go()
        self.ended.emit("tidied")

    def _go_pick_up(self) -> None:
        """Stand where the mouth meets the toy's grip, then pick it up."""
        sp = self.sprite
        toy = self.toy
        facing = self._facing_to(toy.center_x())
        grip_x = toy.x_f + (toy.toy.spots["grip"][0] + 0.5) * toy.scale if toy.facing > 0 else \
            toy.x_f + (toy.toy.w - 1 - toy.toy.spots["grip"][0] + 0.5) * toy.scale
        tx = self._window_x_for(self.fit.toy_spot[0], facing, grip_x)
        sp.facing = facing
        if abs(tx - sp.x()) > 3:
            sp.run_to(tx, "walk")
            self._set_plan("to_pickup")
        else:
            self._pick_up()

    def _chase(self, now: float) -> None:
        sp = self.sprite
        toy = self.toy
        if self._plan == "to_pickup":
            if sp.state == "walk":
                return
            if toy.resting():
                self._pick_up()
                return
            self._plan = None
        tx = toy.center_x()
        if not toy.on_floor() or toy.speed() > 230:
            tx = tx + toy.vx * 0.3               # where it's going
        facing = self._facing_to(tx)
        paw = self._frame_x(self.fit.bat_target[0], facing)
        dist = (tx - paw) * facing
        if toy.on_floor() and BAT_NEAR <= dist <= 14 and toy.speed() < 300:
            if sp.facing != facing:
                sp.face(tx)
                return
            self._bat()
            return
        if self._pounce_choice is None and toy.on_floor() and toy.speed() < 260:
            # stalk it or just walk up to it? one decision per approach (a
            # per-tick roll would make slow cats pounce the most)
            pounce_p = (0.55 if not self._tired() else 0.2) * (0.35 + 0.9 * self._energy())
            self._pounce_choice = random.random() < pounce_p
        if toy.on_floor() and 60 <= dist <= 240 and toy.speed() < 260 and self._pounce_choice:
            self._pounce_choice = None
            if toy.speed() > 30:
                tx = toy.center_x() + toy.vx * 0.45   # where it'll be when it lands
            sp.facing = facing
            self._stalk_then_pounce(tx)
            return
        if (self.mode == "toy" and toy.resting() and now - self._last_throw > BORED_S
                and now - self._last_fetch > REFETCH_S):
            self._last_fetch = now
            self._go_pick_up()                   # bring it to you: "throw it!"
            return
        self._approach(tx, facing, self.fit.bat_target[0])

    def _parade(self) -> None:
        """Hunt over: off it trots with the mouse."""
        sp = self.sprite
        self.note.emit("caught it!")
        sp.run_to(sp.x() + sp.facing * 260, "walk")
        self._set_plan("parade")

    def _hunt_over(self, why: str, parade_done: bool = False) -> None:
        if self.mode != "hunt":
            return
        if why == "caught" and not parade_done and self.toy is not None:
            self.toy.windup = False
            self.toy.pin()
            self._go_pick_up()
            return
        if parade_done:
            self.sprite.let_go()
        mode = self.mode
        self.stop(quiet=True)
        if mode:
            self.ended.emit(why)

    # ---- the laser -------------------------------------------------------------------
    def _laser_tick(self, now: float) -> None:
        sp = self.sprite
        self._track_dot(QCursor.pos(), now)
        if sp.busy():
            return
        self._recover()
        if self._plan == "breather":
            if now < self._plan_until:
                return
            self.stamina = max(self.stamina, 0.45 + 0.2 * self._energy())
            sp.state = "sit"
            self._plan = None
            return
        if self.stamina < SPENT:
            self._breather()
            return
        if sp.state == "walk" and sp._web_after is not None:
            return                               # on its way to a wall / a take-off spot
        dot = QCursor.pos()
        floor, _bounds = self._floor()
        height = floor - dot.y()                 # how far above what it stands on
        body = sp._body().stand
        if self._page_trip(dot, height, body, now):
            return
        facing = self._facing_to(dot.x())
        paw = self._frame_x(self.fit.bat_target[0], facing)
        dist = (dot.x() - paw) * facing
        if height < body * 0.6:                  # on the floor: chase, pounce
            if BAT_NEAR <= dist <= 16:
                if sp.facing != facing:
                    sp.face(dot.x())
                else:
                    self._bat_at_nothing()
            elif 50 <= dist <= 220 and random.random() < 0.25:
                sp.facing = facing
                self._pounce_x = dot.x()
                self._pounce()
                self._plan = None
            else:
                self._approach(dot.x(), facing, self.fit.bat_target[0])
            return
        under = abs(dot.x() - self._cat_x()) < 50
        if height < body * 2.4:                  # within a leap
            if under:
                if random.random() < 0.18 + 0.15 * self._energy():
                    sp.jump_up(height * 0.8)
                    self._spend("pounce")
                else:
                    self._watch(dot.x(), up=True)
                return
            gait = self._gait(True)
            if gait == "run":
                self._spend("run", COST["run_s"] * TICK / 1000.0)
            sp.run_to(sp.x() + (dot.x() - self._cat_x()), gait)
            return
        # too high: sit underneath and watch it, tail going
        if abs(dot.x() - self._cat_x()) > 160:
            sp.run_to(sp.x() + (dot.x() - self._cat_x()), "walk")
        else:
            self._watch(dot.x(), up=True)

    def _track_dot(self, dot: QPoint, now: float) -> None:
        """Where the dot has been resting, and since when (a flick across
        the page isn't worth a climb)."""
        at = self._dot_at
        near = self.sprite._body().stand * 0.6
        if at is None or abs(dot.x() - at[0]) > near or abs(dot.y() - at[1]) > near:
            self._dot_at = (dot.x(), dot.y(), now)

    def _to_toys_level(self, now: float) -> bool:
        """The toy came to rest up on the text (or back down on the floor)
        and the cat isn't there: off it goes after it, a leg at a time.
        True while it's busy getting there (or watching one it can't reach)."""
        sp, toy = self.sprite, self.toy
        if toy is None or toy.held or toy.carried or not toy.on_floor() or toy.speed() > 200:
            return False
        if abs(toy.ground_y() - sp.ground_line()) <= 4:
            self._unreachable = None
            return False
        if self._unreachable is not None and now < self._unreachable:
            self._watch(toy.center_x(), up=toy.ground_y() < sp.ground_line())
            return True
        x, y = toy.center_x(), toy.ground_y()
        kind = sp.toward(x, y - 2, rise=sp._body().stand * 0.25)
        if kind is not None:
            self._spend("climb" if kind in ("climb", "scale") else "leap" if kind == "hop" else
                        "run", COST["run_s"] if kind in ("walk", "run") else None)
            self.trips += 1
            self._set_plan("trip")
            self._pounce_choice = None
            return True
        if self._leap_at_toy():
            return True
        kind = sp.toward(x, y - 2)                     # nowhere to stand by it: a leap below it
        if kind is not None:
            self._spend("climb" if kind in ("climb", "scale") else "leap" if kind == "hop" else
                        "run", COST["run_s"] if kind in ("walk", "run") else None)
            self.trips += 1
            self._set_plan("trip")
            return True
        if toy.ledge is None and sp.ledge() is not None and \
                sp.get_down(sp.x() + (x - self._cat_x())):     # it's down on the floor: get down
            self._spend("leap")
            self.trips += 1
            self._set_plan("trip")
            return True
        # no way there: eyes on it for a bit (throw it again, or fetch it down)
        self._unreachable = now + 4.0
        if self.mode == "toy" and now - self._said_unreachable > 25.0:
            self._said_unreachable = now
            self.note.emit("out of reach")
        self._watch(toy.center_x(), up=True)
        return True

    def _leap_at_toy(self) -> bool:
        """The toy is up somewhere the cat can't stand (on a button, a ledge
        with no room over it) but within a leap of where it is: under it,
        then up on its hind legs' worth of a jump to knock it down."""
        sp, toy = self.sprite, self.toy
        body = sp._body()
        height = sp.ground_line() - toy.ground_y()
        if height <= 0 or height > body.max_rise * 0.85:
            return False
        x = toy.center_x()
        dx = x - self._cat_x()
        if abs(dx) > body.w * 0.3:
            to = sp._on_ledge_x(sp.x() + dx)
            if abs(x - (to - sp.x() + self._cat_x())) > body.w * 0.3:
                return False                           # its ledge doesn't go under it
            sp.run_to(to, self._gait(abs(dx) > 140))
            self._set_plan("approach")
            return True
        sp.face(x)
        sp.jump_up(height)                             # high enough for its paws to get there
        self._spend("pounce")

        def knock():
            """Only if a paw is on it: no batting it from across the gap."""
            if self.toy is not toy or toy.ledge is None or toy.held or toy.carried:
                return
            paw = sp.paw_global()
            px, py = (paw.x(), paw.y()) if paw is not None else (self._cat_x(), sp.y())
            slack = max(toy.tw, toy.th) * 0.5
            if toy.x_f - slack <= px <= toy.x_f + toy.tw + slack and \
                    toy.y_f - slack <= py <= toy.y_f + toy.th + slack:
                toy.ledge = None
                toy.hit(sp.facing * random.uniform(160.0, 320.0), -random.uniform(80.0, 200.0))
        if "jump" in sp.sheet.anims:
            for fi in range(2, 8):                     # any frame of the jump its paw touches it
                sp.on_frame("jump", fi, knock)
        self._set_plan("bat", 0.9)
        return True

    def _page_trip(self, dot: QPoint, height: float, body: float, now: float) -> bool:
        """On a web page: up the text after a dot too high to leap for,
        across to the ledge it's on, down after one below. One leg at a
        time (a leap, a climb up the side of a paragraph); the next tick
        looks again. True if it set off."""
        sp = self.sprite
        if sp.surfaces is None or sp._page() is None:
            return False
        at = self._dot_at
        if at is None or now - at[2] < DOT_SETTLE_S or now < self._trip_retry:
            return False
        seg = sp.ledge()
        above = height > body * 2.4
        below = seg is not None and height < -body * 0.6
        beside = seg is not None and not (seg.x0 - body * 0.5 <= dot.x() <= seg.x1 + body * 0.5)
        if not (above or below or beside):
            return False
        if self._tired() and not below:
            return False                               # too tired to climb: watches from here
        kind = sp.toward(dot.x(), dot.y())
        if kind is None:
            if below and sp.get_down(sp.x() + (dot.x() - self._cat_x())):   # nowhere better: get down
                self._spend("leap")
                self.trips += 1
                return True
            self._trip_retry = now + 1.5               # no way there from here: just watch
            return False
        self._spend("climb" if kind in ("climb", "scale") else "leap" if kind == "hop" else
                    "run", COST["run_s"] if kind in ("walk", "run") else None)
        self.trips += 1
        self._set_plan("trip")
        return True

    # ---- the feather wand --------------------------------------------------------------
    def _paw_near(self, pt: QPoint, reach: float) -> bool:
        paw = self.sprite.paw_global()
        if paw is None:
            return False
        return abs(paw.x() - pt.x()) <= reach and abs(paw.y() - pt.y()) <= reach * 1.3

    def _wand_tick(self, now: float) -> None:
        sp, wand = self.sprite, self.wand
        if wand is None:
            return
        f = wand.feather()
        fvx, fvy = wand.velocity()
        s = self.sprite.pixel_scale()
        # in the air: a paw going past the feather swats it
        if self._jumping and not self._swatted and self._paw_near(f, 9 * s):
            self._swatted = True
            wand.swat(sp.facing * random.uniform(350, 700), -random.uniform(250, 600))
            sp.hit_pause(0.1)
            self.catches += 1
            return
        if not self._jumping:
            self._swatted = False
        plan = self._plan
        if plan == "stalk":
            if now >= self._plan_until:
                self._pounce_x = f.x()
                self._pounce()
            return
        if plan == "pounce":
            if sp.state != "hop":
                self._dust_at_paw(7, 1.0)
                paw = sp.paw_global()
                if not self._missing and paw is not None and self._paw_near(f, 12 * s):
                    wand.pin(QPoint(paw.x(), paw.y() - s), random.uniform(0.4, 0.9))
                    sp.hit_pause(0.14)
                    self.catches += 1
                    self._set_plan("wait", 0.6)
                else:
                    self._missing = False
                    self._shrug()
            return
        self._recover()
        if plan in ("bat", "shrug", "wait") and (sp.busy() or now < self._plan_until):
            return
        if plan == "breather":
            if now < self._plan_until:
                return
            self.stamina = max(self.stamina, 0.45 + 0.2 * self._energy())
            self._plan = None
        if sp.busy():
            return
        if self.stamina < SPENT:
            self._breather()
            return
        floor, _b = self._floor()
        height = floor - f.y()
        body = sp._body().stand
        facing = self._facing_to(f.x())
        paw = self._frame_x(self.fit.bat_target[0], facing)
        dist = (f.x() - paw) * facing
        speed = math.hypot(fvx, fvy)
        if height < body * 0.55:                   # down on the floor: bat it, pounce on it
            if BAT_NEAR <= dist <= 18:
                if sp.facing != facing:
                    sp.face(f.x())
                    return
                wand_ = wand

                def tap():
                    if self._paw_near(wand_.feather(), 10 * s):
                        wand_.swat(sp.facing * random.uniform(250, 500), -random.uniform(150, 450))
                sp.on_frame("bat", 5, tap)
                sp.do_anim("bat")
                self._spend("bat")
                self._set_plan("bat", 0.8)
                return
            if self._pounce_choice is None and speed < 500:
                pounce_p = (0.55 if not self._tired() else 0.2) * (0.35 + 0.9 * self._energy())
                self._pounce_choice = random.random() < pounce_p
            if 60 <= dist <= 240 and speed < 500 and self._pounce_choice:
                self._pounce_choice = None
                sp.facing = facing
                self._stalk_then_pounce(f.x())
                return
            if speed < 40 and random.random() < 0.05 * (1.2 - self._energy()):
                self._watch(f.x(), seconds=random.uniform(0.4, 1.2))
                return
            self._approach(f.x(), facing, self.fit.bat_target[0])
            return
        self._pounce_choice = None
        under = abs(f.x() - self._cat_x()) < 45
        if height < body * 2.3:                    # within a leap: up after it
            if under or abs(dist) < 30:
                if random.random() < 0.22 + 0.25 * self._energy() - (0.15 if self._tired() else 0):
                    sp.face(f.x())
                    sp.jump_up(height * 0.9)
                    self._spend("pounce")
                else:
                    self._watch(f.x(), up=True)
                return
            self._approach(f.x(), facing, 24)
            return
        if abs(f.x() - self._cat_x()) > 140:       # high up: keep underneath it
            sp.run_to(sp.x() + (f.x() - self._cat_x()), "walk")
        else:
            self._watch(f.x(), up=True)

    def _bat_at_nothing(self) -> None:
        if self.sprite.do_anim("bat"):
            self._spend("bat")
        self._plan = None


_ = QPoint
