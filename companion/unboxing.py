"""Unboxing: something bought in the shop arrives in a parcel.

The parcel drops onto the floor in front of the cat with a thump; the cat
looks, walks over, sniffs it, paws at it (it wobbles), and on the third
paw it pops open: the new thing rises out of it with a sparkle and goes to
the corner, and the cat goes and tries it out (curls up in the new bed,
scratches the new post). A toy jumps out onto the floor instead, and
playtime starts with it.

Everything here is for show: the thing was paid for and is owned before
the parcel lands. If anything gets in the way (you pick the cat up, a
focus block starts) the parcel just opens and the thing is delivered.
"""
from __future__ import annotations

import math
import random
import time

from PyQt6.QtCore import QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from .home import pixmap
from .playground import GRAVITY, SQUASH_S, _flags, puff

TICK = 70                     # ms: the sequence's own tick (the cat's)
DROP_FROM = 3.2               # parcel starts this many of its heights above the floor
WOBBLE_S = 0.28
POP_S = 0.55                  # the thing rises out of the box
SHOW_S = 1.3                  # ... and hangs there, sparkling
FADE_S = 0.45
USE_S = {"bed": 30.0, "post": 7.0, "bowl": 6.0, "basket": 3.0}   # trying it out
PAWS = 3                      # paws at it this many times; it opens on the last
GIVE_UP_S = 30.0              # the whole thing, at most (then it just opens)


class Parcel(QWidget):
    """The parcel on the floor, at the cat's pixel scale. ``landed`` fires
    when it hits the floor; ``done`` when it has opened and faded away."""
    landed = pyqtSignal()
    done = pyqtSignal()

    def __init__(self, closed, opened, scale: int, item_pm: QPixmap | None = None) -> None:
        super().__init__(None)
        _flags(self, clickable=False)
        self.scale = s = scale
        self._closed = pixmap(closed.back, closed.w, closed.h, s)
        self._opened = pixmap(opened.back, opened.w, opened.h, s)
        self.pw, self.ph = closed.w * s, closed.h * s
        self.ow, self.oh = opened.w * s, opened.h * s
        self.item = item_pm
        iw = item_pm.width() if item_pm else 0
        ih = item_pm.height() if item_pm else 0
        self.resize(max(self.ow, iw) + 16 * s, max(self.ph, self.oh) + ih + 22 * s)
        self.floor_y = 0
        self.x_mid = 0.0
        self.y_off = 0.0                  # parcel's bottom above the floor (px, while it drops)
        self.vy = 0.0
        self.falling = False
        self.is_open = False
        self._squash_until = 0.0
        self._wobble_until = 0.0
        self._opened_at = 0.0
        self._fading_at = 0.0
        self._alpha = 1.0
        self._sparkles: list[list[float]] = []
        self._last = time.monotonic()
        self._t = QTimer(self)
        self._t.setTimerType(Qt.TimerType.PreciseTimer)
        self._t.timeout.connect(self._step)

    # ---- placing ---------------------------------------------------------
    def drop(self, x_mid: float, floor_y: int) -> None:
        self.x_mid, self.floor_y = x_mid, floor_y
        self.y_off = self.ph * DROP_FROM
        self.vy = 0.0
        self.falling = True
        self.move(int(round(x_mid - self.width() / 2)), floor_y - self.height())
        self.show()
        self.raise_()
        self._last = time.monotonic()
        self._t.start(16)

    def left(self) -> float:
        return self.x_mid - self.pw / 2

    def right(self) -> float:
        return self.x_mid + self.pw / 2

    def wobble(self) -> None:
        """Pawed at: it rocks and squashes."""
        now = time.monotonic()
        self._wobble_until = now + WOBBLE_S
        self._squash_until = now + SQUASH_S

    def open(self) -> None:
        if self.is_open:
            return
        self.is_open = True
        self._opened_at = time.monotonic()
        self._squash_until = self._opened_at + SQUASH_S
        s = self.scale
        for _ in range(9):
            self._sparkles.append([random.uniform(-0.5, 0.5), random.uniform(0.0, 1.0),
                                   random.uniform(0.0, 0.35), random.choice((1, 1, 2))])
        puff(self.x_mid, self.floor_y, s, n=6, strength=0.8)
        if self.item is None:                         # nothing to show off (a toy jumps out)
            self._fading_at = self._opened_at + 0.9

    def finish_soon(self) -> None:
        """Hurry: open now and fade."""
        self.open()
        self._fading_at = min(self._fading_at or 1e18, time.monotonic() + 0.3)

    # ---- motion ---------------------------------------------------------
    def _step(self) -> None:
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        if self.falling:
            self.vy += GRAVITY * dt
            self.y_off -= self.vy * dt
            if self.y_off <= 0:
                self.y_off = 0.0
                self.falling = False
                self._squash_until = now + SQUASH_S * 1.4
                puff(self.x_mid, self.floor_y, self.scale, n=6, strength=0.9)
                self.landed.emit()
        if self.is_open and not self._fading_at and self.item is not None and \
                now > self._opened_at + POP_S + SHOW_S:
            self._fading_at = now
        if self._fading_at and now >= self._fading_at:
            self._alpha = max(0.0, 1.0 - (now - self._fading_at) / FADE_S)
            if self._alpha <= 0.0:
                self._t.stop()
                self.hide()
                self.done.emit()
                self.deleteLater()
                return
        self.update()

    # ---- drawing ----------------------------------------------------------
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.setOpacity(self._alpha)
        now = time.monotonic()
        s = self.scale
        W, H = self.width(), self.height()
        snap = lambda v: int(round(v / s)) * s     # noqa: E731 - stay on the cat's pixel grid
        bottom = H - snap(self.y_off)
        pm = self._opened if self.is_open else self._closed
        w, h = (self.ow, self.oh) if self.is_open else (self.pw, self.ph)
        x = (W - w) // 2
        if now < self._wobble_until:
            k = (self._wobble_until - now) / WOBBLE_S
            x += s * (1 if int(now * 30) % 2 else -1) * (1 if k > 0.4 else 0)
        if now < self._squash_until:
            p.drawPixmap(x - s, bottom - h + s, w + 2 * s, h - s, pm)
        else:
            p.drawPixmap(x, bottom - h, pm)
        if self.is_open and self.item is not None:
            t = min(1.0, (now - self._opened_at) / POP_S)
            ease = 1 - (1 - t) ** 3
            iw, ih = self.item.width(), self.item.height()
            top = bottom - h + 3 * s                  # out of the box ...
            rise = snap(ease * (ih + 4 * s))          # ... up above it
            ix = (W - iw) // 2
            iy = top - rise
            if t < 1.0:
                p.save()                              # still coming out: clipped at the box top
                p.setClipRect(0, 0, W, top + 1)
                p.drawPixmap(ix, iy, self.item)
                p.restore()
            else:
                bob = s if int((now - self._opened_at) * 2.2) % 2 else 0
                p.drawPixmap(ix, iy - bob, self.item)
            self._sparkle(p, now, ix, iy, iw, ih)
        elif self.is_open:
            self._sparkle(p, now, (W - w) // 2, bottom - h - 6 * s, w, 6 * s)
        p.end()

    def _sparkle(self, p: QPainter, now: float, x: int, y: int, w: int, h: int) -> None:
        """Little four-point stars twinkling around what came out."""
        s = self.scale
        age = now - self._opened_at
        for fx, fy, delay, big in self._sparkles:
            a = age - delay
            if a < 0 or a > 1.6:
                continue
            on = math.sin(a * 9.0) > -0.2
            if not on:
                continue
            cx = x + w / 2 + fx * (w + 10 * s)
            cy = y + fy * h - a * 4 * s
            cx, cy = int(cx // s) * s, int(cy // s) * s
            col = QColor(255, 246, 200) if big == 2 else QColor(255, 255, 255)
            p.fillRect(cx, cy, s, s, col)
            if big == 2 or a < 0.8:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    p.fillRect(cx + dx * s, cy + dy * s, s, s, QColor(255, 214, 120))


class Unboxing(QObject):
    """Runs the unboxing of one thing. ``finished(item_id)`` when it's over
    (delivered either way)."""
    finished = pyqtSignal(str)

    def __init__(self, sprite, playtime, fit_fn, render_fn, place_fn, say_fn) -> None:
        """``render_fn(item)`` -> the item's Rendered for this cat;
        ``place_fn(item)`` stands a piece of furniture in the corner;
        ``say_fn(text, seconds)`` speaks."""
        super().__init__()
        self.sprite, self.playtime = sprite, playtime
        self.fit_fn, self.render_fn = fit_fn, render_fn
        self.place_fn, self.say = place_fn, say_fn
        self.item = None
        self.parcel: Parcel | None = None
        self.phase: str | None = None
        self._paws = 0
        self._until = 0.0
        self._started = 0.0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)

    def active(self) -> bool:
        return self.item is not None

    def start(self, item) -> bool:
        """Unbox ``item`` now (False: the cat can't; deliver it yourself)."""
        sp = self.sprite
        fit = self.fit_fn()
        if self.active() or fit is None or not sp.can_play():
            return False
        from .things import parcel as P
        self.item = item
        self.playtime.stop(quiet=True)
        sp._drop_thing()
        sp.in_play = True
        r = self.render_fn(item)
        item_pm = None
        if item.kind != "toy":
            from .things.scene import compose
            rgba, w, h, _at = compose(r, None)
            item_pm = pixmap(rgba, w, h, sp.pixel_scale())
        self.parcel = Parcel(P.render(fit), P.render(fit, opened=True), sp.pixel_scale(), item_pm)
        self.parcel.landed.connect(self._landed)
        self._paws = 0
        self._started = time.monotonic()
        if sp._perched or sp.y() < sp._floor_y() - 2:
            sp._leave_surface()
            sp._vy = 0.0
            sp.state = "fall"                       # down to the floor first
        self.phase = "ground"
        self._t.start(TICK)
        return True

    # ---- the sequence ----------------------------------------------------------
    def _floor(self) -> int:
        sp = self.sprite
        return sp.floor_line(sp.screen() or QApplication.primaryScreen())

    def _cat_x(self) -> float:
        from .sprite import W
        return self.sprite.x() + W / 2

    def _drop_spot(self) -> float:
        """In front of the cat (or behind it, if the screen ends there)."""
        from .screens import usable
        sp = self.sprite
        g = usable(sp.screen() or QApplication.primaryScreen())
        gap = sp._body().w * 1.3 + self.parcel.pw / 2
        for d in (sp.facing, -sp.facing):
            x = self._cat_x() + d * gap
            if g.left() + self.parcel.width() / 2 + 8 < x < g.right() - self.parcel.width() / 2 - 8:
                return x
        return self._cat_x() + sp.facing * gap

    def _sniff_x(self) -> float:
        """Window x that puts the cat's nose against the near side of the
        parcel when it puts its head down (eat)."""
        sp = self.sprite
        side = 1 if self.parcel.x_mid >= self._cat_x() else -1
        edge = self.parcel.left() if side > 0 else self.parcel.right()
        bx, _by, tw, _th = sp._sprite_box()
        cur = sp._current_frame()
        scale = cur[1] if cur else sp.pixel_scale()
        frames = len(sp.sheet.frames("eat", side)) if "eat" in sp.sheet.anims else 0
        mouth = None
        for i in range(frames):                      # the lowest the head goes
            an = sp.sheet.anchor("eat", i, side)
            m = an.get("mouth") if an else None
            if m and (mouth is None or m[1] > mouth[1]):
                mouth = m
        if mouth is None:
            return sp.x() + (edge - side * sp._body().w * 0.6) - self._cat_x()
        return edge - (bx + (mouth[0] + 0.5) * scale) - side * scale

    def _tick(self) -> None:
        sp = self.sprite
        now = time.monotonic()
        if self.phase is None:
            return
        if sp._dragging or now - self._started > GIVE_UP_S:
            self._deliver(hurry=True)               # picked up / something stuck: just open it
            return
        if self.phase == "ground":
            if sp.state in ("fall", "hop", "climb") or sp.busy():
                return
            self.parcel.drop(self._drop_spot(), self._floor())
            sp.face(self.parcel.x_mid)
            if "watchup" in sp.sheet.anims:
                sp.state = "watchup"
                sp._state_ticks = 0
            self.phase = "falling"
        elif self.phase == "walk":
            if sp.state == "walk":
                return
            sp.face(self.parcel.x_mid)
            if sp.do_anim("eat"):
                self.phase = "sniff"
            else:
                self.phase = "paw"
        elif self.phase == "sniff":
            if sp.busy():
                return
            self._until = now + 0.35
            self.phase = "paw"
        elif self.phase == "paw":
            if sp.busy() or now < self._until:
                return
            self._paws += 1
            last = self._paws >= PAWS
            sp.on_frame("bat", 5, self.parcel.open if last else self.parcel.wobble)
            if not sp.do_anim("bat"):
                self.parcel.open()
                last = True
            if last:
                self.phase = "opening"
            else:
                self._until = now + random.uniform(0.25, 0.6)
        elif self.phase == "opening":
            if not self.parcel.is_open or sp.busy():
                return
            self._opened()
        elif self.phase == "showing":
            if now >= self._until and not sp.busy():
                self._to_corner()

    def _landed(self) -> None:
        if self.phase != "falling":
            return
        self.say("a parcel! \U0001F4E6", 4)
        self.sprite.run_to(self._sniff_x(), "walk")
        self.phase = "walk"

    def _opened(self) -> None:
        sp, it = self.sprite, self.item
        if it.kind == "toy":
            self.phase = None
            self._t.stop()
            x = self.parcel.x_mid
            self.say(f"{it.name}! ✨", 4)
            if self.playtime.start_toy(it.id, at_x=x):
                toy = self.playtime.toy
                toy.y_f -= self.parcel.ph * 0.6           # out of the top of the box
                toy.vx, toy.vy = -sp.facing * 140.0, -460.0
                self.playtime._thrown()
            self._end()
            return
        self.phase = "showing"
        self._until = time.monotonic() + POP_S + SHOW_S
        sp.do_anim("celebrate") or sp.do_anim("meow")
        self.say(f"{it.name}! ✨", 4)

    def _to_corner(self) -> None:
        if self.item is None:
            return
        it = self.item
        self.place_fn(it)
        self.sprite.in_play = False
        if self.sprite.go_use(it.kind, USE_S.get(it.kind, 5.0)):
            self.say("trying it out \U0001F43E", 4)
        self._end()

    def _deliver(self, hurry: bool = False) -> None:
        """Whatever happened: open it and hand the thing over."""
        it = self.item
        if it is None:
            return
        if self.parcel is not None:
            self.parcel.finish_soon()
        if it.kind == "toy":
            self._end()
            return
        self.place_fn(it)
        self.sprite.in_play = False
        self._end()

    def _end(self) -> None:
        it, self.item = self.item, None
        self.phase = None
        self._t.stop()
        if self.playtime.mode is None:
            self.sprite.in_play = False
        if it is not None:
            self.finished.emit(it.id)


_ = QPoint
