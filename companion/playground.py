"""Toys on the floor: pixel-art toys from the catalog at the cat's own scale,
with a little physics so they can be thrown, batted and chased.

A :class:`FloorToy` lives on the cat's floor line (the bottom of a screen,
above the taskbar). Grab it and flick it: it flies, bounces and rolls to a
stop (yarn rolls further than a felt mouse). The cat bats it with
:meth:`FloorToy.hit`, pins it when it pounces on it, and carries it in its
mouth (then the cat draws it, and the toy window hides).

The laser dot is pixel art too: a small red dot that follows the cursor.
"""
from __future__ import annotations

import math
import random
import time

from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

from .home import pixmap

TICK = 16                 # ms: toys move at ~60 fps
GRAVITY = 1650.0          # px/s²
BOUNCE = 0.42             # vertical speed kept on hitting the floor
BOUNCES = {"spring": 0.68, "crinkle": 0.3}     # toys that bounce more (or less) than that
BOUNCE_MIN = 100.0        # px/s: slower than this onto the floor, it just lands
FRICTION = {"yarn": 0.215, "ball": 0.31, "crinkle": 0.25, "spring": 0.12,   # horizontal speed
            "mouse": 0.02, "fish": 0.03, "bee": 0.04}                    # kept per second on the floor
ROLLS = ("yarn", "ball", "crinkle")           # round: they turn over as they roll
STOP = 5.0                # px/s: slower than this, it has stopped
MAX_THROW = 1400.0        # px/s
SQUASH_S = 0.12           # a squash lasts this long


def _flags(w: QWidget, clickable: bool) -> None:
    flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
             | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
    if QApplication.platformName() == "xcb":
        flags |= Qt.WindowType.X11BypassWindowManagerHint
    if not clickable:
        flags |= Qt.WindowType.WindowTransparentForInput
    w.setWindowFlags(flags)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    w.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    if not clickable:
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class FloorToy(QWidget):
    """A toy on the floor. ``thrown`` fires when you let go of it (or poke
    it); the play controller then sends the cat after it. Speeds are in
    px/s; it moves at ~60 fps."""
    thrown = pyqtSignal()
    grabbed = pyqtSignal()
    landed = pyqtSignal(float, float)     # x, speed: a hard landing (for a dust puff)

    def __init__(self, toy, scale: int) -> None:
        super().__init__(None)
        _flags(self, clickable=True)
        self.toy = toy                       # things.draw.Rendered (kind "toy")
        self.style = toy.design.get("style", "mouse")
        self.scale = scale
        self._pm = {1: pixmap(toy.back, toy.w, toy.h, scale),
                    -1: pixmap(toy.back, toy.w, toy.h, scale, mirror=True)}
        self.tw, self.th = toy.w * scale, toy.h * scale
        # room above for a squashed toy to stretch into
        self.resize(self.tw + 2 * scale, self.th + 2 * scale)
        self.facing = 1
        self.x_f = 0.0                       # the toy's own top-left (not the window's)
        self.y_f = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.floor_y = 0                     # global y of the floor line (bottom edge)
        self.ledges_fn = None                # () -> [(x0, x1, y, key)]: page lines it can land on
        self.ledge = None                    # the one it's on (None: the floor)
        self.bounds = (0, 0)                 # left, right x the toy stays within
        self.held = False                    # in your hand
        self.carried = False                 # in the cat's mouth
        self.windup = False                  # a wind-up mouse: scurries on its own
        self._roll = 0.0
        self._trail: list[tuple[float, QPoint]] = []
        self._burst_until = 0.0
        self._squash_until = 0.0
        self._frozen_until = 0.0
        self._last = time.monotonic()
        self._t = QTimer(self)
        self._t.setTimerType(Qt.TimerType.PreciseTimer)
        self._t.timeout.connect(self._step)

    # ---- placing --------------------------------------------------------
    def place(self, x_center: float, floor_y: int, bounds: tuple[int, int],
              ledge: tuple | None = None) -> None:
        """Put it down with its middle at x: on the floor line ``floor_y``,
        or on ``ledge`` (x0, x1, y, key), a line of text on a page."""
        self.floor_y = floor_y
        self.bounds = bounds
        self.ledge = ledge
        self.x_f = x_center - self.tw / 2
        self.y_f = self.ground_y() - self.th
        self.vx = self.vy = 0.0
        self.carried = False
        self._sync()
        self.show()
        self.raise_()
        self._last = time.monotonic()
        self._t.start(TICK)

    def stop(self) -> None:
        self._t.stop()
        self.hide()

    def _sync(self) -> None:
        self.move(int(round(self.x_f)) - self.scale, int(round(self.y_f)) - 2 * self.scale)
        self.update()

    def center_x(self) -> float:
        return self.x_f + self.tw / 2

    def ground_y(self) -> float:
        """Global y of what it rests on: its ledge, or the floor."""
        return self.ledge[2] if self.ledge is not None else self.floor_y

    def on_floor(self) -> bool:
        """Resting on something (the floor, or a line of text)."""
        return self.y_f >= self.ground_y() - self.th - 0.5

    def _follow_ledge(self, prev_bottom: float) -> None:
        """Up on the page: ride its line as the page scrolls, roll off the
        end of it, or land on a line it falls onto."""
        lines = self.ledges_fn() if self.ledges_fn else []
        cx = self.center_x()
        if self.ledge is not None:
            x0, x1, y, key = self.ledge
            same = [ln for ln in lines if ln[3] == key]
            if not same:
                self.ledge = None                      # scrolled away / gone: it falls
                return
            ln = min(same, key=lambda ln: abs(ln[2] - y))
            if ln[2] != y and self.on_floor():
                self.y_f += ln[2] - y                  # the page scrolled: so does the toy
            self.ledge = ln
            if not (ln[0] - 1 <= cx <= ln[1] + 1):
                self.ledge = None                      # off the end of the line
            return
        if self.vy <= 0:
            return
        bottom = self.y_f + self.th
        hit = [ln for ln in lines if ln[0] <= cx <= ln[1] and prev_bottom <= ln[2] + 0.5 <= bottom + 0.5
               and ln[2] < self.floor_y]
        if hit:
            self.ledge = min(hit, key=lambda ln: ln[2])    # the first line it falls onto

    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    def resting(self) -> bool:
        return self.on_floor() and abs(self.vx) < 10 and not self.held and not self.carried

    # ---- the cat ------------------------------------------------------------
    def hit(self, vx: float, vy: float = 0.0) -> None:
        """Batted (px/s): off it goes, squashed for a moment."""
        if self.held or self.carried:
            return
        self.vx, self.vy = vx, vy
        if vx:
            self.facing = 1 if vx > 0 else -1
        self.squash()

    def squash(self) -> None:
        self._squash_until = time.monotonic() + SQUASH_S
        self.update()

    def freeze(self, seconds: float) -> None:
        """Hold still for a moment (the hit pause on a catch)."""
        self._frozen_until = time.monotonic() + seconds

    def pin(self) -> None:
        """Pounced on: it stops dead under the paws."""
        self.vx = 0.0
        if self.on_floor():
            self.vy = 0.0
        self.squash()

    def pick_up(self) -> None:
        """In the cat's mouth now (the cat draws it)."""
        self.carried = True
        self.vx = self.vy = 0.0
        self.hide()

    def scurry(self, away_from_x: float | None = None) -> None:
        """A wind-up mouse dashes off (away from the cat if it's close)."""
        sp = random.uniform(140.0, 270.0)
        if away_from_x is not None:
            d = 1 if self.center_x() >= away_from_x else -1
        else:
            d = random.choice((-1, 1))
        self.vx = d * sp
        self.facing = d
        self._burst_until = time.monotonic() + random.uniform(0.3, 0.8)

    # ---- you ----------------------------------------------------------------
    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self.carried:
            return
        self.held = True
        self.vx = self.vy = 0.0
        gp = e.globalPosition().toPoint()
        self._trail = [(time.monotonic(), gp)]
        self._grab_off = QPoint(int(gp.x() - self.x_f), int(gp.y() - self.y_f))
        self._moved = False
        self.grabbed.emit()

    def mouseMoveEvent(self, e) -> None:
        if not self.held:
            return
        gp = e.globalPosition().toPoint()
        self._moved = self._moved or (gp - self._trail[0][1]).manhattanLength() > 4
        now = time.monotonic()
        self._trail = [(t, q) for t, q in self._trail if now - t < 0.12] + [(now, gp)]
        self.x_f = float(gp.x() - self._grab_off.x())
        self.y_f = float(min(gp.y() - self._grab_off.y(), self.floor_y - self.th))
        self._sync()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self.held:
            return
        self.held = False
        (t0, p0), (t1, p1) = self._trail[0], self._trail[-1]
        if self._moved and t1 - t0 > 0.005:
            vx, vy = (p1.x() - p0.x()) / (t1 - t0), (p1.y() - p0.y()) / (t1 - t0)
            k = min(1.0, MAX_THROW / max(1e-6, math.hypot(vx, vy)))
            self.vx, self.vy = vx * k * 0.9, vy * k * 0.9
        else:                                        # a poke: it hops
            self.vx = random.choice((-1, 1)) * random.uniform(100, 200)
            self.vy = -300.0
            self.squash()
        if self.vx:
            self.facing = 1 if self.vx > 0 else -1
        self._last = time.monotonic()
        self.thrown.emit()

    # ---- physics ------------------------------------------------------------
    def _step(self) -> None:
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        if self.held or self.carried or now < self._frozen_until:
            return
        prev_bottom = self.y_f + self.th
        if not self.on_floor() or self.vy < 0:
            self.vy += GRAVITY * dt
        self.x_f += self.vx * dt
        self.y_f += self.vy * dt
        if self.ledges_fn is not None:
            self._follow_ledge(prev_bottom)
        floor_top = self.ground_y() - self.th
        lo, hi = self.bounds
        if self.x_f < lo:
            self.x_f, self.vx = float(lo), -self.vx * 0.6
        elif self.x_f > hi - self.tw:
            self.x_f, self.vx = float(hi - self.tw), -self.vx * 0.6
        if self.y_f >= floor_top:
            self.y_f = float(floor_top)
            if self.vy > BOUNCE_MIN:
                if self.vy > 380:
                    self.landed.emit(self.center_x(), self.vy)
                    self.squash()
                self.vy = -self.vy * BOUNCES.get(self.style, BOUNCE)
            else:
                self.vy = 0.0
            self.vx *= FRICTION.get(self.style, 0.1) ** dt
            if abs(self.vx) < STOP:
                self.vx = 0.0
        if self.windup and self.on_floor():
            if self._burst_until and now >= self._burst_until:
                self._burst_until = 0.0
                self.vx *= 0.3
            elif not self._burst_until and random.random() < 1.8 * dt:
                self.scurry()
        if abs(self.vx) > 10:
            self.facing = 1 if self.vx > 0 else -1
            self._roll += abs(self.vx) * dt
        self._sync()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        face = self.facing
        if self.style in ROLLS and int(self._roll / (6 * self.scale)) % 2:
            face = -face                             # a round toy rolling: it turns over
        pm = self._pm[1 if face > 0 else -1]
        if pm is not None:
            s = self.scale
            x, y, w, h = s, 2 * s, self.tw, self.th
            if time.monotonic() < self._squash_until:
                w, h = self.tw + 2 * s, self.th - s       # squashed flat: one art px lower, two wider
                x, y = 0, 3 * s
            p.drawPixmap(x, y, w, h, pm)
        p.end()


class PixelLaser(QWidget):
    """The laser pointer's dot, in pixel art at the cat's scale: a bright core
    with a soft red ring, pinned to the cursor."""

    def __init__(self, scale: int) -> None:
        super().__init__(None)
        _flags(self, clickable=False)
        self.scale = scale
        self.resize(5 * scale, 5 * scale)
        self._t = QTimer(self)
        self._t.timeout.connect(self._follow)
        self._blink = 0

    def start(self) -> None:
        self._follow()
        self.show()
        self.raise_()
        self._t.start(16)

    def stop(self) -> None:
        self._t.stop()
        self.hide()

    def center(self) -> QPoint:
        return QCursor.pos()

    def _follow(self) -> None:
        p = QCursor.pos()
        self.move(p.x() - self.width() // 2, p.y() - self.height() // 2)
        self._blink = (self._blink + 1) % 40
        self.update()

    def paintEvent(self, _e) -> None:
        s = self.scale
        p = QPainter(self)
        ring = QColor(230, 40, 40, 110 if self._blink < 20 else 80)
        for x, y in ((1, 0), (2, 0), (3, 0), (0, 1), (4, 1), (0, 2), (4, 2), (0, 3), (4, 3),
                     (1, 4), (2, 4), (3, 4)):
            p.fillRect(x * s, y * s, s, s, ring)
        for x in (1, 2, 3):
            for y in (1, 2, 3):
                p.fillRect(x * s, y * s, s, s, QColor(240, 50, 50))
        p.fillRect(2 * s, 2 * s, s, s, QColor(255, 220, 220))
        p.end()


class Dust(QWidget):
    """A little puff of pixel dust where something lands: a few specks at the
    cat's pixel size kick up and out, slow down and fade (about 0.4 s)."""
    LIFE = 0.42

    def __init__(self, x: float, floor_y: int, scale: int, n: int = 6, strength: float = 1.0) -> None:
        super().__init__(None)
        _flags(self, clickable=False)
        self.scale = scale
        w, h = int(22 * scale * strength) + 4 * scale, int(10 * scale * strength) + 3 * scale
        self.resize(w, h)
        self.move(int(x - w / 2), int(floor_y - h))
        self._specks = []
        for k in range(n):
            side = -1 if k % 2 else 1
            self._specks.append([w / 2 + random.uniform(-2, 2) * scale, h - scale,
                                 side * random.uniform(20, 70) * scale * strength,
                                 -random.uniform(15, 45) * scale * strength,
                                 1 if random.random() < 0.6 else 2])
        self._born = time.monotonic()
        self._last = self._born
        self._t = QTimer(self)
        self._t.setTimerType(Qt.TimerType.PreciseTimer)
        self._t.timeout.connect(self._step)
        self._t.start(16)
        self.show()

    def _step(self) -> None:
        now = time.monotonic()
        # clamped: after a sleep/resume (or a clock that jumped) a raw step
        # would fling the specks (and 0.02 ** dt overflows for a big negative one)
        dt, self._last = min(0.05, max(0.0, now - self._last)), now
        if not 0.0 <= now - self._born < self.LIFE:
            self._t.stop()
            self.hide()
            self.deleteLater()
            _PUFFS.discard(self)
            return
        for sp in self._specks:
            sp[0] += sp[2] * dt
            sp[1] += sp[3] * dt
            sp[2] *= 0.02 ** dt                     # air drag
            sp[3] += 60 * self.scale * dt           # settles back down
        self.update()

    def paintEvent(self, _e) -> None:
        age = (time.monotonic() - self._born) / self.LIFE
        a = int(200 * max(0.0, 1.0 - age))
        p = QPainter(self)
        for x, y, _vx, _vy, size in self._specks:
            px = self.scale * size
            col = QColor(214, 206, 190, a) if size == 1 else QColor(190, 182, 166, a)
            p.fillRect(int(x // self.scale * self.scale), int(y // self.scale * self.scale), px, px, col)
        p.end()


class FeatherWand(QWidget):
    """A cat wand: a short stick held at the cursor, a string with real rope
    physics (verlet: it swings, trails and settles) and a feather at the
    end, all drawn on the cat's pixel grid.

    The cat plays with the feather; ``swat(vx, vy)`` knocks it about,
    ``pin(pt)`` holds it under a paw for a moment."""
    SEGMENTS = 9
    GRAVITY = 1800.0           # px/s²
    DAMP = 0.992               # per step

    def __init__(self, scale: int, color=(232, 120, 150)) -> None:
        super().__init__(None)
        _flags(self, clickable=False)
        self.scale = scale
        self.seg = 4.2 * scale                     # string length = SEGMENTS * seg
        self.rod = (9 * scale, -6 * scale)         # the stick, from the hand to its tip
        span = int(self.SEGMENTS * self.seg + 14 * scale)
        self.resize(2 * span, span + 12 * scale)
        self._origin = QPoint(span, 8 * scale)     # where the hand is in the window
        self.color = QColor(*color)
        self.pts: list[list[float]] = []
        self.prev: list[list[float]] = []
        self._pinned_until = 0.0
        self._pin_at = None
        self._last = time.monotonic()
        self._t = QTimer(self)
        self._t.setTimerType(Qt.TimerType.PreciseTimer)
        self._t.timeout.connect(self._step)

    def start(self) -> None:
        tip = self.tip()
        self.pts = [[tip.x(), tip.y() + i * self.seg] for i in range(self.SEGMENTS + 1)]
        self.prev = [list(p) for p in self.pts]
        self._last = time.monotonic()
        self._place()
        self.show()
        self.raise_()
        self._t.start(16)

    def stop(self) -> None:
        self._t.stop()
        self.hide()

    def tip(self) -> QPoint:
        c = QCursor.pos()
        return QPoint(c.x() + self.rod[0], c.y() + self.rod[1])

    def feather(self) -> QPoint:
        x, y = self.pts[-1] if self.pts else (QCursor.pos().x(), QCursor.pos().y())
        return QPoint(int(x), int(y))

    def velocity(self) -> tuple[float, float]:
        if not self.pts:
            return 0.0, 0.0
        (x, y), (px, py) = self.pts[-1], self.prev[-1]
        return (x - px) * 60.0, (y - py) * 60.0

    def swat(self, vx: float, vy: float) -> None:
        """A paw hits the feather (px/s)."""
        if self.pts:
            x, y = self.pts[-1]
            self.prev[-1] = [x - vx / 60.0, y - vy / 60.0]

    def pin(self, pt: QPoint, seconds: float = 0.6) -> None:
        """Held under a paw for a moment (the string goes taut)."""
        self._pin_at = (float(pt.x()), float(pt.y()))
        self._pinned_until = time.monotonic() + seconds

    def _step(self) -> None:
        now = time.monotonic()
        dt = min(0.033, max(0.001, now - self._last))
        self._last = now
        tip = self.tip()
        g = self.GRAVITY * dt * dt
        for i in range(1, len(self.pts)):
            x, y = self.pts[i]
            px, py = self.prev[i]
            nx = x + (x - px) * self.DAMP
            ny = y + (y - py) * self.DAMP + g
            self.prev[i] = [x, y]
            self.pts[i] = [nx, ny]
        self.pts[0] = [float(tip.x()), float(tip.y())]
        pinned = self._pin_at is not None and now < self._pinned_until
        for _ in range(8):                          # keep the string's length
            for i in range(len(self.pts) - 1):
                (ax, ay), (bx, by) = self.pts[i], self.pts[i + 1]
                dx, dy = bx - ax, by - ay
                d = math.hypot(dx, dy) or 1e-6
                diff = (d - self.seg) / d
                if i == 0:
                    self.pts[i + 1] = [bx - dx * diff, by - dy * diff]
                else:
                    self.pts[i] = [ax + dx * diff * 0.5, ay + dy * diff * 0.5]
                    self.pts[i + 1] = [bx - dx * diff * 0.5, by - dy * diff * 0.5]
            if pinned:
                self.pts[-1] = list(self._pin_at)
            self.pts[0] = [float(tip.x()), float(tip.y())]
        floor = getattr(self, "floor_y", None)
        if floor is not None:                       # it drags along the floor, not through it
            for i in range(1, len(self.pts)):
                if self.pts[i][1] > floor - self.scale:
                    self.pts[i][1] = floor - self.scale
        self._place()
        self.update()

    def _place(self) -> None:
        c = QCursor.pos()
        self.move(c.x() - self._origin.x(), c.y() - self._origin.y())

    def paintEvent(self, _e) -> None:
        s = self.scale
        p = QPainter(self)
        off = self.pos()

        def cell(x, y):                             # snap to the cat's pixel grid
            return int((x - off.x()) // s) * s, int((y - off.y()) // s) * s

        def line(a, b, col):
            (x0, y0), (x1, y1) = cell(*a), cell(*b)
            n = max(abs(x1 - x0), abs(y1 - y0)) // s + 1
            for k in range(n + 1):
                t = k / max(1, n)
                p.fillRect(int(round((x0 + (x1 - x0) * t) / s)) * s,
                           int(round((y0 + (y1 - y0) * t) / s)) * s, s, s, col)
        hand = QCursor.pos()
        tip = self.tip()
        line((hand.x(), hand.y()), (tip.x(), tip.y()), QColor(150, 104, 62))          # the stick
        for a, b in zip(self.pts, self.pts[1:]):
            line(a, b, QColor(70, 66, 72))                                             # the string
        if len(self.pts) >= 2:
            (ax, ay), (bx, by) = self.pts[-2], self.pts[-1]
            dx, dy = bx - ax, by - ay
            d = math.hypot(dx, dy) or 1.0
            ux, uy = dx / d, dy / d                                                    # down the string
            light, dark = self.color, self.color.darker(135)
            for k in range(6):                                                         # the feather
                cx, cy = bx + ux * k * s, by + uy * k * s
                p.fillRect(*cell(cx, cy), s, s, dark if k == 0 else light)
                if 1 <= k <= 4:
                    w = 1 if k in (1, 4) else 2
                    for side in (-1, 1):
                        for j in range(1, w + 1):
                            ex, ey = cx - uy * side * j * s, cy + ux * side * j * s
                            p.fillRect(*cell(ex, ey), s, s, light if j < w or k == 2 else dark)
        p.end()


class Splash(QWidget):
    """Bits flicked up from the cat's mouth at its bowl: kibble crumbs when
    it eats, droplets when it drinks. They fly up and out, fall back past
    the rim and fade (about half a second), at the cat's pixel size."""
    LIFE = 0.55
    KINDS = {
        # colours (art pixels), how many, how high they go, how wide they spread
        "food": ([(168, 108, 62), (140, 86, 48), (196, 140, 88)], (3, 5), (22, 38), 30),
        "water": ([(150, 200, 236), (120, 172, 216), (236, 246, 252)], (5, 7), (30, 50), 40),
    }

    def __init__(self, x: int, y: int, scale: int, kind: str) -> None:
        super().__init__(None)
        _flags(self, clickable=False)
        cols, (lo, hi), (up_lo, up_hi), spread = self.KINDS[kind]
        self.scale = scale
        w, h = 34 * scale, 30 * scale
        self.resize(w, h)
        self.move(int(x - w / 2), int(y - h * 0.55))
        ox, oy = w / 2, h * 0.55
        self._bits = []
        for _ in range(random.randint(lo, hi)):
            self._bits.append([ox + random.uniform(-1.5, 1.5) * scale, oy,
                               random.uniform(-spread, spread) * scale,
                               -random.uniform(up_lo, up_hi) * scale,
                               random.choice(cols)])
        self._born = self._last = time.monotonic()
        self._t = QTimer(self)
        self._t.setTimerType(Qt.TimerType.PreciseTimer)
        self._t.timeout.connect(self._step)
        self._t.start(16)
        self.show()
        self.raise_()

    def _step(self) -> None:
        now = time.monotonic()
        dt, self._last = min(0.05, max(0.0, now - self._last)), now   # (see Dust._step)
        if not 0.0 <= now - self._born < self.LIFE:
            self._t.stop()
            self.hide()
            self.deleteLater()
            _PUFFS.discard(self)
            return
        for b in self._bits:
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            b[3] += 420 * self.scale * dt              # up, over, and back down past the rim
        self.update()

    def paintEvent(self, _e) -> None:
        age = (time.monotonic() - self._born) / self.LIFE
        a = int(255 * min(1.0, 3.0 * (1.0 - age)))      # solid, then fades at the end
        p = QPainter(self)
        s = self.scale
        for x, y, _vx, _vy, (r, g, b) in self._bits:
            p.fillRect(int(x // s * s), int(y // s * s), s, s, QColor(r, g, b, max(0, a)))
        p.end()


def splash(x: int, y: int, scale: int, kind: str) -> None:
    """Crumbs ("food") or droplets ("water") from the mouth at (x, y)."""
    if kind in Splash.KINDS:
        _PUFFS.add(Splash(x, y, scale, kind))


_PUFFS: set = set()


def puff(x: float, floor_y: int, scale: int, n: int = 6, strength: float = 1.0) -> None:
    """Kick up dust at (x, the floor)."""
    _PUFFS.add(Dust(x, floor_y, scale, n, strength))


_ = QPointF
