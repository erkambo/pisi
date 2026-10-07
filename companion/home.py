"""PISI's corner: a strip of things (bed, post, bowl, toy basket) standing on
the bottom edge of a screen, in the taskbar's strip (so it doesn't cover
your windows), drawn at the cat's own scale. Drag it along the bottom to
wherever your taskbar has room; click a thing to send the cat over.

The things are fitted to the current cat (``companion/things``). The strip is
a click-through overlay except on the things themselves: clicking one sends
the cat to use it. While the cat uses a thing, the cat's own window draws
that thing behind and in front of the cat at exactly the same spot (so a
bed's rim covers the cat on every OS, whatever the window stacking).
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QBitmap, QImage, QPainter, QPixmap, QRegion
from PyQt6.QtWidgets import QApplication, QWidget

from .log import get_logger

log = get_logger(__name__)

STARTER = {"bed": "bed.rose_donut", "bowl": "bowl.blue", "basket": "basket.wicker"}
MODES = ("full", "bed", "off")      # everything / just the bed / no corner


def pixmap(rgba: bytes | None, w: int, h: int, scale: int, mirror: bool = False) -> QPixmap | None:
    if rgba is None:
        return None
    img = QImage(rgba, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
    if mirror:
        img = img.mirrored(True, False)
    return QPixmap.fromImage(img.scaled(w * scale, h * scale, Qt.AspectRatioMode.IgnoreAspectRatio,
                                        Qt.TransformationMode.FastTransformation))


@dataclass
class Spot:
    """A thing in the corner, as the cat needs it to use it."""
    kind: str
    item_id: str
    r: object                 # things.draw.Rendered
    pos: QPoint               # global top-left of the thing on screen
    scale: int
    facing: int               # the way the cat faces while using it
    back: QPixmap | None
    front: QPixmap | None
    walk_floor: int = 0       # global y of the cat's usual floor on this screen

    def cat_frame_pos(self, frame_w: int) -> QPoint:
        """Global top-left of the cat's frame while it uses the thing."""
        x, y = self.r.cat_at_facing(self.facing, frame_w)
        return QPoint(self.pos.x() + x * self.scale, self.pos.y() + y * self.scale)


def home_config(cfg: dict) -> dict:
    h = cfg.get("home")
    if not isinstance(h, dict):
        h = {}
    placed = h.get("placed")
    if not isinstance(placed, dict):
        placed = dict(STARTER)
    mode = h.get("mode", "full")
    if mode not in MODES:
        mode = "full"
    if not h.get("enabled", True):
        mode = "off"
    if mode == "bed":
        placed = {k: v for k, v in placed.items() if k == "bed"}
    try:
        offset = float(h["offset"]) if "offset" in h else None
    except (TypeError, ValueError):
        offset = None
    order = h.get("order")
    if not isinstance(order, list):
        order = None
    return {"enabled": mode != "off", "mode": mode, "side": h.get("side", default_side()),
            "screen": h.get("screen", ""), "placed": placed, "offset": offset, "order": order}


def default_side() -> str:
    return "right"


def default_offset(screen_w: int) -> int:
    """How far in from the corner the strip starts, by default: on macOS the
    corners beside the Dock are free; on Windows and Linux the corners hold
    the Start / menu button and the clock, so start a little way in, in the
    empty middle-right of the taskbar (drag it anywhere)."""
    import sys
    if sys.platform == "darwin":
        return 0
    return int(screen_w * 0.22)


class HomeCorner(QWidget):
    clicked = pyqtSignal(str)            # kind of the thing clicked
    drag_started = pyqtSignal()
    moved = pyqtSignal(int)              # new offset from the corner (logical px), after a drag
    changed = pyqtSignal()               # the things moved, appeared or went (for panel extensions)

    def __init__(self) -> None:
        super().__init__(None)
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        if QApplication.platformName() == "xcb":
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.spots: dict[str, Spot] = {}
        self._items: list[tuple[QRect, QPixmap | None, QPixmap | None]] = []
        self.pet = None
        self.fit = None
        self._press: QPoint | None = None
        self._press_x = 0
        self._dragging = False
        self._side = "left"
        self._bounds = QRect()
        self._screen = None
        self._through = False

    # ---- building ---------------------------------------------------------
    def build(self, genome, cfg: dict, scale: int, walk_floor: int, screen=None) -> bool:
        """Fit the placed things to the cat with ``genome`` and lay them out
        along the bottom edge of ``screen`` (in the taskbar's strip).
        ``walk_floor`` is the global y of the cat's usual floor there (it
        hops down to the things from it). False (and hidden) if there's
        nothing to show."""
        from .creatures import api
        from .things import catalog, fit as F, layout as L
        from .things.kinds import KINDS
        hc = home_config(cfg)
        if genome is None or not hc["enabled"]:
            self.clear()
            return False
        try:
            pet = api.Creature(genome)
            ft = F.measure(pet)
            things = {}
            for kind, item_id in hc["placed"].items():
                it = catalog.BY_ID.get(item_id)
                if it is None or it.kind != kind or kind not in KINDS:
                    continue
                things[kind] = (item_id, KINDS[kind].render(it.design, ft))
            placed, width, height = L.layout(things, pet, hc["order"])
        except Exception:  # noqa: BLE001 - the corner must never take the cat down
            log.warning("home: couldn't build the corner", exc_info=True)
            self.clear()
            return False
        if not placed:
            self.clear()
            return False
        self.pet, self.fit = pet, ft
        scr = screen or QApplication.primaryScreen()
        g = scr.geometry()
        right = hc["side"] == "right"
        facing = -1 if right else 1
        wpx, hpx = width * scale, height * scale
        off = hc["offset"] if hc["offset"] is not None else default_offset(g.width())
        off = int(max(0, min(off, g.width() - wpx)))
        left = g.right() + 1 - wpx - off if right else g.left() + off
        top = g.bottom() + 1 - hpx                # standing on the bottom edge
        self._side = hc["side"]
        self._bounds = g
        self._screen = scr
        self.setGeometry(left, top, wpx, hpx)
        self.spots.clear()
        self._items = []
        mask = QRegion()
        for p in placed:
            x = (width - p.x - p.r.w) if right else p.x
            y = height - p.r.h
            local = QRect(x * scale, y * scale, p.r.w * scale, p.r.h * scale)
            back = pixmap(p.r.back, p.r.w, p.r.h, scale, mirror=right)
            front = pixmap(p.r.front, p.r.w, p.r.h, scale, mirror=right)
            self._items.append((local, back, front))
            self.spots[p.kind] = Spot(p.kind, p.item_id, p.r, QPoint(left + local.x(), top + local.y()),
                                      scale, facing, back, front, walk_floor)
            for pm in (back, front):
                if pm is not None:
                    mask += QRegion(QBitmap.fromImage(
                        pm.toImage().createAlphaMask())).translated(local.topLeft())
        self.setMask(mask)
        self.update()
        self.show()
        self.changed.emit()
        return True

    def clear(self) -> None:
        self.spots.clear()
        self._items = []
        self.hide()
        self.changed.emit()

    # ---- drawing / clicks ---------------------------------------------------
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        for rect, back, front in self._items:
            if back is not None:
                p.drawPixmap(rect.topLeft(), back)
            if front is not None:
                p.drawPixmap(rect.topLeft(), front)
        p.end()

    def max_offset(self) -> int:
        return max(0, self._bounds.width() - self.width())

    def set_offset(self, off: int) -> None:
        """Slide the strip to ``off`` px in from its corner, at once (the
        things move with it; no rebuild)."""
        g = self._bounds
        off = int(max(0, min(off, self.max_offset())))
        x = g.right() + 1 - self.width() - off if self._side == "right" else g.left() + off
        dx = x - self.x()
        if not dx:
            return
        self._slide_to(x)

    def _slide_to(self, x: int) -> None:
        dx = x - self.x()
        if not dx:
            return
        self.move(x, self.y())
        for spot in self.spots.values():
            spot.pos = QPoint(spot.pos.x() + dx, spot.pos.y())
        self.changed.emit()

    def offset(self) -> int:
        """Where the strip is now: logical px in from its corner."""
        g = self._bounds
        if self._side == "right":
            return g.right() + 1 - (self.x() + self.width())
        return self.x() - g.left()

    # ---- clicks and drags: your mouse, or forwarded by a panel extension ----------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.press(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e) -> None:
        self.drag_to(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.release(e.globalPosition().toPoint())

    def press(self, gp: QPoint) -> None:
        self._press = gp
        self._press_x = self.x()
        self._dragging = False

    def drag_to(self, gp: QPoint) -> None:
        if self._press is None:
            return
        dx = gp.x() - self._press.x()
        if not self._dragging and abs(dx) > 6:
            self._dragging = True
            self.drag_started.emit()
        if self._dragging:
            g = self._bounds
            self._slide_to(max(g.left(), min(self._press_x + dx, g.right() + 1 - self.width())))

    def release(self, gp: QPoint) -> None:
        if self._press is None:
            return
        was_drag, self._dragging = self._dragging, False
        self._press = None
        if was_drag:
            self.moved.emit(self.offset())
            return
        kind = self.kind_at(gp)
        if kind is not None:
            self.clicked.emit(kind)

    def kind_at(self, gp: QPoint) -> str | None:
        """The thing at global point ``gp`` (None: none)."""
        for kind, spot in self.spots.items():
            if QRect(spot.pos, QPoint(spot.pos.x() + spot.r.w * spot.scale - 1,
                                      spot.pos.y() + spot.r.h * spot.scale - 1)).contains(gp):
                return kind
        return None

    # ---- for panel extensions (see panelbridge.py) ----------------------------------
    def set_click_through(self, on: bool) -> None:
        """With a panel extension taking the clicks, the corner's window lets
        them through: the window manager hands a click on a window straight
        to it, so where the shell's panel owns the input the click would be
        lost. Nothing changes on screen."""
        if on == self._through:
            return
        self._through = on
        shown = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, on)
        if shown:
            self.show()                     # (changing a window flag hides it)

    def click_through(self) -> bool:
        return self._through

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.changed.emit()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.changed.emit()

    def hotspots(self) -> list[dict]:
        """Where the things are, in real screen pixels (what a desktop shell
        works in): one rectangle per thing. Empty when the corner isn't
        showing."""
        if not self.isVisible() or not self.spots:
            return []
        out = []
        for kind, spot in self.spots.items():
            x0, y0 = self.to_real(spot.pos)
            x1, y1 = self.to_real(QPoint(spot.pos.x() + spot.r.w * spot.scale,
                                         spot.pos.y() + spot.r.h * spot.scale))
            out.append({"id": kind, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
        return out

    def _origin_dpr(self) -> tuple[int, int, float]:
        scr = self._screen or QApplication.primaryScreen()
        g = scr.geometry() if scr else self._bounds
        dpr = (scr.devicePixelRatio() if scr else 1.0) or 1.0
        return g.x(), g.y(), dpr

    def to_real(self, p: QPoint) -> tuple[int, int]:
        """Qt's logical point -> real pixels (Qt keeps a screen's top-left in
        real pixels and scales from there)."""
        ox, oy, dpr = self._origin_dpr()
        return ox + round((p.x() - ox) * dpr), oy + round((p.y() - oy) * dpr)

    def from_real(self, x: float, y: float) -> QPoint:
        ox, oy, dpr = self._origin_dpr()
        return QPoint(ox + round((x - ox) / dpr), oy + round((y - oy) / dpr))
