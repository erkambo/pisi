"""The wandering cat. A frameless, transparent, always-on-top window that draws
a vector cat with QPainter and roams the screen. No image assets required.

States: SIT (idle, tail-swish, blink), WALK (moves to a target, legs animate),
SLEEP (curled, Zzz) after long idle. Left-drag to move it, click to pet,
double-click to chat, right-click for the menu.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import replace

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath,
                         QPen, QPolygonF)
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication, QWidget

from . import perch
from .bubble import Bubble

W, H = 170, 185
BASELINE = 165           # y of the cat's feet
TICK_MS = 70
GLIDE_MS = 16            # the window glides between logic ticks at ~60 fps
GLIDE_MAX = 220          # px: a bigger jump than this is a teleport, not a glide
DRAG_THRESHOLD = 6

# animations that play once then settle back to sitting
ONESHOT = {"yawn", "meow", "pounce", "jump", "attack", "eat", "hurt",
           "tailswish", "lookaround", "death", "talk", "petted", "stretch",
           "celebrate", "bat", "pickup", "drop",
           "dig", "covereyes", "startle", "bob", "sniff"}
WALK_STEP = {"walk": 1.6, "run": 3.8}     # screen px per tick at speed 1.0
KNOCK_CHANCE = 0.08      # on a line of text, at a decision: knock its last word off
DIG_CHANCE = 0.03        # ... or dig down through the paragraph
GRAVITY = 2.4            # px per tick² while falling off a line
MAX_FALL = 30.0          # terminal velocity, px per tick
DRIFT_GRAVITY = 0.6      # ... and when floating down onto the next line of text
DRIFT_MAX = 6.0          # (about 85 px a second)
# PISI's corner: now and then it goes and uses a thing on its own
VISIT_CHANCE = 0.06
VISITS = {"post": (3.0, 6.0), "bowl": (3.0, 5.0), "bed": (40.0, 90.0)}   # seconds
ENTER = {"curlrim": "rimdown", "curl": "curldown"}     # getting into a thing
EXIT = {"curlrim": "rimup", "curl": "curlup"}          # and out again


def _lighten(c: QColor, f: float) -> QColor:
    return QColor(min(255, int(c.red() + (255 - c.red()) * f)),
                  min(255, int(c.green() + (255 - c.green()) * f)),
                  min(255, int(c.blue() + (255 - c.blue()) * f)))


def _darken(c: QColor, f: float) -> QColor:
    return QColor(int(c.red() * (1 - f)), int(c.green() * (1 - f)),
                  int(c.blue() * (1 - f)))


class CatSprite(QWidget):
    petted = pyqtSignal()
    request_chat = pyqtSignal()
    request_menu = pyqtSignal(QPoint)
    landed = pyqtSignal(int, int)      # global feet point after landing on page text
    bite = pyqtSignal(str, int, int)   # at its bowl: "food" / "water", mouth on screen
    shooed = pyqtSignal()              # dragged off a page it was guarding
    dug = pyqtSignal(int, int, int, int)   # digging at feet (x, y) on screen, width, facing
    knocked = pyqtSignal(int, int, int)    # batted the word at a line's end (x, y on screen), which way

    def __init__(self, color_hex: str = "#e8943a", speed: float = 1.0) -> None:
        super().__init__(None)
        # Where the cat *is* (its logic runs on TICK_MS ticks) vs where its
        # window is drawn: the window glides there at ~60 fps, so a fast
        # chase is smooth instead of stepping 14 times a second. x(), y()
        # and pos() report where the cat is.
        self._lpos = QPoint(0, 0)
        self._from = QPoint(0, 0)
        self._from_t = 0.0
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        if QApplication.platformName() == "xcb":
            # X11 window managers keep windows from going above the top of the
            # screen, and the cat's head has room above it in its window: on a
            # search box near the top its feet couldn't get high enough, the
            # window was pushed down and it fell. Unmanaged, it can.
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # macOS hides "tool" windows whenever another app is active — keep it up
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(W, H)
        self.setMouseTracking(True)

        self.base = QColor(color_hex)
        self.speed = speed
        self.chase_boost = 1.0          # >1 while chasing a toy (laser/mouse)
        self.bubble = Bubble()

        # optional real pixel-art sprite sheet (falls back to vector drawing)
        self.sheet = None
        self.sheet_scale = 0          # 0 = auto integer scale
        self._opaque_cache: dict[int, QRect] = {}   # frame -> visible pixel box
        self._anim = "idle"
        self._afi = 0                 # current animation frame index
        self._aacc = 0.0              # frame accumulator
        self._hold_until = 0          # keep looping a one-shot until this frame
        self._hold_freeze = False     # freeze on the last frame vs loop
        self._trans: str | None = None   # transition anim playing (procedural pets)
        self._trans_fi = 0
        self._trans_acc = 0.0

        # original overlay emotes (hearts, sparkles, …) drawn over any sprite
        self._emote: str | None = None
        self._emote_start = 0
        self._emote_frames = 1

        # focus (pomodoro) mode: while True the cat holds a calm nap pose next
        # to you instead of wandering — see begin_focus / focus_pose / end_focus.
        self._focus = False
        self._focus_depth = 0.0
        # guarding a distracting page during a focus block (see guard): the
        # nap is on hold while it sits on the page; _guard_back = nap again
        self._guarding = False
        self._guard_back = False
        self._guard_said = False
        # burrowing down through a paragraph (see dig)
        self._dig_left = 0
        self._dig_y = 0.0
        self._knock: dict | None = None    # walking to a line's end to knock its last word off
        # reacting to what happens on web pages (companion/reactions.py)
        self.reactions = None

        # animation / behaviour state
        self.state = "sit"
        self.gait = "walk"              # "walk" (calm) or "run" (fast dash)
        self.facing = 1                 # 1 = right, -1 = left
        self.frame = 0
        self.blink = 0.0
        self._state_ticks = 0           # ticks spent in current state
        self._next_decision = 40
        self.target = QPoint(self.x(), self.y())
        # standing on things: lines of web text via the browser bridge
        self.surfaces = None          # a perch.WebSurfaces, or None when off
        self._perched = False         # feet on a surface right now
        self._hop: dict | None = None # leap in progress: from, to, progress
        self._vy = 0.0                # fall speed
        self._web_after = None        # the page move being carried out (perch.Move)
        self._foot: int | None = None # cached local y of the feet
        self._climb: dict | None = None  # climbing the side of the text: path, progress
        self._geo_cache = None        # (sheet id, how its climbing frames line up)
        self._recent: list = []       # (y, x0, x1) of the last few ledges it stood on
        self._angle = 0.0             # degrees the pet is turned (on a wall)
        self._mood = ""               # "climb" while working its way up a page
        self._creep = False           # crouched, under something low
        self._squeeze = False         # flat on its belly, through somewhere tighter
        self._page_scale = 0.0        # smaller drawing scale on a page (0 = usual)
        self.web_fit = False          # shrink to suit the page's text (off: full size, calm)
        self._unit_cache = None       # (sheet id, Body at scale 1)
        self._page_key = None         # cache of the page's ledges for our size
        self._page_val = None
        self._fx = float(self.x())    # float position so diagonal / slow moves
        self._fy = float(self.y())    # don't get truncated to 0 each tick
        self.wander_enabled = True

        # PISI's corner (companion/home.py): ``home(kind)`` gives the spot of a
        # thing there (set by the app); the cat walks over and uses it
        self.home = None
        self._thing: dict | None = None   # the thing in use (drawn around the cat)
        self._goal: dict | None = None    # on its way to a thing
        self._after_leave: list[str] = []  # anims to play once out of the thing
        self._exact = False               # placing at a thing: no screen clamp
        # playing: a toy in the mouth (drawn at the rig's mouth anchor), and
        # callbacks for exact animation frames (the paw's tap, the bite)
        self._carry: dict | None = None
        self._frame_events: list[tuple[str, int, object]] = []
        self._freeze = 0                  # ticks of hit pause left (everything holds)

        # dragging
        self._pressed = False
        self._dragging = False
        self._press_global = QPoint()
        self._press_winpos = QPoint()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)
        self._glide_timer = QTimer(self)
        self._glide_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._glide_timer.timeout.connect(self._glide)     # runs only while gliding
        self._last_sig = None              # what was last drawn (skip redundant repaints)
        self.tired = False                 # worn out from play: trudges, tail low
        self.in_play = False               # a game is steering it: no wandering off
        self._meter: float | None = None   # energy pips shown above the cat (0..1)
        self._meter_alpha = 0.0
        self._meter_on = False

    # ---- placement ---------------------------------------------------
    def _screen_rect(self) -> QRect:
        from .screens import usable
        scr = self.screen() or QApplication.primaryScreen()
        return usable(scr)

    def place_start(self) -> None:
        r = self._screen_rect()
        x = r.center().x() - W // 2
        y = r.bottom() - H
        self.move(x, y)
        self.target = QPoint(x, y)
        self._sync_fpos()

    def _pick_target(self) -> None:
        r = self._screen_rect()
        # mostly a calm walk; occasionally a quick dash
        self.gait = "run" if random.random() < 0.25 else "walk"
        if self.gait == "walk":
            # walks go a shorter distance so it strolls rather than sprints
            span = int(r.width() * 0.30)
            x = min(max(r.left(), self.x() + random.randint(-span, span)),
                    r.right() - W)
        else:
            x = random.randint(r.left(), r.right() - W)
        # along the floor (the bottom of the screen): walking up through the
        # middle of your windows looked like walking on air
        self.target = QPoint(x, self._floor_y())
        self._sync_fpos()

    def set_color(self, color_hex: str) -> None:
        self.base = QColor(color_hex)
        self.update()

    def load_sheet(self, config: dict) -> bool:
        """Load a pixel-art sprite sheet from config. Returns True if one was
        loaded (otherwise the cat stays vector-drawn)."""
        from . import pixelsheet
        return self.set_sheet(pixelsheet.load(config), config)

    def set_sheet(self, sheet, config: dict | None = None) -> bool:
        """Swap the drawn sprite sheet (e.g. a freshly baked procedural pet)."""
        self.sheet = sheet
        if config is not None:
            try:
                self.sheet_scale = int(config.get("sprite_scale", 0))
            except (TypeError, ValueError):
                self.sheet_scale = 0
        self._afi = 0
        self._aacc = 0.0
        self._trans = None
        self._anim = None
        self._opaque_cache.clear()
        self._foot = None
        self._unit_cache = None
        self._geo_cache = None
        self._page_key = None
        self.update()
        return self.sheet is not None

    def set_wander(self, on: bool) -> None:
        self.wander_enabled = on
        if not on and self.state == "walk":
            self.state = "sit"
            self._state_ticks = 0

    def come_to(self, global_pt: QPoint) -> None:
        self._drop_thing()
        self._leave_surface()
        r = self._screen_rect()
        x = max(r.left(), min(global_pt.x() - W // 2, r.right() - W))
        y = max(r.top(), min(global_pt.y() - H // 2, r.bottom() - H))
        self.target = QPoint(x, y)
        self.gait = "run"
        self._sync_fpos()
        self.state = "walk"
        self._state_ticks = 0

    def move(self, *args) -> None:
        """Move the window, but never leave the pet straddling two monitors:
        its body stays whole on one screen (the one under its middle, or the
        nearest one if that's in a gap between screens). Dragged far enough,
        it hops over whole."""
        pt = args[0] if len(args) == 1 else QPoint(int(args[0]), int(args[1]))
        if not self._exact:                   # (lined up with a thing in the corner: as is)
            pt = self._on_one_screen(pt.x(), pt.y())
        old = self._lpos
        self._lpos = QPoint(pt)
        jump = abs(pt.x() - old.x()) + abs(pt.y() - old.y())
        if (self._exact or getattr(self, "_dragging", False) or jump > GLIDE_MAX
                or not self.isVisible()):
            self._from = QPoint(pt)
            super().move(pt)                  # there at once
        else:
            self._from = super().pos()        # glide from where it's drawn now
            self._from_t = time.monotonic()
            if not self._glide_timer.isActive():
                self._glide_timer.start(GLIDE_MS)

    # where the cat is (the window may still be gliding there)
    def x(self) -> int:
        return self._lpos.x()

    def y(self) -> int:
        return self._lpos.y()

    def pos(self) -> QPoint:
        return QPoint(self._lpos)

    def _glide(self) -> None:
        cur = super().pos()
        if cur == self._lpos:
            self._glide_timer.stop()            # arrived: nothing to do until the next move
            return
        t = (time.monotonic() - self._from_t) * 1000.0 / TICK_MS
        if t >= 1.0:
            super().move(self._lpos)
            self._glide_timer.stop()
            return
        f, to = self._from, self._lpos
        super().move(QPoint(int(round(f.x() + (to.x() - f.x()) * t)),
                            int(round(f.y() + (to.y() - f.y()) * t))))

    def _on_one_screen(self, x: int, y: int) -> QPoint:
        screens = QApplication.screens()
        if not screens:
            return QPoint(x, y)
        if not hasattr(self, "_unit_cache"):
            return QPoint(x, y)                   # still being built
        body = self._body()
        half = body.w / 0.75 / 2                  # the whole body, not just its core
        foot = self.foot_offset()
        cx, feet = x + W / 2, y + foot
        mid = QPoint(int(cx), int(feet - body.stand / 2))

        def dist(g: QRect) -> float:
            dx = max(g.left() - mid.x(), 0, mid.x() - g.right())
            dy = max(g.top() - mid.y(), 0, mid.y() - g.bottom())
            return dx * dx + dy * dy
        g = min((s.geometry() for s in screens), key=dist)
        cx = min(max(cx, g.left() + half), g.right() + 1 - half)
        feet = min(max(feet, g.top() + body.stand), g.bottom() + 1)
        return QPoint(int(round(cx - W / 2)), int(round(feet - foot)))

    def _sync_fpos(self) -> None:
        self._fx = float(self.x())
        self._fy = float(self.y())

    def _shown(self) -> tuple[str | None, int]:
        """(animation, frame index) actually on screen: a transition (sit
        down, turn around, …) if one is playing, else the state's anim."""
        if self._trans:
            return self._trans, self._trans_fi
        return (self._anim or (self.sheet.resolve(self.state) if self.sheet else None),
                self._afi)

    def _current_frame(self):
        """(pixmap, scale) for the frame being drawn, or None in vector mode."""
        if not self.sheet:
            return None
        name, fi = self._shown()
        frames = self.sheet.frames(name, self.facing) if name else []
        if not frames:
            return None
        pix = frames[fi % len(frames)]
        return pix, self._scale_for(pix)

    def pixel_scale(self) -> int:
        """The cat's usual drawing scale (screen px per art px), off pages."""
        if not self.sheet:
            return 3
        return int(self.sheet_scale or max(1, min((W - 6) // self.sheet.frame_w,
                                                   (H - 6) // self.sheet.frame_h)))

    def floor_line(self, screen) -> int:
        """Global y of the floor the cat stands on at the bottom of ``screen``
        (the bottom edge of its feet)."""
        from .screens import usable
        return usable(screen).bottom() - H + self.foot_offset()

    def _scale_for(self, pix) -> float:
        """Drawing scale: the sheet's own, or smaller to fit a web page's text."""
        if self._page_scale:
            return self._page_scale
        return self.sheet_scale or max(1, min((W - 6) // pix.width(), (H - 6) // pix.height()))

    def _sprite_box(self) -> tuple[int, int, int, int]:
        """Local (x, y, w, h) of the full drawn frame inside the window (used to
        place the pixmap)."""
        cur = self._current_frame()
        if cur:
            pix, scale = cur
            tw, th = round(pix.width() * scale), round(pix.height() * scale)
            x = (W - tw) // 2
            y = BASELINE - th + 8
            if y < 0:
                y = H - th
            return x, y, tw, th
        top = BASELINE - 92
        return 10, top, W - 20, (BASELINE + 4) - top

    def _opaque_rect(self, pix) -> QRect:
        """Tight bounding box of the non-transparent pixels of a frame (cached)."""
        key = pix.cacheKey()
        cached = self._opaque_cache.get(key)
        if cached is not None:
            return cached
        img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = img.width(), img.height()
        minx, miny, maxx, maxy = w, h, -1, -1
        for yy in range(h):
            for xx in range(w):
                if (img.pixel(xx, yy) >> 24) & 0xFF > 8:
                    minx = min(minx, xx); maxx = max(maxx, xx)
                    miny = min(miny, yy); maxy = max(maxy, yy)
        r = (QRect(0, 0, w, h) if maxx < 0
             else QRect(minx, miny, maxx - minx + 1, maxy - miny + 1))
        self._opaque_cache[key] = r
        return r

    def body_anchor(self) -> QRect:
        """Global box of the cat's fixed drawing area — stable frame-to-frame
        (unlike head_anchor, which tracks the animated opaque pixels). Use this
        to pin overlays like the focus pill so they don't jitter as the cat
        breathes or sleeps."""
        x, y, w, h = self._sprite_box()
        return QRect(self.x() + x, self.y() + y, w, h)

    def head_anchor(self) -> QRect:
        """Global box of the *visible* cat, so the bubble tail sits on the head
        rather than on empty transparent space at the top of the frame."""
        x, y, w, h = self._sprite_box()
        cur = self._current_frame()
        if cur:
            pix, scale = cur
            o = self._opaque_rect(pix)
            x += round(o.x() * scale)
            y += round(o.y() * scale)
            w = round(o.width() * scale)
            h = round(o.height() * scale)
        return QRect(self.x() + x, self.y() + y, w, h)

    # ---- speech ------------------------------------------------------
    def say(self, text: str, persist: bool = False) -> None:
        self.bubble.show_message(text, self.head_anchor(), tail_down=True)
        if self.state == "sleep":
            self.state = "sit"
            self._state_ticks = 0
        if (self.sheet and self.sheet.procedural and self.state in ("sit", "idle")
                and not self._focus):
            self.do_anim("talk", seconds=1.4)

    def hush(self) -> None:
        self.bubble.hide()

    # ---- emotes --------------------------------------------
    def play_emote(self, kind: str = "love", seconds: float = 2.0) -> None:
        """Show an original overlay effect (love/spark/music/question/excited)."""
        self._emote = kind
        self._emote_start = self.frame
        self._emote_frames = max(1, int(seconds * 1000 / TICK_MS))
        self.update()

    def do_anim(self, name: str, seconds: float = 0.0,
                hold_last: bool = False) -> bool:
        """Play a named sprite-sheet animation (e.g. 'meow', 'pounce'). By
        default a one-shot runs a single cycle. Pass ``seconds`` to extend it:
        with ``hold_last`` it plays once then FREEZES on the final frame for the
        rest of the time (e.g. 'flop over' — collapse, then lie there); without
        it the animation loops for the duration (e.g. tail swish). Returns False
        if the sheet lacks the animation."""
        if self._thing is not None or self._goal is not None:
            return False                       # busy with a thing (see go_use)
        if self.sheet and name in self.sheet.anims:
            self.state = name
            self._afi = 0
            self._aacc = 0.0
            self._hold_until = self.frame + int(seconds * 1000 / TICK_MS)
            self._hold_freeze = hold_last
            self.update()
            return True
        return False

    # ---- focus (pomodoro) poses -------------------------------------
    def begin_focus(self) -> None:
        """Enter focus mode: stop wandering and settle down — in its bed when
        it has one in the corner, else beside the user."""
        if self._guarding:
            self._guard_back = True               # after it's done guarding
            return
        self._focus = True
        self._focus_depth = 0.0
        if self._thing is not None and self._thing["spot"].kind == "bed":
            self._thing["until"] = None       # already in bed: stay
            return
        self._after_leave = []
        if self.go_use("bed"):
            return
        self.state = "sit"
        self._state_ticks = 0

    def focus_pose(self, depth: float) -> None:
        """Deepen the nap as the block runs down (0 = just settling, 1 = deep
        sleep). The cat's pose is the progress bar."""
        self._focus_depth = max(0.0, min(1.0, depth))
        if not self._focus or self._thing is not None or self._goal is not None:
            return                               # (asleep in its bed: the curl is the nap)
        if self._focus_depth < 0.35:
            target = "sit"                       # settling in, still alert
        else:
            target = "sleep"                     # curled up, asleep
        if self.state != target:
            self.state = target
            self._state_ticks = 0
        # deep in the block: drifting "z z z"
        if self._focus_depth >= 0.7 and not self._emote and random.random() < 0.03:
            self.play_emote("zzz", seconds=2.2)

    def wake_stretch(self, celebrate: bool = False) -> None:
        """Rouse from the focus nap — a little yawn/stretch, optional sparkle."""
        order = ("celebrate", "stretch", "yawn", "meow") if celebrate else \
            ("stretch", "yawn", "meow")
        if self._thing is not None or self._goal is not None:
            # out of bed first, then the stretch
            self._after_leave = [a for a in order if self.sheet and a in self.sheet.anims][:1]
            self.stop_using()
            if celebrate:
                self.play_emote("spark", seconds=1.8)
            return
        self.state = "sit"
        self._state_ticks = 0
        for a in order:                          # play one if the pack has it
            if self.do_anim(a):
                break
        if celebrate:
            self.play_emote("spark", seconds=1.8)

    def end_focus(self) -> None:
        """Leave focus mode and return to normal wandering behaviour."""
        self._focus = False
        self._focus_depth = 0.0
        if self._thing is not None or self._goal is not None:
            self.stop_using()
        if self.state == "sleep":
            self.state = "sit"
            self._state_ticks = 0

    # ---- guarding your focus -------------------------------------------
    GUARD_LINES = ("Focus time! This one can wait.", "Psst. We're focusing.",
                   "I'll keep this seat warm till the block's done.",
                   "Not now. Back to it!")

    def guard(self, on: bool, nap: bool = True) -> None:
        """Sit on the distracting page in front of you (a focus block's on and
        it's one of the sites you asked PISI to guard). Off again: back to the
        nap if ``nap`` (the block is still running), else just carry on."""
        if on == self._guarding:
            return
        self._guarding = on
        if on:
            self._guard_back = self._focus
            self._guard_said = False
            self._focus = False
            if self._thing is not None or self._goal is not None:
                self.stop_using()                 # out of bed first
            elif self.state == "sleep":
                self.state = "sit"
                self._state_ticks = 0
            return
        back, self._guard_back = self._guard_back and nap, False
        if back:
            self.begin_focus()                    # off the page and back to bed...
            if self._goal is None and self.y() < self._floor_y() - 2:
                self._leave_surface()             # ... or, with no bed, down to nap
                self._vy = 0.0
                self.state = "fall"
                self._state_ticks = 0

    def _guard_spot(self) -> tuple[perch.Seg, float] | None:
        """The ledge nearest the middle of the page you're looking at, and
        where on it to sit."""
        page = self._page()
        if page is None or page.view is None:
            return None
        vx, vy, vw, vh = page.view
        cx, cy = vx + vw / 2, vy + vh / 2
        hw = self._body().w / 2
        best, best_d = None, math.inf
        for seg in page.segs:
            if seg.x1 - seg.x0 < 2 * hw or seg.low:
                continue
            x = min(max(cx, seg.x0 + hw), seg.x1 - hw)
            d = abs(x - cx) + 1.5 * abs(seg.y - cy)
            if d < best_d:
                best, best_d = (seg, x), d
        return best

    def _guard_step(self) -> None:
        """On guard: up onto the middle of the page and stay there."""
        if self._thing is not None or self._goal is not None or self._trans:
            return                                # still getting out of bed
        if self._page() is None:
            return                                # the page isn't in view yet
        if not self._page_scale:
            self._set_page_scale(self._fit_page_scale())
        spot = self._guard_spot()
        if spot is None:
            return
        seg, x = spot
        cx, feet = self._feet()
        vx, vy, vw, vh = self._page().view
        middle = abs(cx - (vx + vw / 2)) < vw * 0.25 and abs(feet - (vy + vh / 2)) < vh * 0.3
        there = abs(feet - seg.y) <= 2 and abs(cx - x) < self._body().w
        if not (self._perched and (middle or there)):
            self._start_hop(int(round(x - W / 2)), int(round(seg.y - self.foot_offset())))
            return
        if self.state not in ("sit", "idle"):
            self.state = "sit"
            self._state_ticks = 0
        if not self._guard_said:
            self._guard_said = True
            self.say(random.choice(self.GUARD_LINES))

    # ---- burrowing through the text ----------------------------------------
    DIG_S = 1.3                   # one line's worth of digging
    DIG_LINES = (2, 4)            # how deep a burrow goes

    def can_dig(self) -> bool:
        """On a line of text, on a page that lets it make a mess."""
        if not (self._perched and self.sheet and "dig" in self.sheet.anims):
            return False
        if self.surfaces is None or not self.surfaces.going_on().get("mess"):
            return False
        seg = self.ledge()
        return seg is not None and seg.kind in perch.TEXT_KINDS

    def dig(self) -> bool:
        """Dig into the line under its paws: the extension flicks the words
        there off the page, leaving a hole, and down it drops onto the next
        line, where it digs again, a few lines deep."""
        if not self.can_dig():
            return False
        if self._mood != "dig":
            self._mood = "dig"
            self._dig_left = random.randint(*self.DIG_LINES)
        self._dig_left -= 1
        cx, feet = self._feet()
        self._dig_y = feet
        self.do_anim("dig", seconds=self.DIG_S)
        self.dug.emit(int(cx), int(round(feet)), int(self._body().w * 1.2), self.facing)
        return True

    def _dig_more(self) -> bool:
        """Dropped through onto the next line down: another one to dig?"""
        if self._dig_left <= 0 or not self._perched:
            return False
        _, feet = self._feet()
        return self._dig_y < feet < self._dig_y + self._body().stand * 3

    def _below_in_block(self) -> bool:
        """More lines of the same paragraph under this one (somewhere to dig to)."""
        seg, page = self.ledge(), self._page()
        if seg is None or page is None:
            return False
        cx, feet = self._feet()
        return any(b.block == seg.block and b.y0 > feet + 1 and b.x0 <= cx <= b.x1
                   for b in page.boxes)

    # ---- knocking a word off the end of the line ----------------------------
    def knock(self) -> bool:
        """The cat thing: to the end of its line of text, a long look at you,
        then a swat, and the last word goes over the edge (the extension
        tips it off the page)."""
        if not (self.can_dig() and "bat" in self.sheet.anims):
            return False
        seg = self.ledge()
        cx, _ = self._feet()
        page = self._page()
        line = next((b for b in page.boxes if abs(b.edge - seg.y) <= 1 and b.x0 <= cx <= b.x1), None)
        if line is None:
            return False
        # only an end of the ledge that is also where the text ends: a ledge
        # can stop short of it for other reasons (a heading above leaves no
        # headroom), and then the word there is nowhere near the cat. (The
        # ledge stops a little short of the text where its body still fits.)
        slack = self._body().w * 0.7
        ends = [side for side, ledge_end, text_end in ((1, seg.x1, line.x1), (-1, seg.x0, line.x0))
                if abs(ledge_end - text_end) <= slack]
        if not ends:
            return False
        side = min(ends, key=lambda s: abs((seg.x1 if s > 0 else seg.x0) - cx))   # the nearer one
        stand = (seg.x1 if side > 0 else seg.x0) - side * self._body().w * 0.45   # a paw's reach
        edge = line.x1 if side > 0 else line.x0
        self._knock = {"side": side, "edge": edge, "stage": "walk"}
        self._web_after = None
        if abs(stand - cx) > 3:
            self._walk_to(stand - W / 2, "walk")
        else:
            self._next_decision = 0
        return True

    def _knock_step(self) -> None:
        k = self._knock
        if not self._perched or self.ledge() is None or self._focus or self._guarding:
            self._knock = None                                   # it got down, or got busy
            return
        if k["stage"] == "walk":                                 # at the edge: look at you
            self.facing = k["side"]
            self.state = "stare" if "stare" in self.sheet.anims else "sit"
            self._state_ticks = 0
            self._next_decision = random.randint(16, 26)
            k["stage"] = "bat"
        elif k["stage"] == "bat":                                # ... and swat it
            _, feet = self._feet()
            self.on_frame("bat", 5, lambda: self.knocked.emit(int(k["edge"]), int(round(feet)), k["side"]))
            self.state = "sit"
            self.do_anim("bat")
            k["stage"] = "done"
            self._next_decision = 14
        else:
            self._knock = None
            self._next_decision = random.randint(30, 70)

    def leap_off(self) -> None:
        """Its page vanished from under it (the tab closed): a spooked leap
        down to the floor, just in time."""
        if not self._perched or self.state in ("hop", "climb"):
            return
        self._mood = ""
        x1 = int(round(self.x() - self.facing * self._body().w))
        self._start_hop(x1, self._floor_y(), lift=24.0)
        if self.sheet and "startle" in self.sheet.anims:
            self._hop["anim"] = "startle"

    # ---- main loop ---------------------------------------------------
    def _tick(self) -> None:
        if self._freeze > 0:                       # the hit pause: hold everything
            self._freeze -= 1
            return
        self.frame += 1
        self._state_ticks += 1

        # occasional blink
        if self.state != "sleep" and random.random() < 0.03:
            self.blink = 1.0
        elif self.blink > 0:
            self.blink = max(0.0, self.blink - 0.34)

        if self._dragging:
            self._advance_anim()
            self._reposition_bubble()
            self.update()
            return

        if self.reactions is not None:
            self.reactions.step()
        if self._thing is not None:
            self._thing_step()
        if self.state == "use":
            pass                                 # in / on a thing (see _thing_step)
        elif self.state in ("hop", "fall"):
            self._air_step()
        elif self.state == "climb" and self._climb is not None:
            self._climb_step()
        else:
            self._stay_on_surface()
            if self.state == "walk":
                self._walk_step()
            elif self.state not in ("hop", "fall", "climb"):
                self._maybe_decide()

        self._advance_anim()
        self._fire_frame_events()
        self._watch_bites()
        self._reposition_bubble()
        self._update_if_changed()

    def _update_if_changed(self) -> None:
        """Repaint only when what's drawn changed: a sleeping cat's frame
        changes 2.5 times a second, not every tick."""
        self._fade_meter()
        sig = (self._shown(), self.facing, self._angle, self._page_scale, self.blink > 0,
               id(self._thing), self._carry is not None, self.sheet is None and self.state,
               self._meter_sig())
        if sig != self._last_sig or self._emote or not self.sheet:
            self._last_sig = sig
            self.update()

    def _display_anim(self) -> str | None:
        """Which animation the current state shows."""
        sh = self.sheet
        if self._dragging and "dangle" in sh.anims:
            return "dangle"
        if self.state == "use" and self._thing is not None:
            return self._thing["anim"]
        if self._carry is not None:
            if self.state == "walk":
                want = "carrytrot" if self.gait == "run" else "carrywalk"
                if want in sh.anims:
                    return want
            if self.state in ("sit", "idle") and "carrysit" in sh.anims:
                return "carrysit"
        if self.state == "hop":
            if self._hop and self._hop.get("anim") in sh.anims:
                return self._hop["anim"]
            return next((a for a in ("jump", "pounce") if a in sh.anims), sh.resolve("walk"))
        if self.state == "fall":
            return next((a for a in ("dangle", "jump") if a in sh.anims), sh.resolve("sit"))
        if self.state == "climb":
            c = self._climb
            leg = c["legs"][c["leg"]] if c and c["leg"] < len(c["legs"]) else {}
            if leg.get("anim") in sh.anims:
                return leg["anim"]
            return sh.resolve("walk") or sh.resolve("run")
        if self.state == "walk" and self._squeeze and "crawl" in sh.anims:
            return "crawl"
        if self.state == "walk" and self._creep and "crouch" in sh.anims:
            return "crouch"
        if self.state == "walk" and sh.procedural:
            if self.gait == "run" and "run" in sh.anims:
                return "run"
            if self.tired and "trudge" in sh.anims:
                return "trudge"
            if "walk" in sh.anims:
                return "walk"
        return sh.resolve(self.state)

    def _anim_fps(self, name: str) -> float:
        sh = self.sheet
        fps = sh.fps_for(name)
        if self.state == "climb":
            return sh.fps_for(name)
        if self.state == "walk" and name in sh.speed and sh.speed[name] > 0:
            # play the gait exactly as fast as the window moves, so planted
            # paws stay planted on screen at any speed setting
            cur = self._current_frame()
            scale = cur[1] if cur else 3
            step = WALK_STEP.get(self.gait, 1.6) * self.speed * self.chase_boost
            px_per_s = step * 1000.0 / TICK_MS / scale
            return max(2.0, min(30.0, px_per_s / sh.speed[name]))
        if self.state == "walk" and self.gait == "walk" and not sh.procedural:
            fps *= 0.6          # slow the run cycle into a calm trot for walking
        return fps

    def _start_transition(self, name: str) -> None:
        self._trans = name
        self._trans_fi = 0
        self._trans_acc = 0.0

    def _watch_bites(self) -> None:
        """Eating or drinking at its bowl: a ``bite`` at the bottom of each
        bob (where the mouth dips lowest), for the crumbs or the splash."""
        t = self._thing
        if self.state != "use" or t is None or t["leaving"] or t["spot"].kind != "bowl":
            self._bite_fi = None
            return
        name, fi = self._shown()
        low = self._lowest_mouth_frame(name)
        if low is not None and fi == low and getattr(self, "_bite_fi", None) != fi:
            contents = t["spot"].r.design.get("contents", "food")
            mouth = self.mouth_global()
            if contents in ("food", "water") and mouth is not None:
                self.bite.emit(contents, mouth.x(), mouth.y())
        self._bite_fi = fi

    def _lowest_mouth_frame(self, name: str | None) -> int | None:
        if not name or not self.sheet:
            return None
        cache = self.__dict__.setdefault("_low_mouth", {})
        key = (id(self.sheet), name, self.facing)
        if key not in cache:
            frames = self.sheet.frames(name, self.facing)
            ys = []
            for i in range(len(frames)):
                an = self.sheet.anchor(name, i, self.facing)
                if an and an.get("mouth"):
                    ys.append((an["mouth"][1], i))
            cache[key] = max(ys)[1] if ys else None
        return cache[key]

    def on_frame(self, anim: str, frame: int, cb) -> None:
        """Call ``cb()`` once, when ``anim`` shows ``frame`` (e.g. the bat's
        tap knocks the toy, the bite picks it up)."""
        self._frame_events.append((anim, frame, cb))

    def _fire_frame_events(self) -> None:
        if not self._frame_events:
            return
        name, fi = self._shown()
        keep = []
        for ev in self._frame_events:
            anim, frame, cb = ev
            if anim == name and fi >= frame:
                try:
                    cb()
                except Exception:  # noqa: BLE001 - a game callback mustn't stop the cat
                    import logging
                    logging.getLogger(__name__).warning("frame event failed", exc_info=True)
            else:
                keep.append(ev)
        self._frame_events = keep

    def _advance_anim(self) -> None:
        if not self.sheet:
            return
        name = self._display_anim()
        if name != self._anim:
            prev = self._anim
            tr = None
            if prev:
                trs = self.sheet.transitions
                tr = (trs.get((prev, name)) or trs.get(("*", name))
                      or trs.get((prev, "*")))
                if tr in (prev, name):           # already there (a flop doesn't flop again)
                    tr = None
            self._anim = name
            self._afi = 0
            self._aacc = 0.0
            if tr and tr in self.sheet.anims and not self._dragging:
                self._start_transition(tr)
        if self._trans:
            tframes = self.sheet.frames(self._trans, self.facing)
            self._trans_acc += self.sheet.fps_for(self._trans) * TICK_MS / 1000.0
            while self._trans_acc >= 1.0:
                self._trans_acc -= 1.0
                self._trans_fi += 1
            if self._trans_fi >= len(tframes):
                self._trans = None
            else:
                return
        frames = self.sheet.frames(name, self.facing) if name else []
        if not frames:
            return
        if self.state == "climb" and self._climb is not None:
            c = self._climb
            leg = c["legs"][c["leg"]] if c["leg"] < len(c["legs"]) else {}
            if leg.get("anim") == name:
                n = len(frames)
                if leg.get("loop"):
                    geo = self._climb_geo()
                    c["acc"] += (self._climb_fps(geo) if geo else 8.0) * TICK_MS / 1000.0
                    fi = int(c["acc"]) % n
                else:                                 # follows the leg's progress
                    fi = min(n - 1, int(c["t"] * n))
                self._afi = n - 1 - fi if leg.get("rev") else fi
                return
        if self.state == "hop" and self._hop is not None:
            # the leap's frames follow its arc: crouch, fly, land (or just the
            # airborne part of an animation, e.g. a pounce's spring to landing)
            a, b = self._hop.get("frames") or (0, len(frames) - 1)
            b = min(b, len(frames) - 1)
            self._afi = min(b, a + int(self._hop["t"] * (b - a + 1)))
            return
        fps = self._anim_fps(name)
        self._aacc += fps * TICK_MS / 1000.0
        while self._aacc >= 1.0:
            self._aacc -= 1.0
            self._afi += 1
            if self._afi >= len(frames):
                if self.state in ONESHOT:    # one-shot: end unless still holding
                    if self.frame < getattr(self, "_hold_until", 0):
                        # freeze on the last frame (flop) or loop from the start
                        self._afi = len(frames) - 1 if self._hold_freeze else 0
                    else:
                        self._afi = 0
                        self.state = "sit"
                        self._state_ticks = 0
                else:
                    self._afi = 0

    def _walk_step(self) -> None:
        dx = self.target.x() - self.x()
        dy = self.target.y() - self.y()
        dist = math.hypot(dx, dy)
        if self._perched:
            seg = perch.support(self._segments(), *self._feet())
            self._creep = bool(seg is not None and seg.low)
            self._squeeze = bool(seg is not None and seg.tight)
        step = (3.8 if self.gait == "run" else 1.6) * self.speed * self.chase_boost
        if self._squeeze:
            step = 0.9 * self.speed                     # squeezing through on its belly
        elif self._creep:
            step = 1.3 * self.speed                     # creeping under something low
        elif self._page_scale:
            step *= max(0.5, self._page_scale / self._base_scale()) ** 0.5
        if dist <= step:
            self.move(self.target)
            self.state = "sit"
            self._state_ticks = 0
            self._next_decision = random.randint(30, 90)
            self._arrive()
            return
        if abs(dx) > 2:
            new_facing = 1 if dx > 0 else -1
            if new_facing != self.facing:
                self.facing = new_facing
                if self.sheet and "turn" in self.sheet.anims_left:
                    self._start_transition("turn")
        if self._trans:
            return              # stand up / turn around before moving off
        # keep the fractions: a slow crawl moves less than a pixel a tick
        if abs(self._fx - self.x()) > 1.5 or abs(self._fy - self.y()) > 1.5:
            self._sync_fpos()                        # moved by something else meanwhile
        self._fx += step * dx / dist
        self._fy += step * dy / dist
        want = QPoint(int(round(self._fx)), int(round(self._fy)))
        self.move(want)
        if self.pos() != want and abs(self.x() - want.x()) > 1:
            self.target = self.pos()                 # held at a screen edge: that's as far as it goes
            self._sync_fpos()

    def _maybe_decide(self) -> None:
        if self._guarding:
            self._guard_step()
            return
        if self._focus or self.in_play:
            return                       # holding a calm nap pose / playing: no wandering
        if self._state_ticks < self._next_decision:
            return
        self._state_ticks = 0
        if self._knock is not None:
            self._knock_step()
            return
        if self._mood == "dig":
            if self._dig_more() and self.dig():
                return
            self._mood = ""
        if self.state == "sleep":
            self.state = "sit"
            self._next_decision = random.randint(30, 80)
            return
        if self._perched and self.wander_enabled and random.random() < KNOCK_CHANCE and self.knock():
            return
        if (self._perched and self.wander_enabled and random.random() < DIG_CHANCE
                and self._below_in_block() and self.dig()):
            return
        if self._perched and self.wander_enabled and self._web_move():
            return
        if self.home and self.wander_enabled and not self._perched and random.random() < VISIT_CHANCE:
            kinds = [k for k in VISITS if self.home(k) is not None]
            if kinds:
                kind = random.choice(kinds)
                lo, hi = VISITS[kind]
                if self.go_use(kind, random.uniform(lo, hi)):
                    return
        roll = random.random()
        if self.wander_enabled and roll < 0.55:
            if not self._web_move() and not self._perched:
                if self.y() < self._floor_y() - 2:
                    self._vy = 0.0                   # up in the air: down to the floor first
                    self.state = "fall"
                    self._state_ticks = 0
                    return
                self._pick_target()
                self.state = "walk"
        elif roll < 0.66 and self.sheet and "yawn" in self.sheet.anims:
            self.state = "yawn"          # brief one-shot (image mode only)
            self._afi = 0
            self._next_decision = random.randint(30, 70)
        elif roll < 0.78:
            self.state = "sleep"
            self._next_decision = random.randint(120, 260)
        else:
            self._next_decision = random.randint(40, 110)

    def _reposition_bubble(self) -> None:
        if self.bubble.isVisible():
            self.bubble.reposition(self.head_anchor())

    # ---- playing --------------------------------------------------------------
    def carry(self, toy, scale: int) -> None:
        """Hold ``toy`` (a things Rendered) in the mouth (needs a rig: the
        procedural cat)."""
        from .home import pixmap
        self._carry = {"toy": toy, "pm": {1: pixmap(toy.back, toy.w, toy.h, scale),
                                          -1: pixmap(toy.back, toy.w, toy.h, scale, mirror=True)}}
        self.update()

    def carrying(self):
        return self._carry["toy"] if self._carry is not None else None

    def let_go(self) -> None:
        self._carry = None
        self.update()

    def mouth_global(self) -> QPoint | None:
        """Where the mouth is on screen right now (None without a rig)."""
        if not self.sheet:
            return None
        name, fi = self._shown()
        an = self.sheet.anchor(name, fi, self.facing) if name else None
        cur = self._current_frame()
        if not an or not an.get("mouth") or not cur:
            return None
        x, y, tw, _th = self._sprite_box()
        s = tw / cur[0].width()
        return QPoint(self.x() + int(x + (an["mouth"][0] + 0.5) * s),
                      self.y() + int(y + (an["mouth"][1] + 0.5) * s))

    # ---- the energy meter (play) ------------------------------------------------
    METER_PIPS = 4
    METER_FADE = 0.16                      # alpha per tick (~0.45 s in or out)
    _PIP = ("..##..", ".#++#.", "#+**+#", "#++++#", ".#++#.", "..##..")   # an orb, art pixels

    def set_meter(self, value: float | None) -> None:
        """Show (fading in) the energy pips at ``value`` (0..1); None fades
        them out."""
        if value is None:
            self._meter_on = False
            return
        self._meter_on = True
        self._meter = max(0.0, min(1.0, float(value)))

    def meter_shown(self) -> bool:
        return self._meter is not None and self._meter_alpha > 0.0

    def _fade_meter(self) -> None:
        if self._meter is None:
            return
        a = self._meter_alpha + (self.METER_FADE if self._meter_on else -self.METER_FADE)
        self._meter_alpha = max(0.0, min(1.0, a))
        if not self._meter_on and self._meter_alpha <= 0.0:
            self._meter = None

    def _meter_sig(self):
        if self._meter is None:
            return None
        return (round(self._meter * self.METER_PIPS * 2), round(self._meter_alpha * 8))

    def _meter_place(self, s: int, width: int) -> tuple[int, int]:
        """Window (x, y) of the pips: centred over the head and clear of the
        ear tips as the cat sits (steady while it runs and leaps), kept
        inside the window."""
        h = len(self._PIP) * s
        x, y = (W - width) // 2, BASELINE - 92 - h
        frames = self.sheet.frames("sit", self.facing) if self.sheet and "sit" in self.sheet.anims else []
        if frames:
            bx, by, bw, _bh = self._sprite_box()
            sc = bw / max(1, frames[0].width())
            top = self._opaque_rect(frames[0]).top()
            y = int(by + top * sc) - h - 3 * s
            an = self.sheet.anchor("sit", 0, self.facing)
            if an and an.get("head_top"):
                x = int(bx + (an["head_top"][0] + 0.5) * sc) - width // 2
        return max(2, min(x, W - width - 2)), max(2, y)

    def _draw_meter(self, p: QPainter) -> None:
        if self._meter is None or self._meter_alpha <= 0.0:
            return
        s = max(2, self.pixel_scale() // 1)
        s = max(2, s - 1)                              # a touch finer than the cat
        n = self.METER_PIPS
        pw = len(self._PIP[0])
        gap = 2 * s
        total = n * pw * s + (n - 1) * gap
        x0, y0 = self._meter_place(s, total)
        a = self._meter_alpha
        level = self._meter * n                       # pips worth of energy
        ink = QColor(22, 40, 84, int(235 * a))        # outline: deep navy
        full = QColor(64, 150, 255, int(255 * a))     # energy blue
        shine = QColor(190, 228, 255, int(255 * a))   # highlight
        empty = QColor(22, 40, 84, int(90 * a))
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(n):
            fill = max(0.0, min(1.0, level - k))     # this pip: 0, ½ or 1
            fill = 1.0 if fill > 0.75 else 0.5 if fill > 0.25 else 0.0
            px = x0 + k * (pw * s + gap)
            rows = len(self._PIP)
            for ry, row in enumerate(self._PIP):
                lit = (rows - 1 - ry) < rows * fill   # fills from the bottom
                for rx, ch in enumerate(row):
                    if ch == ".":
                        continue
                    if ch == "#":
                        c = ink
                    elif not lit:
                        c = empty
                    else:
                        c = shine if ch == "*" and fill == 1.0 else full
                    p.fillRect(px + rx * s, y0 + ry * s, s, s, c)
        p.restore()

    def hit_pause(self, seconds: float = 0.1) -> None:
        """Freeze for a beat on a catch (a game's 'hit stop')."""
        self._freeze = max(1, int(round(seconds * 1000 / TICK_MS)))

    def paw_global(self) -> QPoint | None:
        """Where the near front paw is on screen right now."""
        if not self.sheet:
            return None
        name, fi = self._shown()
        an = self.sheet.anchor(name, fi, self.facing) if name else None
        cur = self._current_frame()
        paw = (an or {}).get("paws", {}).get("nf")
        if not paw or not cur:
            return None
        x, y, tw, _th = self._sprite_box()
        s = tw / cur[0].width()
        return QPoint(self.x() + int(x + (paw[0] + 0.5) * s), self.y() + int(y + (paw[1] + 1) * s))

    def can_play(self) -> bool:
        """The full play set needs the rigged (procedural) cat."""
        return bool(self.sheet and getattr(self.sheet, "procedural", False)
                    and all(a in self.sheet.anims for a in ("bat", "pickup", "drop", "carrywalk")))

    # ---- playing on whatever it stands on (the floor, or a ledge on a page) ----------
    def ledge(self) -> perch.Seg | None:
        """The page ledge it stands on (None: on the floor, or in the air)."""
        if not self._perched:
            return None
        return perch.support(self._segments(), *self._feet())

    def ground_line(self) -> int:
        """Global y of what its feet stand on: a ledge, or the floor."""
        if self._perched:
            return int(round(self._feet()[1]))
        return self.floor_line(self.screen() or QApplication.primaryScreen())

    def _ground_y(self) -> int:
        """Window y standing on what it stands on."""
        return self.y() if self._perched else self._floor_y()

    def _on_ledge_x(self, x: float) -> float:
        """Window x kept on its ledge (it doesn't run off the end of the text)."""
        seg = self.ledge()
        if seg is None:
            return x
        return min(max(x, seg.x0 - W / 2), seg.x1 - W / 2)

    def run_to(self, x: float, gait: str = "run") -> None:
        """Along the floor (or its ledge) to window x, never through the air."""
        self._web_after = None
        x = self._on_ledge_x(x)
        gy = self._ground_y()
        self.target = QPoint(self._on_one_screen(int(round(x)), gy).x(), gy)
        self.gait = gait
        self._sync_fpos()
        if self.state != "walk":
            self.state = "walk"
            self._state_ticks = 0
        self._next_decision = 10 ** 6

    def pounce_to(self, x: float, lift: float = 30.0) -> None:
        """Leap along an arc to window x on the floor, showing the pounce's
        airborne frames (spring, stretched leap, landing)."""
        self._start_hop(int(round(self._on_ledge_x(x))), self._ground_y(), lift)
        if "pounce" in self.sheet.anims:
            self._hop["anim"] = "pounce"
            self._hop["frames"] = (5, 9)

    def jump_up(self, height: float) -> None:
        """Straight up after something above, and down again."""
        self._start_hop(self.x(), self._ground_y(), max(20.0, height))
        if "jump" in self.sheet.anims:
            self._hop["anim"] = "jump"
            self._hop["frames"] = (2, 7)

    def face(self, x_global: float) -> None:
        d = 1 if x_global > self.x() + W / 2 else -1
        if d != self.facing:
            self.facing = d
            if self.sheet and "turn" in self.sheet.anims_left and self.state in ("sit", "idle"):
                self._start_transition("turn")

    def busy(self) -> bool:
        """In the middle of something that shouldn't be interrupted."""
        return (self._trans is not None or self.state in ("hop", "fall", "climb", "use")
                or self.state in ONESHOT)

    # ---- PISI's corner: using things ------------------------------------------
    def using(self) -> str | None:
        """Kind of thing the cat is in / on / heading to, or None."""
        if self._thing is not None:
            return self._thing["spot"].kind
        return self._goal["kind"] if self._goal is not None else None

    def go_use(self, kind: str, seconds: float | None = None, anim: str | None = None) -> bool:
        """Walk over to ``kind`` in the corner and use it (``seconds`` None =
        until told to stop). False if there's no such thing or the pet can't
        use it."""
        spot = self.home(kind) if self.home else None
        if spot is None or not self.sheet or (anim or spot.r.cat_state) not in self.sheet.anims:
            return False
        if self._thing is not None:
            if self._thing["spot"].kind == kind and not self._thing["leaving"]:
                self._thing["until"] = None if seconds is None else \
                    self.frame + int(seconds * 1000 / TICK_MS)
                return True
            self._drop_thing()
        self._goal = {"kind": kind, "seconds": seconds, "stage": "walk", "anim": anim}
        self._web_after = None
        if self._perched or self.y() < self._floor_y() - 2:
            self._leave_surface()
            self._vy = 0.0
            self.state = "fall"                    # down to the floor first
            self._state_ticks = 0
            return True
        self._leave_surface()
        self._head_to_goal()
        return True

    def _goal_window(self, spot) -> QPoint:
        """Window position that puts the cat's frame where the thing wants it."""
        x, y, _w, _h = self._sprite_box()
        fp = spot.cat_frame_pos(self.sheet.frame_w)
        return QPoint(fp.x() - x, fp.y() - y)

    def _home_floor_y(self, spot) -> int:
        """Window y standing on the cat's usual floor by the corner (the things
        themselves stand lower, in the taskbar's strip)."""
        return spot.walk_floor - self.foot_offset() if spot.walk_floor else self._floor_y()

    def _head_to_goal(self) -> None:
        spot = self.home(self._goal["kind"]) if self.home and self._goal else None
        if spot is None:
            self._goal = None
            return
        win = self._goal_window(spot)
        self._goal["stage"] = "walk"
        self.target = QPoint(win.x(), self._home_floor_y(spot))
        self.gait = "run" if abs(win.x() - self.x()) > 600 else "walk"
        self._sync_fpos()
        self.state = "walk"
        self._state_ticks = 0
        self._next_decision = 10 ** 6
        if abs(self.target.x() - self.x()) <= 2 and abs(self.target.y() - self.y()) <= 2:
            self._reach_goal()

    def _reach_goal(self) -> None:
        spot = self.home(self._goal["kind"]) if self.home else None
        if spot is None:
            self._goal = None
            return
        if spot.facing != self.facing:
            self.facing = spot.facing
            if "turn" in self.sheet.anims_left:
                self._start_transition("turn")
        win = self._goal_window(spot)
        if abs(win.y() - self.y()) > 2:            # down into the taskbar's strip, or up into a bed
            self._goal["stage"] = "hop"
            self._exact = True
            self._start_hop(win.x(), win.y(), lift=18.0 if win.y() < self.y() else 8.0)
            self.facing = spot.facing
            return
        self._begin_use()

    def _begin_use(self) -> None:
        spot = self.home(self._goal["kind"]) if self.home and self._goal else None
        goal, self._goal = self._goal, None
        if spot is None:
            self._exact = False
            self.state = "sit"
            return
        self._exact = True
        self.move(self._goal_window(spot))
        self._sync_fpos()
        self._exact = False
        secs = goal.get("seconds") if goal else None
        anim = (goal.get("anim") if goal else None) or spot.r.cat_state
        self._thing = {"spot": spot, "anim": anim, "leaving": False,
                       "until": None if secs is None else self.frame + int(secs * 1000 / TICK_MS)}
        self.facing = spot.facing
        self.state = "use"
        self._state_ticks = 0
        self._anim = anim                         # (no automatic transition)
        self._afi = 0
        enter = ENTER.get(anim)
        if enter and enter in self.sheet.anims:
            self._start_transition(enter)

    def stop_using(self) -> None:
        """Get out of / off the thing: its way-out transition, then down."""
        if self._thing is None:
            self._goal = None
            if self.state == "walk":
                self.state = "sit"
            self._exact = False
            return
        if self._thing["leaving"]:
            return
        anim = self._thing["anim"]
        self._thing["leaving"] = True
        self.state = "sit"
        self._state_ticks = 0
        self._next_decision = 10 ** 6             # nothing else until it's out
        self._anim = "sit"
        ex = EXIT.get(anim)
        if ex and ex in self.sheet.anims:
            self._start_transition(ex)

    def _drop_thing(self) -> None:
        """Stop at once (picked up, called over): no way-out animation."""
        self._thing = None
        self._goal = None
        self._exact = False
        if self.state == "use":
            self.state = "sit"
            self._state_ticks = 0

    def _thing_step(self) -> None:
        t = self._thing
        if not t["leaving"]:
            if t["until"] is not None and self.frame >= t["until"]:
                self.stop_using()
            return
        if self._trans:
            return                                 # still uncurling
        spot = t["spot"]
        self._thing = None
        floor = self._home_floor_y(spot)
        if abs(self.y() - floor) > 2:              # out of it and back to its floor, forwards
            self._exact = True
            self._start_hop(self.x() + spot.facing * 6 * spot.scale, floor,
                            lift=10.0 if self.y() < floor else 16.0)
            self._hop["home"] = True
            self.facing = spot.facing
        else:
            self.state = "sit"
            self._state_ticks = 0
            self._next_decision = random.randint(20, 50)
            self._play_after_leave()

    def _play_after_leave(self) -> None:
        todo, self._after_leave = self._after_leave, []
        for a in todo:
            if self.do_anim(a):
                break

    # ---- standing on page text ----------------------------------------
    def foot_offset(self) -> int:
        """Local y of the pet's feet in its window (standing pose)."""
        if self._foot is not None:
            return self._foot
        foot = BASELINE + 4
        if self.sheet:
            name = self.sheet.resolve("idle") or self.sheet.resolve("sit")
            frames = self.sheet.frames(name, 1) if name else []
            if frames:
                pix = frames[0]
                scale = self._scale_for(pix)
                th = round(pix.height() * scale)
                y = BASELINE - th + 8
                if y < 0:
                    y = H - th
                o = self._opaque_rect(pix)
                foot = y + round((o.y() + o.height()) * scale)
        self._foot = foot
        return foot

    # the pet's size, at drawing scale 1
    def _unit_body(self) -> perch.Body:
        key = id(self.sheet)
        if self._unit_cache is not None and self._unit_cache[0] == key:
            return self._unit_cache[1]
        body = perch.Body(w=100, stand=92, crouch=70, sit=80)      # the drawn cat
        if self.sheet:
            def size(*names):
                ws, hs = [], []
                for n in names:
                    if n and n in self.sheet.anims:
                        for pix in self.sheet.frames(n, 1):
                            o = self._opaque_rect(pix)
                            ws.append(o.width())
                            hs.append(o.height())
                return (max(ws), max(hs)) if hs else None
            walk = size("walk", "idle") or size("run") or size(self.sheet.resolve("sit"))
            if walk:
                crouch = size("crouch") or size("sleep")
                sit = size("sit")
                crawl = size("crawl")
                stand = walk[1]
                body = perch.Body(w=walk[0] * 0.75, stand=stand,
                                  crouch=min(stand, crouch[1]) if crouch else stand * 0.76,
                                  sit=min(stand, sit[1]) if sit else stand,
                                  crawl=crawl[1] if crawl else 0.0)
        self._unit_cache = (key, body)
        return body

    def _base_scale(self) -> float:
        if not self.sheet:
            return 1.0
        name = self.sheet.resolve("idle") or self.sheet.resolve("sit")
        frames = self.sheet.frames(name, 1) if name else []
        if not frames:
            return 1.0
        pix = frames[0]
        return self.sheet_scale or max(1, min((W - 6) // pix.width(), (H - 6) // pix.height()))

    def _cur_scale(self) -> float:
        return self._page_scale or self._base_scale() if self.sheet else 1.0

    def _body(self) -> perch.Body:
        """The pet's size right now, for fitting under things on a page."""
        return self._unit_body().scaled(self._cur_scale())

    def _fit_page_scale(self) -> float:
        """A size that suits the page's text: small enough to creep between
        paragraphs, in whole screen pixels so the art stays crisp. 0 = the
        usual size."""
        if not self.sheet or not self.web_fit or self.surfaces is None:
            return 0
        scr = self.screen() or QApplication.primaryScreen()
        dpr = max(1.0, scr.devicePixelRatio() if scr else 1.0)
        base = self._base_scale()
        opts = sorted({round(k / dpr, 3) for k in range(1, int(base * dpr) + 1)})
        opts = [o for o in opts if o >= 0.5] or [base]
        line_h, gap = self.surfaces.metrics()
        s = perch.fit_scale(self._unit_body(), line_h, gap, opts)
        return 0 if s >= base else s

    def _set_page_scale(self, s: float) -> None:
        """Change size, keeping the feet where they are."""
        if s == self._page_scale:
            return
        cx, feet = self._feet()
        self._page_scale = s
        self._foot = None
        self.move(int(round(cx - W / 2)), int(round(feet - self.foot_offset())))
        self._sync_fpos()
        self.update()

    def _page(self) -> perch.Page | None:
        """The page in front of the pet, as ledges that fit it (cached)."""
        sf = self.surfaces
        if sf is None or self._focus or not sf.active:
            return None
        ceiling = self._screen_rect().top()
        key = (id(sf), sf.version, self._cur_scale(), ceiling, self._recent_ledges())
        if self._page_key == key:
            return self._page_val
        body = self._body()
        boxes = sf.boxes()
        view = sf.view()
        page = perch.Page(perch.ledges(boxes, body, view, ceiling, sf.window()), boxes, body, view,
                          calm=not self._page_scale, recent=self._recent_ledges(),
                          floor=self._floor_seg())
        self._page_key, self._page_val = key, page
        return page

    def _segments(self) -> list:
        page = self._page()
        return page.segs if page else []

    def _feet(self) -> tuple[float, float]:
        return self.x() + W / 2, self.y() + self.foot_offset()

    def _floor_y(self) -> int:
        """Window y when standing on the bottom of the screen (the taskbar)."""
        return self._screen_rect().bottom() - H

    def _leave_surface(self) -> None:
        self._perched = False
        self._hop = None
        self._climb = None
        self._angle = 0.0
        self._mood = ""
        self._creep = False
        self._squeeze = False
        self._set_page_scale(0)
        if self.state in ("hop", "fall", "climb"):
            self.state = "sit"
            self._state_ticks = 0

    def _web_move(self) -> bool:
        """Play on the page in front of us (see perch.plan): explore a shelf,
        hop over a button, climb up the side of the text, nap on the search
        box... False = nothing to play on; wander as usual."""
        page = self._page()
        if page is None or not page.segs:
            return False
        cx, feet = self._feet()
        here = perch.support(page.segs, cx, feet) if self._perched else None
        if here is not None and random.random() < 0.02:
            # now and then back down to the floor for a change of scene: down
            # the side of the text, not a leap off the top of the page
            floor = self._floor_seg()
            down = [c for c in perch.climbs(page.segs + [floor], page.boxes, page.body, here, cx)
                    if c.seg is floor]
            if down:
                c = min(down, key=lambda c: abs(c.start_x - cx))
                mv = perch.Move("climb", c.x, floor, wall=c.wall_x, side=c.side, start=c.start_x,
                                edge=c.edge, linger=random.randint(20, 60))
                self._web_after = mv
                self._mood = ""
                start, _ = self._climb_plan(mv)
                if abs(start - cx) > 3:
                    self._walk_to(start - W / 2, "walk")
                else:
                    self._start_climb(mv)
                return True
        if here is None:
            if self._perched or abs(self.y() - self._floor_y()) > 2:
                return False                  # in mid-air: land first, no flying up
            # on the floor: take on the page's size, then find a way up
            s = self._fit_page_scale()
            if s != self._page_scale:
                self._set_page_scale(s)
                page = self._page()
                if page is None or not page.segs:
                    return False
                cx, feet = self._feet()
            here = self._floor_seg()
        mv = perch.plan(page, here, cx, self.facing, mood=self._mood)
        if mv is None:
            return False
        return self._go_page(mv, here, cx)

    def _go_page(self, mv, here, cx: float) -> bool:
        """Set off on a page move (walk, hop, climb, scale or stay)."""
        self._web_after = mv
        self._mood = mv.mood
        if mv.kind == "stay":
            self._arrive()
            return True
        r = self._screen_rect()
        if mv.kind in ("climb", "scale"):
            start, _legs = self._climb_plan(mv)
            if abs(start - cx) > 3:
                self._walk_to(start - W / 2, "walk")         # to the edge first
            else:
                self._start_climb(mv)
            return True
        x1 = int(max(r.left() - W / 2, min(mv.x - W / 2, r.right() - W / 2)))
        if mv.kind in ("walk", "run") and (self._perched or here.kind == "floor"):
            self._walk_to(x1, mv.kind)
            return True
        if mv.kind == "hop" and mv.edge and abs(mv.start - cx) > 3:
            self._walk_to(mv.start - W / 2, "walk")       # to the take-off spot first
            return True
        self._start_hop(x1, int(round(mv.seg.y - self.foot_offset())), mv.lift)
        return True

    def toward(self, x: float, y: float, rise: float | None = None) -> str | None:
        """One leg of the way across the page to get at the point (x, y)
        (a laser dot up on the text): a leap, a climb up the side of the
        text, or a walk along its shelf, onto the ledge best placed to
        reach it from (with the point at most ``rise`` above it; default a
        leap's height). The kind of move it set off on, or None (nowhere
        better to be than here, or no page)."""
        page = self._page()
        if page is None or not page.segs:
            return None
        cx, feet = self._feet()
        here = perch.support(page.segs, cx, feet) if self._perched else None
        if here is None:
            if self._perched or abs(self.y() - self._floor_y()) > 2:
                return None
            s = self._fit_page_scale()                 # the page's size, before the way up
            if s != self._page_scale:
                self._set_page_scale(s)
                page = self._page()
                if page is None or not page.segs:
                    return None
                cx, feet = self._feet()
            here = self._floor_seg()
        path = perch.route(page, here, cx, max_nodes=80,
                           score=perch.reach_score(x, y, page.body, rise))
        if not path:
            return None
        mv = perch._go(path[0], random, page.body)
        mv = replace(mv, linger=0, pose="sit", mood="")
        self._go_page(mv, here, cx)
        return mv.kind

    def get_down(self, x: float) -> bool:
        """Off its ledge and down toward window x, the way a cat would:
        down the side of the text if there's a way, otherwise to the end of
        the ledge, a step off, and a drop straight down (onto a ledge below,
        or the floor). Never a glide through the text. False: not on a ledge."""
        page = self._page()
        cx, feet = self._feet()
        here = perch.support(page.segs, cx, feet) if page and self._perched else None
        if here is None:
            return False
        want = x + W / 2                               # where it wants its middle to end up
        floor = self._floor_seg()
        downs = [c for c in perch.climbs(page.segs + [floor], page.boxes, page.body, here, cx)
                 if c.seg is floor]
        if downs:                                      # down the side of the text
            c = min(downs, key=lambda c: abs(c.start_x - cx) + 0.5 * abs(c.x - want))
            mv = perch.Move("climb", c.x, floor, wall=c.wall_x, side=c.side, start=c.start_x,
                            edge=c.edge)
            return self._go_page(mv, here, cx)
        # off the end nearest where it's going: step off, then drop
        lo, hi = perch.shelf(page.segs, here)
        side = 1 if want >= cx else -1
        end = hi if side > 0 else lo
        clear = page.body.w * 0.6
        off = perch.Seg(end + side * clear - 1, end + side * clear + 1, here.y + 2, "air")
        mv = perch.Move("hop", off.x0 + 1, off, lift=10.0, start=end - side * 2, edge=1.0)
        return self._go_page(mv, here, cx)

    RECENT_S = 180.0              # how long it remembers where it's just been

    def _recent_ledges(self) -> tuple:
        now = time.monotonic()
        return tuple((y, x0, x1) for y, x0, x1, t in self._recent if now - t < self.RECENT_S)

    def _floor_seg(self) -> perch.Seg:
        """The bottom of the screen, as a shelf the pet can start a climb from."""
        r = self._screen_rect()
        half = self._body().w / 0.75 / 2
        return perch.Seg(r.left() + half, r.right() + 1 - half, self._floor_y() + self.foot_offset(),
                         "floor", -3)

    def _walk_to(self, x: float, gait: str) -> None:
        # somewhere it can actually be (whole, on this screen)
        self.target = QPoint(self._on_one_screen(int(round(x)), self.y()).x(), self.y())
        self.gait = gait
        self.state = "walk"
        self._state_ticks = 0

    def _arrive(self) -> None:
        """Finish a page move: face the way it said, then linger in its pose."""
        if self._knock is not None and self._knock["stage"] == "walk":
            self._next_decision = 4                # at the edge: no dawdling before the look
            return
        if self._goal is not None and self._goal.get("stage") == "walk":
            self._reach_goal()
            return
        mv, self._web_after = self._web_after, None
        if mv is None:
            return
        if mv.kind in ("climb", "scale"):
            self._start_climb(mv)                 # walked to the wall: up we go
            return
        if mv.kind == "hop" and mv.edge:
            # walked to the take-off spot: leap
            self._web_after = replace(mv, edge=0.0)
            r = self._screen_rect()
            x1 = int(max(r.left() - W / 2, min(mv.x - W / 2, r.right() - W / 2)))
            self._start_hop(x1, int(round(mv.seg.y - self.foot_offset())), mv.lift)
            return
        if mv.face:
            if mv.face != self.facing and self.sheet and "turn" in self.sheet.anims_left:
                self._start_transition("turn")
            self.facing = mv.face
        self._state_ticks = 0
        self._next_decision = mv.linger
        self._rest(mv.pose, mv.linger)

    def _rest(self, pose: str, linger: int) -> None:
        if pose == "sleep":
            self.state = "sleep"
        elif pose == "crouch":
            self.state = "crouch" if self.sheet and "crouch" in self.sheet.anims else "sleep"
        elif pose == "crawl":
            self.state = "crawl" if self.sheet and "crawl" in self.sheet.anims else "sleep"
            self._next_decision = min(self._next_decision, 4)  # it doesn't stay
        elif pose == "lookaround" and self.sheet and "lookaround" in self.sheet.anims:
            self.do_anim("lookaround")
            self._next_decision = linger
        else:
            self.state = "sit"
            # lounging: now and then a tail swish, a yawn, a stretch
            idle = [a for a in ("tailswish", "yawn", "stretch", "lookaround")
                    if self.sheet and a in self.sheet.anims]
            if idle and self._perched and random.random() < 0.3:
                self.do_anim(random.choice(idle))
                self._next_decision = linger

    def _start_hop(self, x1: int, y1: int, lift: float | None = None) -> None:
        dist = math.hypot(x1 - self.x(), y1 - self.y())
        self._hop = {"x0": float(self.x()), "y0": float(self.y()),
                     "x1": float(x1), "y1": float(y1), "t": 0.0, "lift": lift,
                     "dt": TICK_MS / max(380.0, min(1100.0, 300 + dist * 1.3))}
        if abs(x1 - self.x()) > 2:
            self.facing = 1 if x1 > self.x() else -1
        self._perched = False
        self._creep = False
        self._squeeze = False
        self._trans = None
        self.state = "hop"
        self._state_ticks = 0

    # ---- climbing up the side of the text ----------------------------------
    def _climb_geo(self) -> dict | None:
        """How the sheet's climbing frames line up (None = no climbing frames:
        fall back to the walk cycle turned onto the wall). From the frames
        themselves: where the wall is in the frame, how much lower the
        pull-up starts, and where it leaves the pet standing."""
        sh = self.sheet
        if not sh or not all(n in sh.anims for n in ("climb", "pullup")):
            return None
        key = id(sh)
        if self._geo_cache and self._geo_cache[0] == key:
            return self._geo_cache[1]
        from .creatures.quadmotion import WALL_FRAC
        stand = sh.frames(sh.resolve("idle") or sh.resolve("sit"), 1)[0]
        last = sh.frames("pullup", 1)[-1]
        o1, o2 = self._opaque_rect(stand), self._opaque_rect(last)
        fw = stand.width()
        d = float(sh.speed.get("pullup", 0.0))
        dy = float((o2.y() + o2.height()) - (o1.y() + o1.height()))
        geo = {"wall": round(fw * WALL_FRAC) - fw / 2,     # frame px right of the middle
               "d": d, "dx": float((o2.x() + o2.width()) - (o1.x() + o1.width())),
               "dy": dy, "K": d - dy, "speed": float(sh.speed.get("climb", 1.0)),
               "pull_n": len(sh.frames("pullup", 1)), "pull_fps": sh.fps_for("pullup")}
        self._geo_cache = (key, geo)
        return geo

    def _climb_plan(self, mv) -> tuple[float, list]:
        """(where to stand before starting, the legs of the climb)."""
        if mv.kind == "scale":
            return self._scale_plan(mv)
        cx, feet = self._feet()
        up = mv.seg.y < feet
        s = self._cur_scale()
        geo = self._climb_geo()
        if geo is None:
            # no climbing frames: the walk cycle turned onto the wall
            ang = -90.0 * mv.side
            return mv.start, [
                {"a": (mv.start, feet), "b": (mv.wall, feet), "ticks": 5, "ang": (0, ang)},
                {"a": (mv.wall, feet), "b": (mv.wall, mv.seg.y), "ang": (ang, ang)},
                {"a": (mv.wall, mv.seg.y), "b": (mv.x, mv.seg.y), "ticks": 5, "ang": (ang, 0)}]
        f = mv.side                                   # it faces the wall
        cw = mv.edge - f * geo["wall"] * s            # its middle while on the wall
        K, d = geo["K"] * s, geo["d"] * s
        top_x = cw + f * geo["dx"] * s                # where the pull-up leaves it
        pull_ticks = max(6, int(geo["pull_n"] / geo["pull_fps"] * 1000 / TICK_MS))
        if up and (mv.seg.low or mv.seg.tight) and "crawl" in self.sheet.anims:
            # somewhere low: up level with it and slide in on its belly (pulling
            # up and standing would put its head through what's above)
            inset = self._body().w * 0.5
            legs = [{"a": (mv.start, feet), "b": (cw, feet), "ticks": 4, "anim": "climb"},
                    {"a": (cw, feet), "b": (cw, mv.seg.y), "anim": "climb", "loop": True},
                    {"a": (cw, mv.seg.y), "b": (mv.edge + f * inset, mv.seg.y), "ticks": 10,
                     "anim": "crawl", "loop": True, "turn": True}]
            return mv.start, legs
        if up:
            legs = [{"a": (mv.start, feet), "b": (cw, feet), "ticks": 4, "anim": "climb"},
                    {"a": (cw, feet), "b": (cw, mv.seg.y + K), "anim": "climb", "loop": True},
                    {"a": (cw, mv.seg.y + K - d), "b": (cw, mv.seg.y + K - d),
                     "ticks": pull_ticks, "anim": "pullup"},
                    {"jump": (top_x, mv.seg.y)}]
            if random.random() < 0.35 and "cling" in self.sheet.anims:
                # a breather halfway up, to look around
                mid = (feet + mv.seg.y + K) / 2
                legs[1:2] = [{"a": (cw, feet), "b": (cw, mid), "anim": "climb", "loop": True},
                             {"a": (cw, mid), "b": (cw, mid), "ticks": random.randint(15, 35),
                              "anim": "cling", "loop": True},
                             {"a": (cw, mid), "b": (cw, mv.seg.y + K), "anim": "climb", "loop": True}]
            return mv.start, legs
        # down: back over the edge, down the wall tail first, hop off
        return top_x, [
            {"a": (cw, feet + K - d), "b": (cw, feet + K - d), "ticks": pull_ticks,
             "anim": "pullup", "rev": True},
            {"a": (cw, feet + K), "b": (cw, mv.seg.y), "anim": "climb", "loop": True, "rev": True},
            {"hop": (mv.x, mv.seg.y)}]

    def _scale_plan(self, mv) -> tuple[float, list]:
        """The legs of a trip by way of walls (perch.Scale): onto a wall
        (grabbing it from beside, or backing over the edge from the top),
        climbing along its outline, leaping across to the next wall, and off
        onto the ledge at the end (pulling up over its edge, sliding in where
        it's low, or a hop)."""
        page = self._page()
        boxes = page.boxes if page else []
        body = self._body()
        s = self._cur_scale()
        geo = self._climb_geo()
        cx, feet = self._feet()
        off = geo["wall"] * s if geo else 0.0
        K = geo["K"] * s if geo else 0.0
        d = geo["d"] * s if geo else 0.0
        pull_ticks = max(6, int(geo["pull_n"] / geo["pull_fps"] * 1000 / TICK_MS)) if geo else 6
        crawl = bool(self.sheet and "crawl" in self.sheet.anims)

        def at(w, y):                                 # its middle on wall w at feet height y
            if geo is None:
                return w.x
            return perch.wall_surface(boxes, w, y, body) - w.side * off

        def path(w, y0, y1):
            if geo is None:
                return [(w.x, y0), (w.x, y1)]
            return [(x - w.side * off, y) for x, y in perch.wall_path(boxes, w, y0, y1, body)]

        legs: list = []
        pos = (mv.start, feet)
        ops = list(mv.ops)
        for i, op in enumerate(ops):
            kind = op[0]
            nxt = ops[i + 1] if i + 1 < len(ops) else None
            if kind == "mount":
                _k, w, y, from_top = op
                ang = -90.0 * w.side if geo is None else 0.0
                if from_top and geo is not None:
                    # back over the edge, tail first: the pull-up played backwards
                    cwp = at(w, y + K)
                    legs.append({"a": (cwp, y + K - d), "b": (cwp, y + K - d), "ticks": pull_ticks,
                                 "anim": "pullup", "rev": True, "face": w.side})
                    pos = (cwp, y + K)
                else:
                    legs.append({"a": pos, "b": (at(w, y), y), "ticks": 4, "anim": "climb",
                                 "face": w.side, "ang": (0.0, ang)})
                    pos = (at(w, y), y)
            elif kind == "leap":
                _k, w, y, lift = op
                b = (at(w, y), y)
                legs.append({"arc": (pos, b, lift), "ticks": max(6, int(abs(b[0] - pos[0]) / 9) + 6),
                             "anim": "jump", "face": 1 if b[0] > pos[0] else -1, "then_face": w.side})
                pos = b
            elif kind == "climb":
                _k, w, y = op
                if nxt is not None and nxt[0] == "pullup" and not (nxt[2].low or nxt[2].tight) and geo:
                    y = y + K                          # up until the front paws reach over the edge
                pts = path(w, pos[1], y)
                pts[0] = pos
                legs.append({"path": pts, "anim": "climb", "loop": True, "rev": y > pos[1],
                             "face": w.side, "ang": (-90.0 * w.side, -90.0 * w.side) if geo is None else None})
                pos = pts[-1]
            elif kind == "pullup":
                _k, w, seg, tx = op
                if (seg.low or seg.tight) and crawl:
                    inset = body.w * 0.5
                    legs.append({"a": pos, "b": (w.edge + w.side * inset, seg.y), "ticks": 10,
                                 "anim": "crawl", "loop": True, "face": w.side})
                elif geo is not None:
                    legs.append({"a": (pos[0], pos[1] - d), "b": (pos[0], pos[1] - d),
                                 "ticks": pull_ticks, "anim": "pullup", "face": w.side})
                    legs.append({"jump": (pos[0] + w.side * geo["dx"] * s, seg.y)})
                else:
                    legs.append({"a": pos, "b": (tx, seg.y), "ticks": 5,
                                 "ang": (-90.0 * w.side, 0.0)})
            elif kind == "hop":
                _k, seg, tx, lift = op
                legs.append({"hop": (tx, seg.y), "lift": lift})
        for leg in legs:
            if leg.get("ang") is None:
                leg.pop("ang", None)
        return mv.start, legs

    def _start_climb(self, mv) -> None:
        """Onto the wall beside the shelf, up (or down) it, and onto the
        ledge at the other end (see perch.climbs)."""
        _start, legs = self._climb_plan(mv)
        if mv.side:
            self.facing = mv.side
        self._climb = {"legs": legs, "leg": 0, "t": 0.0, "mv": mv, "acc": 0.0,
                       "speed": max(2.0, self._body().stand * 0.08)}
        self._perched = False
        self._creep = False
        self._squeeze = False
        self._trans = None
        self.state = "climb"
        self._state_ticks = 0
        self._enter_leg()

    def _enter_leg(self) -> None:
        c = self._climb
        leg = c["legs"][c["leg"]]
        mv = c["mv"]
        if "jump" in leg:                             # the pull-up's last frame: stand there
            x, y = leg["jump"]
            self._climb = None
            self.move(int(round(x - W / 2)), int(round(y - self.foot_offset())))
            self._web_after = replace(mv, kind="hop")
            self._land(perch.support(self._segments(), *self._feet(), tol=8.0))
            return
        if "hop" in leg:                              # off the wall onto the ledge
            x, y = leg["hop"]
            self._climb = None
            self._angle = 0.0
            self._web_after = replace(mv, kind="hop")
            self._start_hop(int(round(x - W / 2)), int(round(y - self.foot_offset())),
                            lift=leg.get("lift", 6))
            return
        c["t"] = 0.0
        if leg.get("face"):
            self.facing = leg["face"]
        if "path" in leg:
            pts = leg["path"]
            leg["_cum"] = [0.0]
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                leg["_cum"].append(leg["_cum"][-1] + math.hypot(x1 - x0, y1 - y0))
            self._place_on(pts[0])
        elif "arc" in leg:
            self._place_on(leg["arc"][0])
        else:
            self._place_on(leg["a"])

    def _place_on(self, pt) -> None:
        self.move(int(round(pt[0] - W / 2)), int(round(pt[1] - self.foot_offset())))

    def _climb_step(self) -> None:
        c = self._climb
        if self.surfaces is not None:
            dy = self.surfaces.take_scroll()          # the wall scrolls too
            if dy:
                for leg in c["legs"]:
                    for k in ("a", "b", "jump", "hop"):
                        if k in leg:
                            leg[k] = (leg[k][0], leg[k][1] + dy)
                    if "path" in leg:
                        leg["path"] = [(x, y + dy) for x, y in leg["path"]]
                    if "arc" in leg:
                        (ax, ay), (bx, by), lift = leg["arc"]
                        leg["arc"] = ((ax, ay + dy), (bx, by + dy), lift)
        if self._page() is None:                      # the page went away: let go
            self._climb = None
            self._angle = 0.0
            self._vy = 0.0
            self.state = "fall"
            return
        leg = c["legs"][c["leg"]]
        if "path" in leg:                             # along the wall's outline
            total = leg["_cum"][-1]
            c["t"] += self._climb_rate() / max(1.0, total)
            t = min(1.0, c["t"])
            want = t * total
            pts, cum = leg["path"], leg["_cum"]
            k = max(0, min(len(pts) - 2, next((i for i in range(1, len(cum)) if cum[i] >= want),
                                              len(cum) - 1) - 1))
            seg_len = max(1e-6, cum[k + 1] - cum[k])
            u = (want - cum[k]) / seg_len
            (x0, y0), (x1, y1) = pts[k], pts[k + 1]
            self._place_on((x0 + (x1 - x0) * u, y0 + (y1 - y0) * u))
        elif "arc" in leg:                            # a leap across to the next wall
            c["t"] += 1.0 / leg["ticks"]
            t = min(1.0, c["t"])
            (ax, ay), (bx, by), lift = leg["arc"]
            self._place_on(perch.hop_point(ax, ay, bx, by, t, lift))
            if t >= 1.0 and leg.get("then_face"):
                self.facing = leg["then_face"]
        else:
            a, b = leg["a"], leg["b"]
            if "ticks" in leg:
                c["t"] += 1.0 / leg["ticks"]
            else:
                dist = abs(b[1] - a[1]) + abs(b[0] - a[0])
                c["t"] += self._climb_rate() / max(1.0, dist)
            t = min(1.0, c["t"])
            self._place_on((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        if "ang" in leg:
            self._angle = leg["ang"][0] + (leg["ang"][1] - leg["ang"][0]) * t
        if t >= 1.0:
            c["leg"] += 1
            if c["leg"] >= len(c["legs"]):
                mv = c["mv"]
                self._climb = None
                self._angle = 0.0
                self._web_after = replace(mv, kind="hop")
                self._land(perch.support(self._segments(), *self._feet(), tol=8.0))
                return
            self._enter_leg()

    def _climb_rate(self) -> float:
        """Screen px per tick up the wall. With climbing frames the paws are
        locked to the wall: the frames play exactly as fast as it climbs."""
        geo = self._climb_geo()
        if geo is None:
            return self._climb["speed"] if self._climb else 2.0
        fps = self._climb_fps(geo)
        return geo["speed"] * self._cur_scale() * fps * TICK_MS / 1000.0

    def _climb_fps(self, geo) -> float:
        # about a body length a second, as fast as the frames can sensibly go
        want = self._body().stand * 1.1
        return max(6.0, min(22.0, want / max(0.1, geo["speed"] * self._cur_scale())))

    def _stay_on_surface(self) -> None:
        """Ride the page as it scrolls; fall when the ledge under us is gone."""
        if not self._perched or self.surfaces is None:
            return
        dy = self._ride_room(self.surfaces.take_scroll())
        if dy:
            self.move(self.x(), int(round(self.y() + dy)))
            if self.state == "walk":
                self.target = QPoint(self.target.x(), int(round(self.target.y() + dy)))
            self._sync_fpos()
        if self._focus:
            return
        cx, feet = self._feet()
        seg = perch.support(self._segments(), cx, feet)
        if seg is not None:
            if abs(seg.y - feet) >= 1:
                self.move(self.x(), int(round(seg.y - self.foot_offset())))
                if self.state == "walk":
                    self.target = QPoint(self.target.x(), self.y())
            return
        # the ledge scrolled away (or under the toolbar), something now sits
        # on top of it, the tab closed or the page lost focus
        self._perched = False
        self._creep = False
        self._squeeze = False
        self._vy = 0.0
        self.state = "fall"
        self._state_ticks = 0

    def _ride_room(self, dy: float) -> float:
        """How far the scrolling page may carry us: never out of its window.
        Past that we let go and stay put, and the text slides on under us."""
        view = self.surfaces.view() if dy else None
        if view is None:
            return dy
        _, feet = self._feet()
        top = view[1] + self._body().stand            # keep our head inside
        bottom = view[1] + view[3]
        if dy < 0:
            return max(dy, min(0.0, top - feet))
        return min(dy, max(0.0, bottom - feet))

    def _air_step(self) -> None:
        if self.state == "hop" and self._hop is not None:
            h = self._hop
            if self.surfaces is not None:
                dy = self.surfaces.take_scroll()      # the landing spot scrolls too
                h["y1"] += dy
            h["t"] = min(1.0, h["t"] + h["dt"])
            x, y = perch.hop_point(h["x0"], h["y0"], h["x1"], h["y1"], h["t"], h["lift"])
            self.move(int(round(x)), int(round(y)))
            if h["t"] >= 1.0:
                self._hop = None
                if self._goal is not None and self._goal.get("stage") == "hop":
                    self._begin_use()
                    return
                if h.get("home"):                     # hopped out of a thing
                    self._exact = False
                    self._land(None)
                    self._play_after_leave()
                    return
                seg = perch.support(self._segments(), *self._feet(), tol=8.0)
                if seg is None and self.y() < self._floor_y() - 2:
                    self._web_after = None            # the ledge went away mid-leap
                    self._vy = 0.0
                    self.state = "fall"
                    return
                self._land(seg)
            return
        # falling: drift gently when there's a ledge below to land on, drop
        # quickly when there isn't
        cx, feet = self._feet()
        segs = self._segments()
        dy = self.surfaces.take_scroll() if self.surfaces is not None else 0.0
        # floating down gently only through open space; text in the way: drop
        below = perch.landing(segs, cx, feet, feet + 2000)
        page = self._page()
        hw = self._body().w / 2
        soft = below is not None and (page is None or not any(
            b.x0 < cx + hw and b.x1 > cx - hw and feet + 4 <= b.y0 < below.y - 4
            for b in page.boxes))                    # (not counting what it stood on)
        g, top = (DRIFT_GRAVITY, DRIFT_MAX) if soft else (GRAVITY, MAX_FALL)
        self._vy = min(top, self._vy + g)
        new_feet = feet + self._vy
        # text scrolling up past us counts as crossing it (page coordinates)
        seg = perch.landing(segs, cx, min(feet, feet + dy), new_feet)
        floor = self._floor_y()
        if seg is not None:
            self.move(self.x(), int(round(seg.y - self.foot_offset())))
            self._land(seg)
        elif self.y() + self._vy >= floor:
            self.move(self.x(), floor)
            self._land(None)
        else:
            self.move(self.x(), int(round(self.y() + self._vy)))

    def _land(self, seg) -> None:
        self._sync_fpos()
        self._vy = 0.0
        self.state = "sit"
        self._state_ticks = 0
        self._next_decision = random.randint(25, 70)
        self._perched = seg is not None
        if seg is not None:
            self.move(self.x(), int(round(seg.y - self.foot_offset())))
            cx, feet = self._feet()
            self.landed.emit(int(cx), int(feet))
            self._recent = (self._recent + [(seg.y, seg.x0, seg.x1, time.monotonic())])[-3:]
            self._page_key = None
            if self._web_after is None and seg.low:
                self._rest("crouch", 0)                 # no room to sit up here
            self._arrive()
            if self._mood == "dig":
                self._next_decision = 5                 # through the hole: keep digging
            elif self.reactions is not None:
                self.reactions.landed(seg)
        else:
            self._web_after = None
            self._mood = ""
            self._set_page_scale(0)                     # off the page: usual size
            if self._goal is not None:
                self._head_to_goal()                    # down from the page: on to the thing

    # ---- interaction -------------------------------------------------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragging = False
            self._press_global = e.globalPosition().toPoint()
            self._press_winpos = self.pos()

    def mouseMoveEvent(self, e) -> None:
        if not self._pressed:
            return
        delta = e.globalPosition().toPoint() - self._press_global
        if not self._dragging and delta.manhattanLength() > DRAG_THRESHOLD:
            self._dragging = True
            self._drop_thing()
            self._leave_surface()
            if self._guarding:
                self.shooed.emit()                # "fine, five minutes"
        if self._dragging:
            self.move(self._press_winpos + delta)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        was_drag = self._dragging
        self._pressed = False
        self._dragging = False
        if was_drag and self._page() is not None:
            # dropped over a page: take on its size and fall onto the text
            # below (or the floor)
            self._set_page_scale(self._fit_page_scale())
            self._mood = "climb" if random.random() < 0.6 else ""   # up we go, mostly
            self._sync_fpos()
            self._vy = 0.0
            self.state = "fall"
            self._state_ticks = 0
        if not was_drag:
            # a click without drag = a pet
            if self.state == "sleep":
                self.state = "sit"
                self._state_ticks = 0
            self.petted.emit()

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.request_chat.emit()

    def contextMenuEvent(self, e) -> None:
        self.request_menu.emit(e.globalPos())

    # ---- drawing -----------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        if self._angle:
            # on a wall: turned about the middle of the body
            cy = self.foot_offset() - self._body().stand / 2
            p.translate(W / 2, cy)
            p.rotate(self._angle)
            p.translate(-W / 2, -cy)

        if self.sheet:
            self._paint_sheet(p)
        else:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            bob = 0
            legphase = 0.0
            if self.state == "walk":
                legphase = self.frame * 0.6
                bob = int(1.5 * (1 + math.sin(self.frame * 0.6)))
            p.save()
            p.translate(0, -bob)
            if self.facing < 0:
                p.translate(W, 0)
                p.scale(-1, 1)
            self._draw_cat(p, legphase)
            p.restore()

        self._draw_emote(p)
        if self._angle:
            p.resetTransform()
        self._draw_meter(p)
        p.end()

    # ---- emote overlay drawing (original art) ------------------------
    def _heart(self, p: QPainter, cx: float, cy: float, s: float, color: QColor):
        path = QPainterPath()
        path.moveTo(cx, cy + s * 0.35)
        path.cubicTo(cx - s, cy - s * 0.4, cx - s * 0.5, cy - s, cx, cy - s * 0.25)
        path.cubicTo(cx + s * 0.5, cy - s, cx + s, cy - s * 0.4, cx, cy + s * 0.35)
        p.fillPath(path, color)

    def _star(self, p: QPainter, cx: float, cy: float, s: float, color: QColor):
        pts = []
        for i in range(10):
            r = s if i % 2 == 0 else s * 0.42
            a = math.pi / 2 + i * math.pi / 5
            pts.append(QPointF(cx + r * math.cos(a), cy - r * math.sin(a)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(QPolygonF(pts))

    def _draw_emote(self, p: QPainter) -> None:
        if not self._emote:
            return
        t = (self.frame - self._emote_start) / self._emote_frames
        if t >= 1.0:
            self._emote = None
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx = W // 2
        top = 24
        kind = self._emote
        if kind == "love":
            for dx, ph in ((-16, 0.0), (2, 0.3), (16, 0.6)):
                tt = max(0.0, min(1.0, (t - ph * 0.4) * 1.5))
                if tt <= 0.0 or tt >= 1.0:
                    continue
                a = int(230 * (1 - tt))
                self._heart(p, cx + dx, top - 30 * tt, 8, QColor(233, 80, 110, a))
            return
        alpha = int(230 * (1 - t))
        rise = int(30 * t)
        if kind == "zzz":                    # sleepy "z z z" drifting up
            f = QFont()
            f.setBold(True)
            p.setPen(QColor(120, 120, 150, alpha))
            for dx, dl, sz in ((6, 0.0, 11), (14, 0.25, 14), (24, 0.5, 17)):
                a = int(230 * max(0.0, 1 - (t + dl)))
                if a <= 0:
                    continue
                f.setPointSize(sz)
                p.setFont(f)
                p.setPen(QColor(120, 120, 150, a))
                p.drawText(QRect(cx + dx, top - rise - 6, 24, 24),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           "z")
            return
        if kind == "spark":
            for dx, dl in ((-14, 0.0), (0, 0.2), (13, 0.4)):
                a = int(230 * max(0.0, 1 - (t + dl)))
                if a > 0:
                    self._star(p, cx + dx, top - rise, 7, QColor(255, 205, 70, a))
            return
        sym = {"music": "♪", "question": "?", "excited": "!"}.get(kind, "!")
        col = {"music": QColor(120, 160, 240, alpha),
               "question": QColor(150, 150, 160, alpha)}.get(
                   kind, QColor(240, 90, 90, alpha))
        f = QFont()
        f.setPointSize(17)
        f.setBold(True)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRect(0, top - rise - 12, W, 26),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                   sym)

    def _paint_sheet(self, p: QPainter) -> None:
        name, fi = self._shown()
        frames = self.sheet.frames(name, self.facing) if name else []
        if not frames:
            return
        pix = frames[fi % len(frames)]
        x, y, tw, th = self._sprite_box()
        # crisp, nearest-neighbour scaling; mirror when facing left (unless
        # the pet ships frames drawn for that side)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        spot = self._thing["spot"] if self._thing is not None else None
        if spot is not None and spot.back is not None:
            p.drawPixmap(spot.pos - self.pos(), spot.back)
        p.save()
        if self.sheet.mirrored(name, self.facing):
            p.translate(x + tw, y)
            p.scale(-1, 1)
            p.drawPixmap(0, 0, tw, th, pix)
        else:
            p.drawPixmap(x, y, tw, th, pix)
        p.restore()
        if spot is not None and spot.front is not None:
            p.drawPixmap(spot.pos - self.pos(), spot.front)
        if self._carry is not None:
            an = self.sheet.anchor(name, fi, self.facing)
            if an and an.get("mouth"):
                from .things.kinds.toy import held_at
                c = self._carry
                s = tw / pix.width()
                tx, ty = held_at(c["toy"], an["mouth"], self.facing)
                pm = c["pm"][1 if self.facing > 0 else -1]
                if pm is not None:
                    p.drawPixmap(int(x + tx * s), int(y + ty * s), pm)

    def _draw_cat(self, p: QPainter, legphase: float) -> None:
        base = self.base
        outline = _darken(base, 0.45)
        belly = _lighten(base, 0.55)
        stripe = _darken(base, 0.18)
        pink = QColor(233, 150, 160)
        sleeping = self.state == "sleep"

        pen = QPen(outline, 2.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)

        # ---- tail (behind body) ----
        tail_swish = math.sin(self.frame * 0.12) * 10
        if sleeping:
            tail_swish = 6
        tail = QPainterPath()
        tail.moveTo(34, BASELINE - 22)
        tail.cubicTo(14, BASELINE - 30,
                     10 + tail_swish, BASELINE - 58 - tail_swish,
                     26 + tail_swish, BASELINE - 66 - tail_swish)
        tp = QPen(outline, 9.0)
        tp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(tp)
        p.drawPath(tail)
        tp2 = QPen(base, 6.0)
        tp2.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(tp2)
        p.drawPath(tail)
        p.setPen(pen)

        # ---- legs ----
        p.setBrush(QBrush(base))
        for i, lx in enumerate((46, 58, 82, 94)):
            off = 0
            if self.state == "walk":
                off = int(2.5 * math.sin(legphase + i * 1.4))
            p.drawRoundedRect(lx + off, BASELINE - 14, 11, 16, 5, 5)

        # ---- body ----
        body = QRect(28, BASELINE - 44, 66, 44)
        p.setBrush(QBrush(base))
        p.drawRoundedRect(body, 22, 22)
        # belly patch
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(belly))
        p.drawEllipse(QRect(52, BASELINE - 30, 40, 28))
        # stripes
        p.setPen(QPen(stripe, 3.0))
        for sx in (44, 54, 64):
            p.drawArc(sx, BASELINE - 46, 16, 20, 30 * 16, 120 * 16)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, 22, 22)

        # ---- head ----
        hx, hy, hr = 90, BASELINE - 58, 22
        # ears
        p.setBrush(QBrush(base))
        left_ear = QPolygonF([QPointF(hx - 16, hy - 12), QPointF(hx - 22, hy - 34),
                              QPointF(hx - 4, hy - 20)])
        right_ear = QPolygonF([QPointF(hx + 4, hy - 20), QPointF(hx + 18, hy - 34),
                               QPointF(hx + 20, hy - 10)])
        p.drawPolygon(left_ear)
        p.drawPolygon(right_ear)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(pink))
        p.drawPolygon(QPolygonF([QPointF(hx - 15, hy - 15), QPointF(hx - 18, hy - 28),
                                 QPointF(hx - 8, hy - 20)]))
        p.drawPolygon(QPolygonF([QPointF(hx + 6, hy - 19), QPointF(hx + 15, hy - 28),
                                 QPointF(hx + 16, hy - 14)]))
        p.setPen(pen)
        p.setBrush(QBrush(base))
        p.drawEllipse(QPoint(hx, hy), hr, hr - 2)

        # ---- face ----
        eye_y = hy - 2
        if sleeping or self.blink > 0.5:
            p.setPen(QPen(outline, 2.0))
            p.drawArc(hx - 13, eye_y - 4, 10, 8, 0, -180 * 16)
            p.drawArc(hx + 3, eye_y - 4, 10, 8, 0, -180 * 16)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(40, 40, 45))
            p.drawEllipse(QPoint(hx - 8, eye_y), 3, 4)
            p.drawEllipse(QPoint(hx + 8, eye_y), 3, 4)
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(QPoint(hx - 7, eye_y - 1), 1, 1)
            p.drawEllipse(QPoint(hx + 9, eye_y - 1), 1, 1)
        # nose + mouth
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(pink))
        p.drawPolygon(QPolygonF([QPointF(hx - 3, hy + 6), QPointF(hx + 3, hy + 6),
                                 QPointF(hx, hy + 9)]))
        p.setPen(QPen(outline, 1.4))
        p.drawArc(hx - 6, hy + 8, 6, 5, 0, -160 * 16)
        p.drawArc(hx, hy + 8, 6, 5, -20 * 16, -160 * 16)
        # whiskers
        p.setPen(QPen(outline, 1.0))
        for wy in (hy + 3, hy + 8):
            p.drawLine(hx + 6, wy, hx + 24, wy - 2)
        p.drawLine(hx - 6, hy + 5, hx - 22, hy + 3)

        # ---- Zzz when sleeping ----
        if sleeping:
            p.setPen(QColor(120, 120, 140))
            f = QFont()
            f.setPointSize(9)
            f.setBold(True)
            p.setFont(f)
            wobble = int(math.sin(self.frame * 0.15) * 2)
            p.drawText(hx + 18 + wobble, hy - 26, "z")
            f.setPointSize(11)
            p.setFont(f)
            p.drawText(hx + 24 - wobble, hy - 34, "Z")
