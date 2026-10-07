"""The cat notices what's going on in the web page in front of you.

The browser extension tells PISI what happens on the page, never the words:
where your selection is, whether a video or music is playing, where you're
typing, that you reached the end, that you closed the tab the cat was on.
This module turns that into behaviour, one thing at a time, and only when
the cat is free (not napping through a focus block, guarding a site,
playing, in its bed, being dragged, digging or knocking a word off):

* you select some text: it stalks over and swats at the highlight
* a video plays: it settles beside it and watches; pauses with you,
  stretches when it ends
* music plays: it bobs its head now and then
* you type for a while: it sits on the box and watches
* you scroll slowly through a long read: it curls up on the page
* you fling the page: it hangs on; scroll forever: a yawn, a look
* you reach the end of the page: a stretch
* the page zooms: a start; the tab closes under it: a spooked leap down
* a login page: it covers its eyes
* the connection drops: a puzzled look
* the mouse lingers near it: it stalks your pointer and pounces
* it lands on a picture: a sniff; on code: it kneads it, like a warm laptop
"""
from __future__ import annotations

import random
import time

from PyQt6.QtGui import QCursor

HOLD = 10 ** 6                  # "don't wander off": the plan says when it's over


class Reactions:
    SEL_SETTLE_S = 0.5          # a selection has to sit still this long (you've let go)
    PLAN_S = 12.0               # longest it spends getting somewhere
    COOL = {"sel": 20.0, "video": 30.0, "type": 120.0, "read": 300.0, "cursor": 90.0,
            "music": 12.0, "fling": 4.0, "doom": 900.0, "zoom": 3.0}

    def __init__(self, sprite, web, clock=time.monotonic, cursor=None) -> None:
        self.sp, self.web, self.clock = sprite, web, clock
        self.cursor = cursor or QCursor.pos
        self.plan: str | None = None
        self._stage = ""
        self._until = 0.0
        self._target: tuple[float, float] | None = None
        self._cool: dict[str, float] = {}
        self._pending: tuple[str, float] | None = None      # (what, until when)
        self._last: dict = {}                               # the page as last seen
        self._sel_since = 0.0
        self._typing_since = 0.0
        self._hover_since = 0.0
        self._zoom: float | None = None
        self._end_seen: set = set()

    # ---- when it may react -----------------------------------------------------
    def free(self) -> bool:
        sp = self.sp
        return not (sp.sheet is None or sp._dragging or sp._focus or sp._guarding or sp.in_play
                    or sp._thing is not None or sp._goal is not None or sp._mood == "dig"
                    or sp._knock is not None)

    def settled(self) -> bool:
        """Free and not mid-move: sitting, standing, lying about."""
        return self.free() and not self.sp.busy() and self.sp.state != "walk"

    def _ready(self, what: str, now: float) -> bool:
        return now >= self._cool.get(what, 0.0)

    def _cooldown(self, what: str, now: float) -> None:
        self._cool[what] = now + self.COOL[what] * random.uniform(0.8, 1.4)

    # ---- every tick ------------------------------------------------------------
    def step(self) -> None:
        now = self.clock()
        on_web = self.sp.surfaces is not None
        for ev in self.web.take_events() if on_web else ():
            self._event(ev, now)
        page = self.web.going_on() if on_web else {}
        if self.plan is not None and not self.free():
            self._end(hold=False)                # dragged off, a focus block began...
        if self._pending and self._pending[1] < now:
            self._pending = None
        if self._pending and self.settled():
            self._do_pending()
        self._notice(page, now)
        if self.plan is not None:
            self._run(page, now)
        elif self.settled():
            self._idle(page, now)
        self._last = page

    def landed(self, seg) -> None:
        """Just landed on a ledge: a picture gets a sniff, code a knead."""
        if not self.free() or self.plan is not None:
            return
        if seg.kind == "img" and random.random() < 0.5:
            self.sp.do_anim("sniff")
        elif seg.kind == "code" and random.random() < 0.4:
            self.sp.do_anim("knead", seconds=2.5)

    # ---- things that happen ----------------------------------------------------
    def _event(self, ev: str, now: float) -> None:
        if ev == "closed" and self.free():
            self._end(hold=False)
            self.sp.leap_off()
        elif ev == "secret":
            self._pending = ("covereyes", now + 6.0)

    def _do_pending(self) -> None:
        what, _ = self._pending
        self._pending = None
        if what == "covereyes":
            self._end(hold=False)
            self.sp.do_anim("covereyes", seconds=2.2, hold_last=True)

    def _notice(self, page: dict, now: float) -> None:
        """Changes worth a reaction straight away (whatever the cat's doing)."""
        last = self._last
        sp = self.sp
        # the page zoomed: everything under it changed size
        z = self.web.zoom() if self.web.active else None
        if z is not None and self._zoom is not None and abs(z - self._zoom) > 0.01 \
                and sp._perched and self.settled() and self._ready("zoom", now):
            self._cooldown("zoom", now)
            self._end(hold=False)
            sp.do_anim("startle")
        self._zoom = z
        # offline: what happened?
        if page.get("offline") and not last.get("offline") and self.settled():
            sp.play_emote("question", seconds=2.0)
            sp.do_anim("lookaround")
        # the end of a long page, reached by scrolling: a good stretch
        key = self.web._active
        if page.get("end") and not last.get("end") and key not in self._end_seen \
                and self.web.scrolls(60) and self.settled() and self.plan is None:
            self._end_seen.add(key)
            sp.do_anim("stretch")
            sp.play_emote("spark", seconds=1.5)
        # a fling of the page while it's riding it: hold on!
        view = self.web.view()
        fast = view and any(abs(dy) > 0.8 * view[3] and ago < 0.4
                            for ago, dy in self.web.scrolls(0.4))
        if fast and sp._perched and self.settled() and self.plan != "read" \
                and self._ready("fling", now) and "crouch" in sp.sheet.anims:
            self._cooldown("fling", now)
            sp.state = "crouch"
            sp._state_ticks = 0
            sp._next_decision = 25
        # a selection appears or moves: note when, so it can settle first
        sel = page.get("sel")
        if sel and (not last.get("sel") or _moved(sel, last["sel"])):
            self._sel_since = now
        if page.get("typing") and not last.get("typing"):
            self._typing_since = now

    # ---- choosing something to do ----------------------------------------------
    def _idle(self, page: dict, now: float) -> None:
        sp = self.sp
        view = self.web.view()
        sel = page.get("sel")
        if sel and now - self._sel_since >= self.SEL_SETTLE_S and self._ready("sel", now):
            self._cooldown("sel", now)
            if random.random() < 0.85:
                self._begin("sel", (sel[0] + sel[2] / 2, sel[1]), now)
                return
        vid = page.get("video")
        if vid and page.get("playing") == "playing" and self._ready("video", now):
            self._cooldown("video", now)
            self._begin("video", self._beside(vid), now)
            return
        typing = page.get("typing")
        if typing and now - self._typing_since > 3.0 and self._ready("type", now):
            self._cooldown("type", now)
            self._begin("type", (typing[0] + typing[2] / 2, typing[1]), now)
            return
        if view and sp._perched and self._reading(view) and self._ready("read", now):
            self._cooldown("read", now)
            self._begin("read", (view[0] + view[2] / 2, view[1] + view[3] * 0.55), now)
            return
        if page.get("music") and not (vid and page.get("playing") == "playing") \
                and self._ready("music", now) and sp.state in ("sit", "idle"):
            self._cooldown("music", now)
            if sp.do_anim("bob", seconds=random.uniform(3.0, 5.0)):
                sp.play_emote("music", seconds=2.0)
            return
        if view and self._doomscrolling(view) and self._ready("doom", now):
            self._cooldown("doom", now)
            sp.do_anim("yawn")
            self._begin("doom", None, now)
            self._stage, self._until = "look", now + 1.6
            return
        self._maybe_stalk(now)

    def _reading(self, view) -> bool:
        """A slow, steady read: several small scrolls in the last two
        minutes, the latest recent, a page or more in all."""
        moves = self.web.scrolls(120)
        if len(moves) < 5 or min(ago for ago, _ in moves) > 30:
            return False
        return (all(abs(dy) <= 0.7 * view[3] for _, dy in moves)
                and sum(abs(dy) for _, dy in moves) >= view[3])

    def _doomscrolling(self, view) -> bool:
        """Scrolling on and on: lots of it for three minutes and counting."""
        moves = self.web.scrolls(200)
        return (len(moves) >= 30 and max(ago for ago, _ in moves) > 170
                and min(ago for ago, _ in moves) < 5
                and sum(abs(dy) for _, dy in moves) > 12 * view[3])

    def _beside(self, vid) -> tuple[float, float]:
        """A spot beside a video, on the cat's side, about halfway up."""
        x, y, w, h = vid
        cx, _ = self.sp._feet()
        body = self.sp._body().w
        side = x - body if cx < x + w / 2 else x + w + body
        return side, y + h * 0.6

    # ---- plans: get there, then do the thing ------------------------------------
    def _begin(self, plan: str, target, now: float) -> None:
        self.plan, self._target = plan, target
        self._stage = "go" if target is not None else ""
        self._until = now + self.PLAN_S
        self.sp._next_decision = HOLD

    def _end(self, hold: bool = False) -> None:
        if self.plan is None:
            return
        self.plan = None
        self._stage = ""
        if not hold:
            self.sp._next_decision = random.randint(30, 70)
            self.sp._state_ticks = 0

    def _run(self, page: dict, now: float) -> None:
        sp = self.sp
        if self._stage == "go":
            if now > self._until:
                self._end()
                return
            if sp.busy() or sp.state == "walk":
                return                            # on the way
            x, y = self._target
            if sp.toward(x, y, rise=sp._body().stand * 0.4) is None:
                self._along(x, now)               # on the best ledge: along it, then on
            sp._next_decision = HOLD
            return
        if self._stage == "along":
            if sp.state == "walk" and now < self._until:
                return
            self._arrive(page, now)
            return
        getattr(self, "_run_" + self.plan)(page, now)

    def _along(self, x: float, now: float) -> None:
        """Up on the right ledge (or as near as it gets): walk along it to x,
        stopping a pounce short of a selection."""
        from .sprite import W
        sp = self.sp
        cx, _ = sp._feet()
        if self.plan == "sel":
            x -= (1 if x > cx else -1) * sp._body().w * 1.6
        if abs(x - cx) < sp._body().w * 0.5:
            self._arrive(None, now)
            return
        self._stage, self._until = "along", now + 6.0
        sp.run_to(x - W / 2, "walk")

    def _arrive(self, page: dict | None, now: float) -> None:
        sp = self.sp
        x, _ = self._target
        sp.face(x)
        if self.plan == "sel":
            self._stage, self._until = "stalk", now + random.uniform(0.6, 1.1)
            sp.state = "stalk" if "stalk" in sp.sheet.anims else "crouch"
            sp._state_ticks = 0
        elif self.plan in ("video", "type"):
            self._stage = "watch"
            page = page if page is not None else self.web.going_on()
            vid = page.get("video") if self.plan == "video" else page.get("typing")
            if vid:
                sp.face(vid[0] + vid[2] / 2)
            self._watch()
        elif self.plan == "read":
            self._stage = "nap"
            sp.state = "sleep"
            sp._state_ticks = 0
        sp._next_decision = HOLD

    def _watch(self) -> None:
        sp = self.sp
        if sp.state != "watch" and "watch" in sp.sheet.anims and not sp.busy():
            sp.state = "watch"
            sp._state_ticks = 0

    def _run_sel(self, page: dict, now: float) -> None:
        """Stalk, pounce onto the highlight, swat it."""
        from .sprite import W
        sp = self.sp
        sel = page.get("sel")
        if self._stage == "stalk" and now >= self._until:
            if not sel:
                sp.state = "sit"                  # it's gone: never mind
                self._end()
                return
            self._stage = "pounce"
            sp.pounce_to(sel[0] + sel[2] / 2 - W / 2, lift=random.uniform(16, 26))
        elif self._stage == "pounce" and not sp.busy():
            self._stage = "swat"
            if sel:
                sp.face(sel[0] + sel[2] / 2)
            sp.do_anim("bat")
            sp.play_emote("excited", seconds=1.2)
        elif self._stage == "swat" and sp.state != "bat":
            self._end()

    def _run_video(self, page: dict, now: float) -> None:
        sp = self.sp
        state = page.get("playing") if page.get("video") else None
        if state == "playing":
            if self._stage == "paused":
                self._stage = "watch"
            self._watch()
        elif state == "paused" and self._stage == "watch":
            self._stage = "paused"                # it looks back at you
            sp.state = "sit"
            sp.do_anim("lookaround")
        elif state == "ended" or state is None:
            if state == "ended":
                sp.state = "sit"
                sp.do_anim("stretch")
            self._end()

    def _run_type(self, page: dict, now: float) -> None:
        if page.get("typing"):
            self._watch()
            return
        self.sp.state = "sit"
        self._end()

    def _run_read(self, page: dict, now: float) -> None:
        view = self.web.view()
        moves = self.web.scrolls(60)
        fast = view and any(abs(dy) > 0.8 * view[3] for _, dy in moves)
        if not moves or fast:
            if self.sp.state == "sleep":
                self.sp.state = "sit"             # you've stopped (or flung it): awake
            self._end()

    def _run_doom(self, page: dict, now: float) -> None:
        if self._stage == "look" and now >= self._until and not self.sp.busy():
            self.sp.do_anim("lookaround")
            self._end()

    # ---- your mouse pointer -----------------------------------------------------
    def _maybe_stalk(self, now: float) -> None:
        sp = self.sp
        if sp.state not in ("sit", "idle") or not self._ready("cursor", now):
            self._hover_since = 0.0
            return
        p = self.cursor()
        cx, feet = sp._feet()
        head = sp._body().stand
        dx = p.x() - cx
        near = (40 <= abs(dx) <= 170 and feet - head * 2.5 <= p.y() <= feet + 10
                and not sp.geometry().contains(p))
        if not near:
            self._hover_since = 0.0
            return
        if not self._hover_since:
            self._hover_since = now
            return
        if now - self._hover_since < 1.2:
            return
        self._hover_since = 0.0
        self._cooldown("cursor", now)
        if random.random() > 0.6:
            return
        self._begin("cursor", None, now)
        self._target = (p.x(), p.y())
        self._stage, self._until = "stalk", now + random.uniform(0.6, 1.0)
        sp.face(p.x())
        sp.state = "stalk" if "stalk" in sp.sheet.anims else "crouch"
        sp._state_ticks = 0

    def _run_cursor(self, page: dict, now: float) -> None:
        sp = self.sp
        if self._stage == "stalk" and now >= self._until:
            p = self.cursor()
            cx, _ = sp._feet()
            self._stage = "pounce"
            if abs(p.x() - cx) < 220:
                from .sprite import W
                sp.pounce_to(p.x() - W / 2, lift=random.uniform(18, 30))
            else:
                sp.state = "sit"                  # it got away
        elif self._stage == "pounce" and not sp.busy():
            sp.play_emote("excited", seconds=1.0)
            self._end()


def _moved(a, b, tol: float = 4.0) -> bool:
    return any(abs(p - q) > tol for p, q in zip(a, b))
