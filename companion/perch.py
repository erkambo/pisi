"""Things on the screen the pet can stand on.

Web pages, reported by the PISI browser extension through :mod:`bridge`:
lines of text, pictures, buttons and fields, as boxes in global screen
coordinates (the units the pet's window moves in). Pure Python, so the pet's
physics can be tested without a browser or a display.

The page is a little world of solid boxes, like shelves in a room. The pet
can't stand *inside* a paragraph: a line only makes a ledge where there's room
above it for the pet's body, standing or crouched (:func:`ledges`). So it
stands on top of a paragraph, beside a short last line, on a heading with
space around it, on a picture, a button or the search box, and on top of the
browser window itself; it creeps through gaps that are only crouching-high,
and its leaps arc around text instead of through it (:func:`arc_clear`).

:func:`plan` is the pet's idea of play on that world: explore a shelf end to
end, hop over a button to the next one, climb ledge by ledge towards the top
of the screen and nap there (or on the search box), nap on a picture, watch a
video from on top of it, sit on a heading and look around.

A *segment* (:class:`Seg`) is a stretch where the pet's middle can be while
its feet rest on an edge. The extension never sends the words; lines come from
the browser tab you're looking at (the one that last reported focus) and go
stale a few seconds after that page stops reporting.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace
from statistics import median
from typing import TYPE_CHECKING
from collections.abc import Callable

if TYPE_CHECKING:
    from pathlib import Path


TEXT_KINDS = ("p", "h", "li", "quote", "code", "cell")
MEDIA_KINDS = ("img", "video")
INF = float("inf")


@dataclass(frozen=True)
class Seg:
    x0: float
    x1: float
    y: float                     # the edge the feet rest on
    kind: str = "p"              # p, h, li, quote, code, cell, img, video
    block: int = -1              # which paragraph / heading / picture (top to bottom)
    row: int = 0                 # line number inside its block
    rows: int = 1                # lines the block has on screen
    room: float = INF            # free height above the edge here
    low: bool = False            # only crouching-high: creep, don't stand
    tight: bool = False          # only crawling-high: squeeze through, don't stay

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    def holds(self, x: float, slack: float = 6.0) -> bool:
        return self.x0 - slack <= x <= self.x1 + slack


@dataclass(frozen=True)
class Box:
    """Something solid on the page: a line of text, a picture, a button..."""
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str = "p"
    block: int = -1

    @property
    def edge(self) -> float:
        """Where feet rest on top: on the letters, not the line box above them."""
        return self.y0 + round((self.y1 - self.y0) * 0.12) if self.kind in TEXT_KINDS else self.y0


@dataclass(frozen=True)
class Body:
    """The pet's size on screen (from its sprite), for fitting under things."""
    w: float = 90.0              # width that must fit under a ceiling
    stand: float = 87.0          # height standing / walking
    crouch: float = 66.0         # height crouched, creeping
    sit: float = 78.0            # height sitting
    crawl: float = 0.0           # height flattened, squeezing through (0: can't)

    def scaled(self, k: float) -> Body:
        return Body(self.w * k, self.stand * k, self.crouch * k, self.sit * k, self.crawl * k)

    @property
    def lowest(self) -> float:
        return self.crawl if 0 < self.crawl < self.crouch else self.crouch

    @property
    def max_rise(self) -> float:          # how high a leap can go up
        return self.stand * 1.8

    @property
    def reach(self) -> float:             # how far a leap can go sideways
        return self.stand * 3.5

    @property
    def max_drop(self) -> float:
        return self.stand * 9.0


ZOOMS = (0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5,
         3.0, 4.0, 5.0)


@dataclass(frozen=True)
class PageMap:
    """Page (CSS) pixels -> the pet's screen units: (ax + x * s, ay + y * s)."""
    ax: float
    ay: float
    s: float
    win: tuple | None = None     # the browser window, in the pet's units
    zoom: float = 1.0
    exact: bool = False          # placed with the help of the mouse

    def rect(self, x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
        return self.ax + x * self.s, self.ay + y * self.s, w * self.s, h * self.s


def browser_map(geo: dict, screens: list[tuple]) -> PageMap | None:
    """Where a page sits on the real screens, from the browser's own numbers.

    ``screens`` are the desktop's screens as (x, y, w, h, pixel ratio) in the
    pet's units. Browsers and the desktop can disagree about everything: a
    browser may scale each monitor differently (Brave on X11 called a 4K
    monitor 2560 wide at 1.5x and a laptop 1680 wide at 1.83x, where Qt said
    1920 and 1536, both at 2x), number screens from 0 each, and report mouse
    positions in yet other units. So: find the screen whose shape matches the
    one the browser says it's on, get the browser's scale there from the
    screen's real pixels, the page zoom from the browser's pixel ratio, and
    place the page in its window (toolbars on top, side panels split) unless a
    mouse position over the page says exactly where it is."""
    try:
        sw, sh = (float(v) for v in geo["screen"][:2])
        wx, wy, ow, oh = (float(v) for v in geo["win"][:4])
        iw, ih = (float(v) for v in geo["inner"][:2])
        dpr = float(geo.get("dpr") or 1.0)
        left, top = float(geo.get("left") or 0), float(geo.get("top") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if sw <= 0 or sh <= 0 or iw <= 0 or ih <= 0:
        return None
    best = None
    for gx, gy, gw, gh, qd in screens or [(0.0, 0.0, sw, sh, dpr)]:
        rw, rh = gw / sw, gh / sh
        if abs(rw - rh) > 0.03 * rw:
            continue                          # not this screen's shape
        dsf = gw * qd / sw                    # browser's real pixels per its own unit
        z = dpr / dsf
        snap = min(ZOOMS, key=lambda v: abs(v - z))
        err = abs(snap - z) / snap
        where = abs(gx - left * rw) + abs(gy - top * rh)
        cand = (err > 0.04, where, err, gx, gy, rw, dsf, snap if err <= 0.04 else z)
        if best is None or cand[:3] < best[:3]:
            best = cand
    if best is None and screens:
        # no screen has the shape the browser gave: Brave's fingerprinting
        # protection makes screen sizes up (2560x1440 on a 16:10 laptop). Its
        # pixel ratio is real, so use that as its scale (the page zoom can't
        # be told apart then: take 100%), on the screen its window is on; the
        # screen check fine-tunes the rest.
        def holds(sc):
            gx, gy, gw, gh, qd = sc
            k = dpr / qd
            mx, my = (wx - left + ow / 2) * k, (wy - top + oh / 2) * k
            return 0 <= mx - gx < gw and 0 <= my - gy < gh
        gx, gy, gw, gh, qd = next((sc for sc in screens if holds(sc)), screens[0])
        best = (True, 0.0, 0.0, gx, gy, dpr / qd, dpr, 1.0)
    if best is None:
        return None
    *_, gx, gy, k, dsf, z = best
    # the window, relative to its screen, then in our units
    qx, qy = gx + (wx - left) * k, gy + (wy - top) * k
    # the page inside the window, in browser units
    spare_w, spare_h = max(0.0, ow - iw * z), max(0.0, oh - ih * z)
    dx, dy, exact = spare_w / 2, spare_h, False
    moz = geo.get("moz")
    mouse = geo.get("mouse")
    if moz:
        try:
            dx, dy, exact = float(moz[0]) - wx, float(moz[1]) - wy, True
        except (TypeError, ValueError, IndexError):
            pass
    elif mouse and USE_MOUSE:
        try:
            msx, msy, mcx, mcy = (float(v) for v in mouse[:4])
        except (TypeError, ValueError):
            msx = None
        # mouse screen positions come in the browser's units or in real
        # pixels, depending on the browser: take whichever fits the window
        for unit in ((1.0, dsf) if msx is not None else ()):
            cdx, cdy = msx / unit - wx - mcx * z, msy / unit - wy - mcy * z
            if -2 <= cdx <= spare_w + 2 and -2 <= cdy <= spare_h + 2:
                dx, dy, exact = cdx, cdy, True
                break
    return PageMap(qx + dx * k, qy + dy * k, z * k, (qx, qy, ow * k, oh * k), z, exact)


# Placing the page from a mouse position over it: Brave on X11 (2x desktop)
# reports mouse positions in other units than its window, and accepting one
# now and then made the page jump; the screen check places it instead.
USE_MOUSE = False

STALE_S = 3.0                    # no word from the page for this long -> gone
FOCUS_GRACE_S = 15.0             # a page you were just reading stays playable this long
                                 # after you click into another app (while it's visible)
HEARTBEAT_S = 1.5                # how often a quiet page still reports
SUPPORT_TOL = 4.0                # feet within this many px of an edge = standing on it


class WebSurfaces:
    """Text lines from the browser extension, per tab, newest focused tab wins."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 scale_for: Callable[[float, float], float] | None = None,
                 screens: Callable[[], list[tuple]] | None = None,
                 memory: Path | None = None) -> None:
        self._clock = clock
        # browser screen units -> the pet's units. A browser may ignore the
        # desktop's display scaling (and zoom pages instead), so it can call a
        # 3072-px-wide screen what the desktop calls 1536: the app works out
        # the factor from the browser's reported screen size.
        self._scale_for = scale_for or (lambda w, h: 1.0)
        # ... or, from extensions that send the browser's own numbers ("geo"),
        # a full placement on the real screens (see browser_map)
        self._screens = screens or (lambda: [])
        self.scale = 1.0
        self._map = PageMap(0.0, 0.0, 1.0)
        self._win_fix: dict[tuple, tuple[float, float]] = {}   # window -> found correction
        # ...remembered across restarts (a file), so a restart doesn't leave
        # the page under the toolbar until it's found again
        self._memory = memory
        self._win_fix.update(self._load_memory())
        self._tabs: dict[tuple, dict] = {}
        self._active: tuple | None = None
        self._pending_dy = 0.0
        self.version = 0             # bumps whenever what the pet sees may change
        self._sig = None
        self._verify_soon = False
        self._events: list[str] = []         # "closed", "secret": for the pet to react to
        self._scrolls: list[tuple[float, float]] = []   # (when, screen px) on the active page
        self.guards_any: bool | None = None  # you've asked it to guard some site (None: not told)

    def feed(self, msg: dict) -> None:
        kind = msg.get("type")
        key = (msg.get("conn"), msg.get("tab"))
        if kind == "host-gone":
            for k in [k for k in self._tabs if k[0] == msg.get("conn")]:
                self._forget(k)
            return
        if kind == "gone":
            why = msg.get("why")
            if why == "secret" or (why == "closed" and key == self._active):
                self._events.append(why)
            self._forget(key)
            return
        if kind != "lines":
            return
        now = self._clock()
        geo = msg.get("geo")
        pm = browser_map(geo, self._screens()) if isinstance(geo, dict) else None
        if pm is None:
            # older messages: lines already in the browser's screen units
            try:
                sw, sh = (float(v) for v in (msg.get("screen") or [0, 0])[:2])
                k = self._scale_for(sw, sh) if sw > 0 and sh > 0 else 1.0
            except (TypeError, ValueError):
                k = 1.0
            try:
                win = msg.get("win")
                win = tuple(float(v) * k for v in win[:4]) if win else None
            except (TypeError, ValueError):
                win = None
            pm = PageMap(0.0, 0.0, k, win, float(msg.get("zoom") or 1.0), bool(msg.get("exact")))
            view = msg.get("view")
            try:
                view = pm.rect(*(float(v) for v in view[:4])) if view else None
            except (TypeError, ValueError):
                view = None
        else:
            view = pm.rect(0, 0, *(float(v) for v in geo["inner"][:2]))
        k = pm.s
        kinds = msg.get("kinds") or []
        raw = []
        for r in msg.get("lines") or []:
            try:
                x, y, w, h = pm.rect(*(float(v) for v in r[:4]))
                b = int(r[4]) if len(r) > 4 else -1
            except (TypeError, ValueError):
                continue
            if w > 0 and h > 0:
                kind = kinds[b] if 0 <= b < len(kinds) and isinstance(kinds[b], str) else "p"
                box = Box(x, y, x + w, y + h, kind, b)
                raw.append((b, x, x + w, box.edge, kind, y, h, box))
        counts: dict[int, int] = {}
        for b, *_ in raw:
            counts[b] = counts.get(b, 0) + 1
        seen: dict[int, int] = {}
        segs = []
        boxes = []
        solids = []
        for b, x0, x1, top, kind, y, h, box in raw:    # rows arrive top to bottom per block
            row = seen.get(b, 0)
            seen[b] = row + 1
            segs.append(Seg(x0, x1, top, kind, b, row, counts[b]))
            solids.append(box)
            if kind in TEXT_KINDS:
                boxes.append((x0, y, x1 - x0, h))
        win = pm.win
        if view is not None and solids:
            # text is only reported where it's visible, so the page reaches at
            # least that far down, whatever the browser says (Brave's page
            # height is off whenever one of its bars shows or hides)
            low = max(b.y1 for b in solids)
            if low > view[1] + view[3]:
                view = (view[0], view[1], view[2], low - view[1] + 2)
        scroll = msg.get("scroll") or [0, 0]
        try:
            sy = float(scroll[1]) * k
        except (TypeError, ValueError, IndexError):
            sy = 0.0
        prev = self._tabs.get(key)
        # a screen-checked correction belongs to the browser *window* (it's the
        # toolbars the browser didn't tell us about): it holds through zooming
        # and scrolling, and other tabs in the same window share it, until
        # the window moves or resizes
        # (Brave scales even its window numbers with the page zoom, so the
        # window is known only by its screen; a correction that stops
        # matching the screen is dropped by the screen check: see unlocate)
        wkey = (round(pm.ax / 200), ) if pm.win is None else self._screen_key(pm)
        basis = (wkey, pm.exact)
        same = (prev or {}).get("basis") == basis
        known = self._win_fix.get(basis) if not pm.exact else None
        if known is not None and not same:
            self._verify_soon = True                  # a remembered place: check it
        if same:
            fix = prev["fix"]
        elif known is not None:
            fix = known
        else:
            fix = (0.0, 0.0)
        if prev is not None and key == self._active:
            # the page scrolled: the text under the pet moved by -dy on screen
            self._pending_dy -= sy - prev["sy"]
            if sy != prev["sy"]:
                self._scrolls = [s for s in self._scrolls if now - s[0] < SCROLL_MEMORY_S]
                self._scrolls.append((now, sy - prev["sy"]))
        if "guards" in msg:
            self.guards_any = bool(msg.get("guards"))
        focused = bool(msg.get("focused"))
        meta = {"geo": geo, "map": [round(pm.ax, 1), round(pm.ay, 1), round(pm.s, 4)],
                "zoom": pm.zoom, "exact": pm.exact}
        self._tabs[key] = {"meta": meta, "map": pm,
                           "located": bool((same and prev.get("located")) or known is not None), "segs": segs, "boxes": boxes, "solids": solids, "win": win,
                           "sy": sy, "seen": now, "view": view,
                           "guard": bool(msg.get("guard")),     # a site you'd rather avoid
                           "page": _going_on(msg, pm),
                           "basis": basis, "fix": fix,
                           "pending_fix": (prev or {}).get("pending_fix")
                           if (prev or {}).get("basis") == basis else None,
                           "focused_at": now if focused else (prev or {}).get("focused_at", -1e9)}
        if focused:
            self._tabs[key]["covered"] = False        # you're looking at it again
        elif prev is not None:
            self._tabs[key]["covered"] = prev.get("covered", False)
            self._tabs[key]["seen_on_screen"] = prev.get("seen_on_screen", False)
        if focused and key != self._active:
            self._active = key
            self._pending_dy = 0.0
            self._scrolls = []
        if key == self._active:
            self.scale = k
            self._map = pm
            # a "still here" heartbeat with nothing new doesn't make the pet
            # rethink the page
            sig = (tuple(solids), view, win, sy, self._tabs[key]["fix"])
            if sig != self._sig:
                self._sig = sig
                self.version += 1

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        """A point on the active page (page px) -> the pet's units."""
        pm = self._map
        dx, dy = self.correction
        return pm.ax + x * pm.s + dx, pm.ay + y * pm.s + dy

    def to_browser(self, x: float, y: float) -> tuple[int, int]:
        """A point in the pet's units -> the active page's coordinates (or,
        from older extensions, the browser's screen units)."""
        pm = self._map
        dx, dy = self.correction
        return round((x - dx - pm.ax) / pm.s), round((y - dy - pm.ay) / pm.s)

    def _forget(self, key: tuple) -> None:
        self._tabs.pop(key, None)
        self.version += 1
        if key == self._active:
            self._active = None
            self._pending_dy = 0.0

    def _live(self) -> dict | None:
        t = self._tabs.get(self._active) if self._active is not None else None
        if t is None:
            return None
        now = self._clock()
        if now - t["seen"] > STALE_S:
            return None
        # a page you've switched away from stays as long as it's still to be
        # seen on screen (the screen check says when it's covered); if
        # nothing checks, it lasts a grace period
        if now - t["focused_at"] > FOCUS_GRACE_S + HEARTBEAT_S and not t.get("seen_on_screen"):
            return None
        if t.get("covered"):
            return None
        return t

    @property
    def focus_age(self) -> float:
        t = self._tabs.get(self._active) if self._active is not None else None
        return self._clock() - t["focused_at"] if t else 1e9

    def set_covered(self, covered: bool) -> None:
        """The screen check's verdict on the active page while you're in
        another window: covered (the pet leaves) or still in view (it stays)."""
        t = self._tabs.get(self._active) if self._active is not None else None
        if t is None:
            return
        if t.get("covered") != covered:
            self.version += 1
        t["covered"] = covered
        t["seen_on_screen"] = not covered

    @property
    def active(self) -> bool:
        return self._live() is not None

    def going_on(self) -> dict:
        """What's happening on the page in front (see _going_on), with its
        rectangles on screen; {} when there's no page."""
        t = self._live()
        if not t:
            return {}
        dx, dy = t["fix"]
        out = dict(t.get("page") or {})
        for k in RECT_SIGNALS:
            if out.get(k):
                x, y, w, h = out[k]
                out[k] = (x + dx, y + dy, w, h)
        return out

    def take_events(self) -> list[str]:
        """Things that just happened to pages ("closed": the page in front
        was closed, "secret": you opened a login or payment page)."""
        ev, self._events = self._events, []
        return ev

    def scrolls(self, within: float) -> list[tuple[float, float]]:
        """The active page's recent scrolls: (seconds ago, screen px)."""
        now = self._clock()
        return [(now - t, dy) for t, dy in self._scrolls if now - t <= within]

    def zoom(self) -> float:
        return self._map.zoom

    def guarded(self) -> bool:
        """The page in front of you is one of the distracting sites you asked
        PISI to guard (the extension decides; PISI never sees the address)."""
        t = self._live()
        return bool(t and t.get("guard"))

    def segments(self) -> list[Seg]:
        t = self._live()
        if not t:
            return []
        dx, dy = t["fix"]
        if not dx and not dy:
            return list(t["segs"])
        return [Seg(s.x0 + dx, s.x1 + dx, s.y + dy, s.kind, s.block, s.row, s.rows)
                for s in t["segs"]]

    def boxes(self) -> list[Box]:
        """Everything solid on the active page: lines, pictures, buttons, fields."""
        t = self._live()
        if not t:
            return []
        dx, dy = t["fix"]
        if not dx and not dy:
            return list(t["solids"])
        return [Box(b.x0 + dx, b.y0 + dy, b.x1 + dx, b.y1 + dy, b.kind, b.block)
                for b in t["solids"]]

    def window(self) -> tuple[float, float, float, float] | None:
        """The browser window around the active page (x, y, w, h), if known."""
        t = self._live()
        return t["win"] if t else None

    def metrics(self) -> tuple[float, float]:
        """(line height, gap between paragraphs) on the active page."""
        t = self._live()
        if not t:
            return 0.0, 0.0
        if t.get("metrics") is None:
            t["metrics"] = metrics(t["solids"])
        return t["metrics"]

    def text_boxes(self) -> list[tuple[float, float, float, float]]:
        """The active page's text line boxes as reported, before any correction."""
        t = self._live()
        return list(t["boxes"]) if t else []

    def nudge(self, dx: float, dy: float) -> None:
        """A screen check found the text (dx, dy) from where we had it. Applied
        once two checks in a row agree, so one odd grab can't move it."""
        t = self._live()
        if t is None:
            return
        if not dx and not dy:
            t["pending_fix"] = None
            return
        p = t.get("pending_fix")
        if p is not None and abs(p[0] - dx) <= 4 and abs(p[1] - dy) <= 4:
            fx, fy = t["fix"]
            t["fix"] = (fx + (p[0] + dx) / 2, fy + (p[1] + dy) / 2)
            t["pending_fix"] = None
            if t.get("located"):
                self._win_fix[t["basis"]] = t["fix"]
            self.version += 1
            return
        t["pending_fix"] = (dx, dy)

    def _screen_key(self, pm: PageMap) -> tuple:
        cx, cy = pm.win[0] + pm.win[2] / 2, pm.win[1] + pm.win[3] / 2
        for x, y, w, h, _d in self._screens() or []:
            if x <= cx < x + w and y <= cy < y + h:
                return (x, y)
        return (round(pm.win[0] / 400), round(pm.win[1] / 400))

    def window_fix(self, windows: list[tuple], screens: list[tuple] | None = None
                   ) -> tuple[float, float] | None:
        """The active page's correction from the browser windows' real places
        (``windows``: (x, y, w, h) in real pixels, see xwin): the window as
        wide as the page whose bottom the page runs to. None: can't tell
        (no such window, or more than one that fit)."""
        from . import xwin
        t = self._live()
        if not t or not isinstance((t.get("meta") or {}).get("geo"), dict):
            return None
        pm = t["map"]
        try:
            iw, ih = (float(v) for v in t["meta"]["geo"]["inner"][:2])
        except (KeyError, TypeError, ValueError):
            return None
        pw, ph = iw * pm.s, ih * pm.s                    # the page, in our units
        fits = []
        for x, y, w, h in windows:
            lg = xwin.to_logical(x, y, w, h, screens if screens is not None else self._screens())
            if lg is None:
                continue
            lx, ly, lw, lh = lg
            if abs(lw - pw) <= 24 and lh >= ph - 2 and lx <= pm.ax + 400 and lx + lw >= pm.ax - 400:
                fits.append(lg)
        if len(fits) != 1:
            return None
        lx, ly, lw, lh = fits[0]
        return (lx + (lw - pw) / 2 - pm.ax, ly + lh - ph - pm.ay)

    def prior(self) -> tuple[float, float] | None:
        """The place found before for the active page's screen, if any."""
        t = self._live()
        return self._win_fix.get(t["basis"]) if t else None

    def take_verify_soon(self) -> bool:
        v, self._verify_soon = self._verify_soon, False
        return v

    def _load_memory(self) -> dict:
        import json
        if self._memory is None:
            return {}
        try:
            raw = json.loads(self._memory.read_text("utf-8"))
            return {(tuple(v["screen"]), bool(v["exact"])): (float(v["dx"]), float(v["dy"]))
                    for v in raw.get("places", [])}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _save_memory(self) -> None:
        import json
        if self._memory is None:
            return
        places = [{"screen": list(k[0]), "exact": k[1], "dx": v[0], "dy": v[1]}
                  for k, v in self._win_fix.items()]
        try:
            self._memory.write_text(json.dumps({"places": places}), "utf-8")
        except OSError:
            pass

    def unlocate(self) -> None:
        """The correction no longer matches what's on screen (the window
        moved, a bar appeared): forget it and look again."""
        t = self._live()
        if t is None:
            return
        self._win_fix.pop(t["basis"], None)
        t["fix"] = (0.0, 0.0)
        t["located"] = False
        t["pending_fix"] = None
        self.version += 1

    def place(self, dx: float, dy: float) -> None:
        """A look at the whole page on screen found exactly where it is:
        browsers don't always say (Brave on X11 hides its toolbar height)."""
        t = self._live()
        if t is None:
            return
        t["fix"] = (dx, dy)
        t["pending_fix"] = None
        t["located"] = True
        self._win_fix[t["basis"]] = (dx, dy)
        self._save_memory()
        self.version += 1

    @property
    def located(self) -> bool:
        """Whether the active page's place on screen has been checked whole."""
        t = self._live()
        return bool(t and (t.get("located") or t["map"].exact))

    @property
    def correction(self) -> tuple[float, float]:
        t = self._live()
        return t["fix"] if t else (0.0, 0.0)

    def view(self) -> tuple[float, float, float, float] | None:
        """The visible page area on screen (x, y, w, h), if known."""
        t = self._live()
        if not t or t["view"] is None:
            return None
        x, y, w, h = t["view"]
        dx, dy = t["fix"]
        return (x + dx, y + dy, w, h)

    def take_scroll(self) -> float:
        """Screen px the active page's text moved since last asked (riding)."""
        dy, self._pending_dy = self._pending_dy, 0.0
        return dy if self.active else 0.0


SCROLL_MEMORY_S = 240.0
RECT_SIGNALS = ("sel", "video", "typing")


def _going_on(msg: dict, pm: PageMap) -> dict:
    """The page's signals (extension 0.3+), rectangles in the pet's units:
    sel (your selection), video (the biggest started video) with playing
    ("playing" / "paused" / "ended"), music, typing (the field you're typing
    in), end (scrolled to the bottom), offline, mess (knocking words off and
    digging allowed)."""
    out: dict = {}
    for k in RECT_SIGNALS:
        r = msg.get(k)
        try:
            out[k] = pm.rect(*(float(v) for v in r[:4])) if r else None
        except (TypeError, ValueError):
            out[k] = None
    out["playing"] = msg.get("playing") if msg.get("playing") in ("playing", "paused", "ended") else None
    for k in ("music", "end", "offline"):
        out[k] = bool(msg.get(k))
    out["mess"] = bool(msg.get("mess"))
    return out


# ---- the page's size, and the pet's ---------------------------------------------
def metrics(boxes: list[Box]) -> tuple[float, float]:
    """(typical line height, typical gap between paragraphs) of a page's
    text, 0 when there's none."""
    text = sorted((b for b in boxes if b.kind in TEXT_KINDS), key=lambda b: b.y0)
    if not text:
        return 0.0, 0.0
    line_h = median(b.y1 - b.y0 for b in text)
    gaps = []
    for i, a in enumerate(text):
        for b in text[i + 1:]:
            if b.y0 - a.y1 > line_h * 4:
                break
            if b.block == a.block and b.y0 >= a.y1 - 1 and min(a.x1, b.x1) > max(a.x0, b.x0):
                break                         # not the bottom line of its block
            if b.block != a.block and b.y0 >= a.y1 - 1 and min(a.x1, b.x1) - max(a.x0, b.x0) > 30:
                gaps.append((b.y0 - a.y1, a.kind == b.kind == "p"))
                break
    paras = sorted(g for g, p in gaps if p)
    if len(paras) >= 3:                       # between paragraphs
        return float(line_h), float(median(paras))
    if not gaps:
        return float(line_h), line_h * 1.3
    # no paragraphs to speak of: the roomier gaps (not between list items)
    rest = sorted(g for g, _ in gaps)
    return float(line_h), float(rest[(len(rest) * 3) // 4])


def fit_scale(unit: Body, line_h: float, gap: float, options: list[float]) -> float:
    """The biggest drawing scale (of ``options``) at which the pet can creep
    between two paragraphs and isn't more than a few lines tall."""
    if line_h <= 0 or not options:
        return max(options) if options else 1.0
    room = max(gap, line_h)
    ok = [s for s in options if unit.crouch * s <= room * 1.05
          and line_h * 1.2 <= unit.stand * s <= line_h * 2.6]
    if ok:
        return max(ok)
    # nothing fits between the lines: still no smaller than a line and a bit
    big_enough = [s for s in options if unit.stand * s >= line_h * 1.2]
    return min(big_enough) if big_enough else max(options)


# ---- where the pet fits -----------------------------------------------------------
def ledges(boxes: list[Box], body: Body, view: tuple | None = None, ceiling: float = -INF,
           win: tuple | None = None) -> list[Seg]:
    """Where the pet can be on the page: stretches of top edges with room
    above for its body, standing or (``low``) crouched. A line inside a
    paragraph has the line above it a few pixels over its head, so it isn't
    one; the top of a paragraph after a gap, the space beside a short last
    line, a picture, a button, the search box... are. ``view`` keeps it inside
    the visible page; ``ceiling`` is the top of the screen; ``win`` (the
    browser window) adds its top edge, the highest shelf there is."""
    half = body.w / 2
    if view is not None:
        vx0, vy0, vx1, vy1 = view[0], view[1], view[0] + view[2], view[1] + view[3]
    else:
        vx0 = vy0 = -INF
        vx1 = vy1 = INF
    out: list[Seg] = []
    for s in boxes:
        y = s.edge
        if not vy0 + 2 <= y <= vy1 - 2:
            continue
        lo, hi = max(s.x0, vx0 + half * 0.6), min(s.x1, vx1 - half * 0.6)
        if hi - lo < 2:
            continue
        cuts = []                         # pet-middle ranges under something, and its room
        for b in boxes:
            if b is s or b.y0 >= y - 1 or b.y1 <= y - body.stand:
                continue
            a, z = b.x0 - half, b.x1 + half
            if z > lo and a < hi:
                cuts.append((a, z, max(0.0, y - b.y1)))
        out += _pieces(s, y, lo, hi, cuts, y - ceiling, body)
    if win is not None:
        wx, wy, ww, _wh = win
        room = wy - ceiling
        if room >= body.crouch and ww > body.w:
            out.append(Seg(wx + half * 0.6, wx + ww - half * 0.6, wy, "top", -2,
                           room=room, low=room < body.stand))
    return out


def _pieces(s: Box, y: float, lo: float, hi: float, cuts: list, room: float,
            body: Body) -> list[Seg]:
    xs = sorted({lo, hi, *(c for a, z, _ in cuts for c in (a, z) if lo < c < hi)})
    res: list[Seg] = []
    for p, q in zip(xs, xs[1:]):
        m = (p + q) / 2
        c = min([room] + [cl for a, z, cl in cuts if a <= m <= z])
        if c < body.lowest:
            continue
        low = c < body.stand
        tight = c < body.crouch
        if res and abs(res[-1].x1 - p) < 0.01 and res[-1].low == low and res[-1].tight == tight:
            res[-1] = replace(res[-1], x1=q, room=min(res[-1].room, c))
        else:
            res.append(Seg(p, q, y, s.kind, s.block, room=c, low=low, tight=tight))
    return res


def shelf(segs: list[Seg], here: Seg) -> tuple[float, float]:
    """How far the pet can walk from ``here`` without a leap: touching
    stretches at the same height (standing and crouching ones)."""
    lo, hi = here.x0, here.x1
    same = [s for s in segs if abs(s.y - here.y) < 1.0]
    grew = True
    while grew:
        grew = False
        for s in same:
            if s.x0 < lo - 0.5 and s.x1 >= lo - 0.5:
                lo, grew = s.x0, True
            if s.x1 > hi + 0.5 and s.x0 <= hi + 0.5:
                hi, grew = s.x1, True
    return lo, hi


# ---- pet physics helpers -------------------------------------------------------
def support(segs: list[Seg], x: float, feet: float, tol: float = SUPPORT_TOL) -> Seg | None:
    """The edge the pet stands on at (x, feet), if any (closest one)."""
    best = None
    for s in segs:
        if s.holds(x) and abs(s.y - feet) <= tol:
            if best is None or abs(s.y - feet) < abs(best.y - feet):
                best = s
    return best


def landing(segs: list[Seg], x: float, y_from: float, y_to: float) -> Seg | None:
    """The first edge a pet falling from y_from to y_to at x lands on."""
    hits = [s for s in segs if s.holds(x, 2.0) and y_from - 0.5 <= s.y <= y_to]
    return min(hits, key=lambda s: s.y) if hits else None


def base_lift(x0: float, y0: float, x1: float, y1: float) -> float:
    return 24.0 + 0.075 * abs(x1 - x0) + max(0.0, y0 - y1) * 0.35


def hop_point(x0: float, y0: float, x1: float, y1: float, t: float,
              lift: float | None = None) -> tuple[float, float]:
    """Position along a leap from (x0, y0) to (x1, y1) at t in [0, 1]: a
    parabola whose top is ``lift`` px above the higher end."""
    t = max(0.0, min(1.0, t))
    if lift is None:
        lift = base_lift(x0, y0, x1, y1)
    apex = min(y0, y1) - lift
    # quadratic Bezier through the apex control point
    cy = 2 * apex - (y0 + y1) / 2
    x = x0 + (x1 - x0) * t
    y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
    return x, y


def arc_clear(boxes: list[Box], body: Body, x0: float, y0: float, x1: float, y1: float,
              lift: float, steps: int = 14, flat: bool = False) -> bool:
    """Does a leap (feet from (x0, y0) to (x1, y1)) miss everything solid?
    In the air the pet is tucked: about crouching-high (``flat``: as low as
    it goes, slipping into or out of a tight spot)."""
    hw, hh = body.w * 0.42, (body.lowest * 0.9 if flat else body.crouch * 0.8)
    apex = min(y0, y1) - lift
    rx0, rx1 = min(x0, x1) - hw, max(x0, x1) + hw
    ry0, ry1 = apex - hh - lift, max(y0, y1)
    near = [b for b in boxes if b.x1 > rx0 and b.x0 < rx1 and b.y1 > ry0 and b.y0 < ry1]
    if not near:
        return True
    for i in range(1, steps):
        x, y = hop_point(x0, y0, x1, y1, i / steps, lift)
        bx0, bx1, by0, by1 = x - hw, x + hw, y - hh, y - 8
        for b in near:
            if b.x0 < bx1 and b.x1 > bx0 and b.y0 < by1 and b.y1 > by0:
                return False
    return True


def find_lift(boxes: list[Box], body: Body, x0: float, y0: float, x1: float,
              y1: float, flat: bool = False) -> float | None:
    """A leap height that clears everything, or None (can't get there).
    ``flat``: into or out of somewhere tight, so try low, flat hops first."""
    if y0 - y1 > body.max_rise or y1 - y0 > body.max_drop or abs(x1 - x0) > body.reach:
        return None
    # (the clearance over the higher end is in proportion to the pet)
    base = base_lift(x0, y0, x1, y1) - 24.0 + body.stand * 0.27
    lifts = ((3.0, 8.0, 14.0) if flat else ()) + (base, base * 1.7 + 16, base * 2.6 + 36)
    for lift in lifts:
        if y0 - min(y0, y1) + lift > body.max_rise + body.stand * 0.6:
            break
        if arc_clear(boxes, body, x0, y0, x1, y1, lift, flat=flat and lift < 15):
            return lift
    return None


@dataclass(frozen=True)
class Hop:
    seg: Seg
    x: float
    lift: float
    start: float | None = None   # where on its shelf it takes off (None: where it is)


def hops(segs: list[Seg], boxes: list[Box], body: Body, here: Seg, x: float) -> list[Hop]:
    """Every ledge the pet can leap to from its shelf without going through
    anything: from where it is, or after a few steps to a better take-off
    spot (beside the ledge rather than underneath it). Walking along the
    shelf isn't a leap."""
    lo, hi = shelf(segs, here)
    pad = min(body.w * 0.2, (hi - lo) / 2)
    out = []
    for s in segs:
        if abs(s.y - here.y) < 1.0 and s.x1 >= lo - 0.5 and s.x0 <= hi + 0.5:
            continue                                  # same shelf: walk there
        inset = min(body.w * 0.3, s.width / 2)
        # take-off spots: here, then just off either end of the target, nearest first
        spots = sorted({min(max(v, lo + pad), hi - pad)
                        for v in (x, s.x0 - body.w * 0.9, s.x1 + body.w * 0.9,
                                  s.x0 - body.w * 1.5, s.x1 + body.w * 1.5)},
                       key=lambda v: abs(v - x))
        for x0 in spots:
            tx = min(max(x0, s.x0 + inset), s.x1 - inset)
            if abs(tx - x0) < body.w * 0.3 and abs(s.y - here.y) < 4:
                continue                              # a step, not a leap
            lift = find_lift(boxes, body, x0, here.y, tx, s.y, flat=s.tight or here.tight)
            if lift is not None:
                out.append(Hop(s, tx, lift, None if abs(x0 - x) < 3 else x0))
                break
    return out


@dataclass(frozen=True)
class Climb:
    """Up (or down) the side of a column of text: step off the end of a
    shelf onto the wall beside it, climb, and step onto another shelf."""
    seg: Seg                     # the ledge it ends on
    x: float                     # where its middle ends up on it
    wall_x: float                # its middle's x while on the wall
    side: int                    # where the wall is, seen from the pet: -1 left, +1 right
    start_x: float               # where it steps off the shelf it's on
    edge: float = 0.0            # the wall itself (the text's side)


def _free(boxes: list[Box], x0: float, y0: float, x1: float, y1: float) -> bool:
    return not any(b.x0 < x1 and b.x1 > x0 and b.y0 < y1 and b.y1 > y0 for b in boxes)


def climbs(segs: list[Seg], boxes: list[Box], body: Body, here: Seg, x: float) -> list[Climb]:
    """Ledges above or below the pet it can reach up the side of the text: a
    straight wall (a column's edge, a picture's side) that comes down to the
    shelf it's on (or to the floor), with room for the pet beside it all the
    way. It walks along its shelf to the foot of the wall, climbs, and steps
    onto the ledge at the top."""
    lo, hi = shelf(segs, here)
    hw = cling_hw(body)
    out = []
    for b_seg in segs:
        dy = abs(b_seg.y - here.y)
        if dy < body.stand * 0.3 or b_seg is here:
            continue
        for d in (1, -1):                     # the wall on the ledge's right / left end
            b_end = b_seg.x1 if d > 0 else b_seg.x0
            if b_seg.kind == "floor":         # down to the floor: the wall is at *our* end
                b_end = hi if d > 0 else lo
            top = min(here.y, b_seg.y) - body.crouch
            bot = max(here.y, b_seg.y)
            # the wall: the outermost box edge on this side along the way
            if d > 0:
                edges = [b.x1 for b in boxes if b.y1 > top and b.y0 < bot
                         and b_end - body.w * 2.5 <= b.x1 <= b_end + hw]
                wall_x = max(edges + [b_end]) + hw + 2
            else:
                edges = [b.x0 for b in boxes if b.y1 > top and b.y0 < bot
                         and b_end - hw <= b.x0 <= b_end + body.w * 2.5]
                wall_x = min(edges + [b_end]) - hw - 2
            if abs(wall_x - b_end) > body.w * 1.4:
                continue
            # the foot of the wall must be on (or just off the end of) our shelf
            start = min(max(wall_x, lo), hi)
            if abs(start - wall_x) > body.w * 1.4:
                continue
            if not _free(boxes, wall_x - hw, top, wall_x + hw, bot - 2):
                continue
            # ...and a wall to hold on to for a fair part of the way
            near = [b for b in boxes if b.y1 > top and b.y0 < bot and
                    (wall_x - hw - body.w <= b.x1 <= wall_x - hw + 3 if d > 0
                     else wall_x + hw - 3 <= b.x0 <= wall_x + hw + body.w)]
            # ...something to hold on to all the way: no bare stretch longer
            # than it can reach across (no climbing up empty page)
            if _longest_gap([(max(top, b.y0), min(bot, b.y1)) for b in near], top, bot) \
                    > body.stand * 0.9:
                continue
            inset = min(body.w * 0.3, b_seg.width / 2)
            tx = b_seg.x1 - inset if d > 0 else b_seg.x0 + inset
            if b_seg.kind == "floor":
                tx = wall_x + d * body.w * 0.3    # hops off the foot of the wall
            out.append(Climb(b_seg, tx, wall_x, -d, start, wall_x - d * hw))
    return out


# ---- walls ---------------------------------------------------------------------
@dataclass(frozen=True)
class Wall:
    """The side of a column of text (or a picture) the pet can climb: only
    where there's something to hold on to all the way (gaps it can reach
    across are fine), with room beside it for its body."""
    x: float                     # the pet's middle while on it (frame-free estimate)
    top: float                   # highest its feet get (the top of the column)
    bot: float                   # lowest
    side: int                    # +1: the wall is on the pet's right
    edge: float                  # the wall itself


INDENT = 48                      # how far in an indented block still counts as the same wall
# On a wall the pet hugs it: its climbing frames stick out from the wall about
# 0.6x its standing height, so a gap that wide (plus a little) is room enough.
CLING = 0.33                     # half its thickness on a wall, x its standing height


def cling_hw(body: Body) -> float:
    """Half the room the pet needs beside a wall while it climbs."""
    return body.stand * CLING


def wall_surface(boxes: list[Box], w: Wall, y: float, body: Body) -> float:
    """Where the wall really is beside a pet whose feet are at height y: the
    nearest text edge alongside its body (further in where a block is
    indented, out again below it)."""
    lo, hi = y - body.stand * 0.8, y - 2
    if w.side > 0:
        xs = [b.x0 for b in boxes if b.y1 > lo and b.y0 < hi and w.edge - 3 <= b.x0 <= w.edge + INDENT]
        return min(xs) if xs else w.edge
    xs = [b.x1 for b in boxes if b.y1 > lo and b.y0 < hi and w.edge - INDENT <= b.x1 <= w.edge + 3]
    return max(xs) if xs else w.edge


def wall_path(boxes: list[Box], w: Wall, y0: float, y1: float, body: Body,
              step: float = 6.0) -> list[tuple[float, float]]:
    """The wall's outline from feet height y0 to y1, as (surface x, y)
    points: the pet shimmies in and out along it as it climbs (no more than
    a pixel sideways per pixel up)."""
    n = max(1, int(abs(y1 - y0) / step))
    pts = []
    prev = None
    for i in range(n + 1):
        y = y0 + (y1 - y0) * i / n
        x = wall_surface(boxes, w, y, body)
        if prev is not None:
            lim = abs(y - pts[-1][1])
            x = min(max(x, prev - lim), prev + lim)
        pts.append((x, y))
        prev = x
    return pts


def walls(boxes: list[Box], body: Body, floor_y: float | None = None) -> list[Wall]:
    hw = cling_hw(body)
    reach_gap = body.stand * 0.9                      # a gap in the wall it can reach across
    cands = set()
    for b in boxes:
        cands.add((round(b.x0 / 3) * 3, 1))
        cands.add((round(b.x1 / 3) * 3, -1))
    out: list[Wall] = []
    for e, side in sorted(cands):
        # (indented blocks a little further in are still this wall: the pet
        # follows the outline in and out, see wall_path)
        if side > 0:                                  # column to the pet's right: its left edges
            touch = [b for b in boxes if e - 3 <= b.x0 <= e + INDENT]
            wx = e - hw - 2
        else:                                         # column to the pet's left: its right edges
            touch = [b for b in boxes if e - INDENT <= b.x1 <= e + 3]
            wx = e + hw + 2
        if len(touch) < 2 and not any(b.y1 - b.y0 > body.stand for b in touch):
            continue
        spans = []
        for b in sorted(touch, key=lambda b: b.y0):
            if spans and b.y0 - spans[-1][1] <= reach_gap:
                spans[-1][1] = max(spans[-1][1], b.y1)
            else:
                spans.append([b.y0, b.y1])
        block = sorted((b.y0, b.y1) for b in boxes if b.x0 < wx + hw and b.x1 > wx - hw)
        for a, z in spans:
            # feet from the column's top edge down to its bottom, the body
            # needing room above the feet: cut where something's in the way
            pieces = [[a - body.crouch, z]]
            for b0, b1 in block:
                nxt = []
                for p0, p1 in pieces:
                    if b1 <= p0 or b0 >= p1:
                        nxt.append([p0, p1])
                        continue
                    if b0 > p0:
                        nxt.append([p0, b0])
                    if b1 < p1:
                        nxt.append([b1, p1])
                pieces = nxt
            for p0, p1 in pieces:
                top, bot = max(a, p0 + body.crouch), p1
                if floor_y is not None and floor_y - bot <= body.stand and \
                        not any(b.x0 < wx + hw and b.x1 > wx - hw and b.y1 > bot and b.y0 < floor_y
                                for b in boxes):
                    bot = floor_y                     # it comes down to the floor
                if bot - top < body.stand * 0.5:
                    continue
                if any(w.side == side and abs(w.x - wx) < 10 and w.top < bot and top < w.bot
                       for w in out):
                    continue
                out.append(Wall(wx, top, bot, side, e))
    return out


@dataclass(frozen=True)
class Scale:
    """A trip up (or down) walls: onto a wall from a shelf, climbing, maybe a
    leap across to another wall, and off onto a ledge at the end (pulling up
    over its edge, or a hop). ``ops`` spell it out for the pet."""
    seg: Seg                     # the ledge it ends on
    x: float                     # where its middle ends up
    start: float                 # where it steps onto the first wall from its shelf
    ops: tuple                   # ("mount", wall, y, from_top), ("climb", wall, y),
                                 # ("leap", wall, y, lift), ("pullup", wall, seg, x),
                                 # ("hop", seg, x, lift)
    cost: float = 1.0


class WallMap:
    """The walls of a page and the ways between them and the ledges, worked
    out once per page (what a route search asks again and again)."""

    def __init__(self, page: Page, floor: Seg | None = None) -> None:
        self.page = page
        b = page.body
        self.walls = walls(page.boxes, b, floor.y if floor is not None else None)
        self._exits: dict[int, list] = {}
        self._leaps: dict[int, list] = {}

    def mounts(self, here: Seg, x: float) -> list[tuple]:
        """Walls it can step onto from its shelf: (wall, feet y, start x, from_top)."""
        b = self.page.body
        lo, hi = shelf(self.page.segs, here)
        out = []
        for w in self.walls:
            if w.top - 4 <= here.y <= w.bot + 4:
                start = min(max(w.x, lo), hi)
                if abs(start - w.x) > b.w * 1.4:
                    continue
                from_top = abs(here.y - w.top) < 6 and (lo <= w.edge <= hi
                                                         or abs(w.edge - start) < b.w)
                out.append((w, here.y, start, from_top, None))
            elif 0 < here.y - w.bot <= b.max_rise:
                # the wall ends above it: jump up and grab hold
                start = min(max(w.x - w.side * b.w * 0.8, lo), hi)
                if abs(start - w.x) > b.reach:
                    continue
                lift = find_lift(self.page.boxes, b, start, here.y, w.x, w.bot)
                if lift is not None:
                    out.append((w, w.bot, start, False, lift))
        return out

    def exits(self, w: Wall) -> list[tuple]:
        """Ledges it can get onto from this wall: (ledge, x, ops, cost)."""
        if id(w) in self._exits:
            return self._exits[id(w)]
        b = self.page.body
        out = []
        for t in self.page.segs:
            if not (w.top - 6 <= t.y <= w.bot + b.max_drop):
                continue
            end = t.x0 if w.side > 0 else t.x1
            at_top = abs(t.y - w.top) < 6
            mid = (t.low or t.tight) and w.top <= t.y <= w.bot      # a gap in the column's side
            if (at_top or mid) and abs(end - w.edge) <= b.w * 1.4:
                inset = min(b.w * 0.3, t.width / 2)
                tx = t.x0 + inset if w.side > 0 else t.x1 - inset
                out.append((t, tx, (("climb", w, t.y), ("pullup", w, t, tx)), 1.0))
                continue
            # a hop off the wall to a ledge nearby
            if min(abs(t.x0 - w.x), abs(t.x1 - w.x)) > b.reach or t.y < w.top - b.max_rise:
                continue
            y = min(max(t.y + b.stand * 0.3, w.top), w.bot)
            inset = min(b.w * 0.3, t.width / 2)
            tx = min(max(w.x, t.x0 + inset), t.x1 - inset)
            if abs(tx - w.x) < b.w * 0.6:
                continue                              # right above or below: not a hop
            lift = find_lift(self.page.boxes, b, w.x, y, tx, t.y)
            if lift is not None:
                out.append((t, tx, (("climb", w, y), ("hop", t, tx, lift)), 1.2))
        self._exits[id(w)] = out
        return out

    def leaps(self, w: Wall) -> list[tuple]:
        """Other walls it can leap across to: (wall, from y, to y, lift)."""
        if id(w) in self._leaps:
            return self._leaps[id(w)]
        b = self.page.body
        out = []
        for v in self.walls:
            if v is w or abs(v.x - w.x) < b.w or abs(v.x - w.x) > b.reach:
                continue
            lo, hi = max(w.top, v.top), min(w.bot, v.bot)
            if hi < lo - b.max_rise:
                continue
            # leap level: as high as both allow, landing a little higher
            y1 = min(max(lo + b.stand * 0.3, w.top), w.bot)
            y2 = min(max(y1 - b.stand * 0.3, v.top), v.bot)
            lift = find_lift(self.page.boxes, b, w.x, y1, v.x, y2)
            if lift is not None:
                out.append((v, y1, y2, lift))
        self._leaps[id(w)] = out
        return out

    def scales(self, here: Seg, x: float, max_states: int = 30) -> list[Scale]:
        """Every ledge it can reach by way of walls from its shelf, the
        easiest way for each."""
        import heapq
        found: dict[int, Scale] = {}
        queue = []
        tick = 0
        for w, y, start, top, lift in self.mounts(here, x):
            tick += 1
            first = ("mount", w, y, top) if lift is None else ("leap", w, y, lift)
            heapq.heappush(queue, (0.5 if lift is None else 1.0, tick, w, y, start, (first,)))
        seen = set()
        n = 0
        while queue and n < max_states:
            cost, _t, w, y, start, ops = heapq.heappop(queue)
            if id(w) in seen:
                continue
            seen.add(id(w))
            n += 1
            for t, tx, tail, c in self.exits(w):
                if t is here or (abs(t.y - here.y) < 1 and t.x0 <= x <= t.x1):
                    continue
                total = cost + c + abs(t.y - y) / 400
                if id(t) not in found or found[id(t)].cost > total:
                    found[id(t)] = Scale(t, tx, start, ops + tail, total)
            for v, y1, y2, lift in self.leaps(w):
                if id(v) not in seen:
                    tick += 1
                    heapq.heappush(queue, (cost + 1.3 + abs(y1 - y) / 400, tick, v, y2, start,
                                           ops + (("climb", w, y1), ("leap", v, y2, lift))))
        return list(found.values())


# ---- finding a way there -------------------------------------------------------
SPOT_WEIGHT = {"search": 3.0, "top": 2.6, "h": 2.4, "img": 2.0, "video": 2.0, "button": 0.5,
               "field": 0.6, "p": 1.0, "li": 1.0, "quote": 1.0, "code": 0.8, "cell": 0.8,
               "row": 0.7, "floor": 0.0}


def spot_score(seg: Seg, body: Body, view: tuple | None) -> float:
    """How nice a place to settle: a heading, the search box, a picture, the
    top of the window; high up; room to sit up; space to lounge."""
    if seg.tight:
        return -10.0                    # a place to squeeze through, not to stay
    sc = SPOT_WEIGHT.get(seg.kind, 1.0)
    if view is not None:
        sc += 1.5 * max(0.0, min(1.0, (view[1] + view[3] - seg.y) / max(1.0, view[3])))
    sc += 0.0 if seg.low else 0.8
    sc += 0.6 * min(1.0, seg.width / (body.w * 3))
    return sc


@dataclass(frozen=True)
class Walk:
    """Along its shelf to another stretch of it (through a squeeze, say)."""
    seg: Seg
    x: float


def _along(segs: list[Seg], here: Seg, x: float, body: Body) -> list[Walk]:
    lo, hi = shelf(segs, here)
    out = []
    for s in segs:
        if s is here or abs(s.y - here.y) >= 1 or s.x1 < lo - 0.5 or s.x0 > hi + 0.5:
            continue
        inset = min(body.w * 0.4, s.width / 2)
        out.append(Walk(s, min(max(x, s.x0 + inset), s.x1 - inset)))
    return out


def _step_cost(opt) -> float:
    if isinstance(opt, Walk):
        return 0.6 if opt.seg.tight else 0.3
    if isinstance(opt, Scale):
        return 1.0 + opt.cost                           # climbing is harder work
    return 1.6 if isinstance(opt, Climb) else 1.0


def reach_score(x: float, y: float, body: Body, rise: float | None = None):
    """A route score for getting at the point (x, y), say a laser dot: the
    best ledge has it straight above within ``rise`` (default: a leap), or
    right on it. In body heights (so a step of the way, 0.12, is worth a
    little)."""
    rise = body.max_rise * 0.85 if rise is None else rise

    def score(seg: Seg) -> float:
        if seg.tight:
            return -1e3
        px = min(max(x, seg.x0), seg.x1)
        up = seg.y - y                          # how far above the ledge it is
        off = max(0.0, up - rise) + 1.5 * max(0.0, -up - body.stand * 0.3)
        return -(abs(x - px) + off) / max(1.0, body.stand)
    return score


def route(page: Page, here: Seg, x: float, max_nodes: int = 40,
          moves=None, seg_walks: bool = True, score=None) -> list:
    """The way to the best spot reachable from here, as a list of leaps and
    climbs (empty when here is already the best). Nicer spots are worth a
    longer way, but not much longer. ``score(seg)`` changes what "best" is
    (default: a nice spot to settle, see spot_score)."""
    import heapq
    base = moves or page.ways
    moves = (lambda seg, at: base(seg, at) + _along(page.segs, seg, at, page.body)) \
        if seg_walks else base
    if score is not None:
        best_path, best = [], score(here)
    else:
        best_path, best = [], spot_score(here, page.body, page.view) if here.kind != "floor" else -1e9
        score = lambda seg: spot_score(seg, page.body, page.view)   # noqa: E731
    seen = {id(here)}
    queue = [(0.0, 0, here, x, [])]
    n = 0
    tick = 1
    while queue and n < max_nodes:
        cost, _t, seg, at, path = heapq.heappop(queue)
        n += 1
        if path:
            val = score(seg) - 0.12 * cost
            if val > best:
                best, best_path = val, path
        for opt in moves(seg, at):
            if id(opt.seg) in seen:
                continue
            seen.add(id(opt.seg))
            tick += 1
            heapq.heappush(queue, (cost + _step_cost(opt), tick, opt.seg, opt.x, path + [opt]))
    return best_path


def _longest_gap(spans: list[tuple[float, float]], top: float, bot: float) -> float:
    """The longest stretch of [top, bot] no span covers."""
    gap, cur = 0.0, top
    for a, b in sorted(spans):
        if a > cur:
            gap = max(gap, a - cur)
        cur = max(cur, b)
    return max(gap, bot - cur)


# ---- playing on the page --------------------------------------------------------
@dataclass(frozen=True)
class Move:
    """What the pet does next on a page."""
    kind: str                    # "walk", "run", "hop", "climb" or "stay"
    x: float = 0.0               # where its middle should end up
    seg: Seg | None = None       # ... on this ledge
    linger: int = 0              # ticks to wait after arriving
    pose: str = "sit"            # "sit", "sleep", "lookaround" or "crouch" while lingering
    face: int = 0                # facing after arriving (0 = keep)
    lift: float | None = None    # leap height that clears things (None = default)
    mood: str = ""               # "climb" while working its way up
    wall: float = 0.0            # climb: the middle's x on the wall
    side: int = 0                # climb: where the wall is, seen from the pet
    start: float = 0.0           # climb: where it steps off its shelf
    edge: float = 0.0            # climb: x of the wall itself
    ops: tuple = ()              # scale: the trip by way of walls (see Scale)


def _go(opt, rng: random.Random, body: Body, mood: str = "", face: int = 0) -> Move:
    """A leap or a climb, as a move."""
    if isinstance(opt, Walk):
        return Move("walk", opt.x, opt.seg, linger=rng.randint(2, 6), mood=mood)
    pose = _rest_pose(opt.seg, body, "sit")
    linger = rng.randint(3, 10)
    if isinstance(opt, Scale):
        pose = _rest_pose(opt.seg, body, "lookaround" if rng.random() < 0.4 else "sit")
        return Move("scale", opt.x, opt.seg, linger=rng.randint(20, 50), pose=pose, mood=mood,
                    start=opt.start, ops=opt.ops)
    if isinstance(opt, Climb):
        # a climb is hard work: get your breath back, have a look from up there
        pose = _rest_pose(opt.seg, body, "lookaround" if rng.random() < 0.4 else "sit")
        return Move("climb", opt.x, opt.seg, linger=rng.randint(20, 50), pose=pose, mood=mood,
                    wall=opt.wall_x, side=opt.side, start=opt.start_x, edge=opt.edge)
    return Move("hop", opt.x, opt.seg, linger=linger, lift=opt.lift, face=face, pose=pose,
                mood=mood, start=opt.start if opt.start is not None else 0.0,
                edge=1.0 if opt.start is not None else 0.0)


@dataclass
class Page:
    """What the pet knows about the page in front of it."""
    segs: list[Seg]
    boxes: list[Box]
    body: Body
    view: tuple | None = None
    calm: bool = False           # full-size pet: find a good spot and mostly lounge there
    recent: tuple = ()           # ledges it was just on (so it doesn't ping-pong)
    floor: Seg | None = None     # the bottom of the screen
    _walls: object = None

    def wall_map(self) -> WallMap:
        if self._walls is None:
            self._walls = WallMap(self, self.floor)
        return self._walls

    def ways(self, here: Seg, x: float) -> list:
        """Everything it can do from here: leaps, and trips by way of walls
        (up the side of the text, across to another wall, onto a ledge)."""
        return hops(self.segs, self.boxes, self.body, here, x) + self.wall_map().scales(here, x)


def _rest_pose(seg: Seg, body: Body, want: str) -> str:
    """The pose to linger in, if it fits under whatever is above."""
    if seg.tight:
        return "crawl"
    if want == "sleep" or seg.room >= {"sit": body.sit, "lookaround": body.stand}.get(want, 0):
        return want
    return "crouch" if seg.room < body.sit else "sit"


def _stay(seg: Seg, x: float, body: Body, want: str, linger: int, mood: str = "") -> Move:
    return Move("stay", x, seg, linger=linger, pose=_rest_pose(seg, body, want), mood=mood)


ARRIVE_WEIGHT = {"search": 3.0, "h": 2.5, "img": 2.0, "video": 2.0, "top": 1.5, "p": 1.5,
                 "li": 1.2, "quote": 1.2, "button": 1.0, "field": 0.8}


def plan(page: Page, here: Seg | None, x: float, facing: int,
         rng: random.Random | None = None, mood: str = "") -> Move | None:
    """Play on the page. ``here`` is the ledge the pet stands on (None when
    it's elsewhere); ``facing`` is +1 right / -1 left; ``mood`` is "climb"
    while it's working its way up. A calm page (a full-size pet) gets the
    same play at a cat's pace: up to a good spot, then mostly lounging there,
    pacing its shelf now and then, so it isn't a distraction while you read."""
    rng = rng or random
    mv = _plan(page, here, x, facing, rng, mood)
    if mv is not None and page.calm and mv.kind in ("stay", "walk", "run"):
        mv = replace(mv, linger=int(mv.linger * 2.5) + 20)
    return mv


def _was_on(seg: Seg, recent: tuple) -> bool:
    return any(abs(seg.y - y) < 2 and seg.x0 < x1 and seg.x1 > x0 for y, x0, x1 in recent)


def _low_on_page(page: Page, here: Seg) -> bool:
    """In the lower part of what's on screen (somewhere better is above)."""
    v = page.view
    if v is None:
        return True
    return here.y > v[1] + v[3] * 0.4


def _plan(page: Page, here: Seg | None, x: float, facing: int, rng, mood: str) -> Move | None:
    calm = page.calm
    facing = 1 if facing >= 0 else -1
    segs, body = page.segs, page.body
    if not segs:
        return None
    if here is None:
        return None                 # in mid-air: it lands (or falls) first, no flying
    if here.kind == "floor":
        # on the floor below the page: find a way up to somewhere nice, one
        # leap or climb at a time (none: stay on the floor)
        if rng.random() > (0.6 if calm else 0.8):
            return None
        way = route(page, here, x)
        return _go(way[0], rng, body, mood="climb" if len(way) > 1 else "") if way else None

    if here.tight:
        # squeezing through: keep going to where it can sit up, or out
        lo, hi = shelf(segs, here)
        edge = body.w * 0.15
        roomy = [s for s in segs if abs(s.y - here.y) < 1 and not s.tight
                 and s.x1 >= lo - 0.5 and s.x0 <= hi + 0.5]
        if roomy:
            s0 = min(roomy, key=lambda s: min(abs(s.x0 - x), abs(s.x1 - x)))
            inset = min(body.w * 0.4, s0.width / 2)
            tx = min(max(x, s0.x0 + inset), s0.x1 - inset)
            return Move("walk", tx, here, linger=rng.randint(4, 10))
        ways = [o for o in page.ways(here, x) if not o.seg.tight]
        if ways:
            o = max(ways, key=lambda o: spot_score(o.seg, body, page.view)
                    + (0.5 if (o.x - x) * facing > 0 else 0.0))
            return _go(o, rng, body, mood=mood, face=1 if o.x > x else -1)
        # a dead end: back out the way it came
        end = hi - edge if facing > 0 else lo + edge
        back = lo + edge if facing > 0 else hi - edge
        return Move("walk", end if abs(end - x) > 4 else back, here, linger=2)
    # somewhere cosy: linger a while
    if here.kind in ("top", "search") and rng.random() < (0.85 if mood == "climb" else 0.6):
        return _stay(here, x, body, "sleep", rng.randint(160, 360))
    if here.kind == "video" and rng.random() < 0.6:
        return _stay(here, x, body, "sit", rng.randint(120, 260))
    if here.kind == "img" and rng.random() < 0.5:
        return _stay(here, x, body, "sleep" if rng.random() < 0.5 else "sit", rng.randint(80, 200))
    if here.kind == "h" and rng.random() < 0.35:
        return _stay(here, x, body, "lookaround", rng.randint(40, 90))
    if here.kind == "button" and rng.random() < 0.3:
        return _stay(here, x, body, "sit", rng.randint(20, 50))
    if mood != "climb" and rng.random() < (0.35 if calm else 0.05):
        return _stay(here, x, body, "sleep" if rng.random() < 0.4 else "sit", rng.randint(60, 150))

    # explore the shelf: walk (or run, on a long one) to its end
    lo, hi = shelf(segs, here)
    edge = body.w * 0.15
    end = hi - edge if facing > 0 else lo + edge
    if mood != "climb" and (end - x) * facing > body.w * 0.5 and rng.random() < (0.4 if calm else 0.65):
        far = abs(end - x)
        run = far > body.w * 4 and rng.random() < 0.5
        return Move("run" if run else "walk", end, here, linger=rng.randint(6, 20))

    if mood == "climb":
        # on its way somewhere: the next leap or climb of the way there
        way = route(page, here, x)
        if way:
            return _go(way[0], rng, body, mood="climb" if len(way) > 1 else "")
        # this is the spot: settle in
        return _stay(here, x, body, "sleep" if rng.random() < 0.6 else "lookaround",
                     rng.randint(120, 300))
    options = page.ways(here, x)
    fresh = [o for o in options if not _was_on(o.seg, page.recent)]
    if calm and options and not fresh:
        # it's been everywhere it can get to from here: settle down instead
        # of pacing back and forth between the same ledges
        return _stay(here, x, body, "sleep" if rng.random() < 0.5 else "sit", rng.randint(100, 220))
    if fresh and (calm or rng.random() < 0.85):
        options = fresh                         # somewhere it hasn't just been
    ups = [o for o in options if o.seg.y < here.y - body.stand * 0.25]
    drive = (0.3 if _low_on_page(page, here) else 0.04) if calm else 0.2
    if rng.random() < drive:
        way = route(page, here, x)
        if way:
            return _go(way[0], rng, body, mood="climb" if len(way) > 1 else "")

    if mood != "climb" and any(isinstance(o, Hop) for o in options):
        # outside a climbing mood, leaps first; climbing is for working your way up
        if rng.random() < 0.75:
            options = [o for o in options if isinstance(o, Hop)]
            ups = [o for o in ups if isinstance(o, Hop)]
    elif mood != "climb" and rng.random() < 0.5:
        options, ups = [], []                   # don't go up and down the same wall all day
    ahead = [o for o in options if isinstance(o, Hop) and (o.x - x) * facing > body.w * 0.3
             and abs(o.seg.y - here.y) <= body.stand * 0.7]
    downs = [o for o in options if o.seg.y > here.y + body.stand * 0.25]
    roll = rng.random()
    pick = None
    if ahead and roll < 0.5:                    # onwards: over the gap, the button...
        pick = min(ahead, key=lambda o: abs(o.x - x))
    elif ups and roll < 0.65:
        pick = rng.choice(ups)
    elif downs and roll < 0.92:
        pick = min(downs, key=lambda o: (o.seg.y - here.y) + 0.5 * abs(o.x - x))
    elif options:
        pick = rng.choice(options)
    if pick is not None:
        return _go(pick, rng, body, face=1 if pick.x > x else -1)
    # nowhere to leap: peek over the edge, turn round and explore the other
    # way, or rest
    back = lo + edge if facing > 0 else hi - edge
    roll = rng.random()
    if roll < 0.3:
        return _stay(here, x, body, "lookaround", rng.randint(30, 70))
    if abs(back - x) > body.w * 0.5 and roll < 0.7:
        return Move("walk", back, here, linger=rng.randint(10, 30))
    return _stay(here, x, body, "sit" if rng.random() < 0.6 else "sleep", rng.randint(60, 160))
