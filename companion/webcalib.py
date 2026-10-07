"""Checking the browser's geometry against the screen itself.

The extension says "a line of text is here". Usually that's exact, but a
browser can be off by a few dozen pixels before the mouse has crossed the page
(an unexpected side panel), or by a scaling quirk. So now and then PISI looks
at a thin strip of the screen around a few reported lines and asks: where is
the ink, really? If the ink sits consistently a few pixels away from where the
lines were reported, that's the correction.

The matching works on a grayscale strip (bytes) so it can be tested with
synthetic images; :class:`Calibrator` does the screen grabs with Qt. Nothing
is saved or sent: the pixels are looked at once and dropped.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass


def ink_rows(gray: bytes, w: int, h: int, stride: int, x0: int = 0, x1: int | None = None,
             step: int = 2) -> list[float]:
    """Per row: the share of pixels that stand out from that row's background."""
    x1 = w if x1 is None else min(w, x1)
    out = []
    for y in range(h):
        row = gray[y * stride + x0: y * stride + x1: step]
        if not row:
            out.append(0.0)
            continue
        bg = sorted(row)[len(row) // 2]
        out.append(sum(1 for v in row if abs(v - bg) > 48) / len(row))
    return out


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 1e-9 or vb <= 1e-9:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** 0.5


def _shift_scores(ink: list[float], spans: list[tuple[float, float]], origin: float,
                  max_shift: int, step: int = 1, center: int = 0) -> dict[int, float]:
    """Correlation of an ink profile with spans (a, length) shifted by each
    amount, ``origin`` being the profile's first position."""
    n = len(ink)
    out = {}
    for d in range(center - max_shift, center + max_shift + 1, step):
        mask = [0.0] * n
        for a, ln in spans:
            lo, hi = int(round(a + d - origin)), int(round(a + ln + d - origin))
            for r in range(max(0, lo), min(n, hi)):
                mask[r] = 1.0
        out[d] = _corr(ink, mask)
    return out


def _best(scores: dict[int, float], apart: int) -> tuple[int, float, float]:
    """(best shift, its score, the best score clearly elsewhere). A flat-topped
    peak gives its middle."""
    d, sc = max(scores.items(), key=lambda kv: (kv[1], -abs(kv[0])))
    top = [k for k, v in scores.items() if v >= sc - 0.004 and abs(k - d) <= apart]
    d = int(round(sum(top) / len(top)))
    other = max((v for k, v in scores.items() if abs(k - d) > apart), default=-1.0)
    return d, sc, other


def _lines_show(gray: bytes, w: int, h: int, stride: int, left: float, top: float,
                lines: list) -> bool:
    """Are these lines of text really on screen here? Ink inside each line,
    blank in the thin gap just above it (whatever is beside the column)."""
    def frac(x0, y0, x1, y1):
        x0, x1 = max(0, int(x0)), min(w, int(x1))
        y0, y1 = max(0, int(y0)), min(h, int(y1))
        if x1 - x0 < 8 or y1 <= y0:
            return None
        rows = [gray[y * stride + x0: y * stride + x1: 2] for y in range(y0, y1)]
        bg = sorted(rows[len(rows) // 2])[len(rows[len(rows) // 2]) // 2]
        hit = sum(1 for r in rows for v in r if abs(v - bg) > 48)
        return hit / sum(len(r) for r in rows)
    good = n = 0
    for x, y, lw, lh in lines:
        bx, by = x - left, y - top
        inside = frac(bx, by + lh * 0.2, bx + lw, by + lh * 0.8)
        above = frac(bx, by - 5, bx + lw, by - 1)
        if inside is None or above is None:
            continue
        n += 1
        good += inside > 0.03 and inside > above * 2
    return n > 0 and good >= max(2, n // 2)


def _edge_fit(gray: bytes, w: int, h: int, stride: int, left: float, top: float,
              lines: list, dx: float, dy: float) -> float:
    """Sharp, for the last pixel or two: ink inside each line box against
    the thin bands just above and below it, every row."""
    def frac(x0, y0, x1, y1):
        x0, x1 = max(0, int(x0)), min(w, int(x1))
        y0, y1 = max(0, int(y0)), min(h, int(y1))
        if x1 - x0 < 8 or y1 <= y0:
            return None
        hit = n = 0
        for y in range(y0, y1):
            row = gray[y * stride + x0: y * stride + x1: 3]
            bg = sorted(row)[len(row) // 2]
            hit += sum(1 for v in row if abs(v - bg) > 48)
            n += len(row)
        return hit / n
    score = []
    for x, y, lw, lh in lines[::max(1, len(lines) // 40)]:
        bx, by = x + dx - left, y + dy - top
        inside = frac(bx, by + 2, bx + lw, by + lh - 2)
        above = frac(bx, by - 4, bx + lw, by)
        below = frac(bx, by + lh, bx + lw, by + lh + 4)
        if inside is None or above is None or below is None:
            continue
        score.append(inside - max(above, below))
    return sum(score) / len(score) if score else -1.0


def _fit_2d(gray: bytes, w: int, h: int, stride: int, left: float, top: float,
            lines: list, dx: float, dy: float) -> float:
    """How well boxes shifted by (dx, dy) sit on the ink: inside them minus
    just past their right ends (where a ragged line stops)."""
    def ink(x0, y0, x1, y1):
        x0, x1 = max(0, int(x0)), min(w, int(x1))
        y0, y1 = max(0, int(y0)), min(h, int(y1))
        if x1 - x0 < 4 or y1 - y0 < 2:
            return None
        hit = n = 0
        for y in range(y0, y1, 3):
            row = gray[y * stride + x0: y * stride + x1: 4]
            bg = sorted(row)[len(row) // 2]
            hit += sum(1 for v in row if abs(v - bg) > 48)
            n += len(row)
        return hit / n if n else None
    ins, outs = [], []
    for x, y, lw, lh in lines[::max(1, len(lines) // 30)]:
        bx, by = x + dx - left, y + dy - top
        a = ink(bx, by, bx + lw, by + lh)
        b = ink(bx + lw + 8, by, bx + lw + 60, by + lh)
        if a is not None:
            ins.append(a)
        if b is not None:
            outs.append(b)
    if not ins:
        return -1.0
    return sum(ins) / len(ins) - (sum(outs) / len(outs) if outs else 0.0)


UP_REACH = 60          # a page is seldom higher than the browser says (its
                       # toolbars, unreported, push it *down*): search less upwards


def locate(gray: bytes, w: int, h: int, stride: int, left: float, top: float,
           lines: list[tuple[float, float, float, float]], reach: int,
           prior: tuple[float, float] | None = None) -> Fix | None:
    """Where a whole page really is: match the pattern of its text (line
    rows, paragraph gaps, headings; then the columns' edges) against the ink
    in a grab of the screen around it, up to ``reach`` px off. Only answers
    when one place clearly beats every other (text is periodic, so a near
    tie means it can't tell)."""
    if len(lines) < 6:
        return None
    up = min(reach, UP_REACH)
    x_lo = int(min(l[0] for l in lines) - left)
    x_hi = int(max(l[0] + l[2] for l in lines) - left)
    spans = [(l[1], l[3]) for l in lines]
    # a wrong answer is a whole line off: compare with shifts half a line away
    pitch = sorted(l[3] for l in lines)[len(lines) // 2]
    apart = max(8, int(pitch * 0.6))
    # the page may be off sideways too (with other windows' text beside it),
    # so look for the line pattern under a few sideways shifts and keep the
    # one where it's clearest
    best = None
    for sx in sorted(range(-reach, reach + 1, 80), key=abs):
        xa, xb = max(0, x_lo + sx), min(w, x_hi + sx)
        if xb - xa < 80:
            continue
        ink = ink_rows(gray, w, h, stride, xa, xb, step=10)
        if max(ink) < 0.05:
            continue
        coarse = _shift_scores(ink, spans, top, (reach + up) // 2, step=3,
                               center=(reach - up) // 2)
        d0, sc0, ot0 = _best(coarse, apart)
        q = sc0 - 0.5 * max(0.0, ot0)
        if best is None or q > best[0]:
            best = (q, ink, coarse, d0, sx)
        if sc0 >= 0.5 and sc0 - ot0 >= 0.12:
            break                                  # clear enough: no need to look further
    if best is None:
        return None
    _q, ink, coarse, d0, sx0 = best
    # lines are evenly spaced, so one line off can score almost as well top
    # to bottom: settle it in 2D (ink inside each box, blank just past each
    # line's ragged end) between the strongest few candidates, each with its
    # own sideways offset (from where its lines start)
    # (dense, evenly spaced text like a list of references can rank the right
    # place below several wrong ones top to bottom, so check plenty; and the
    # place found last time for this screen, if any, always)
    peaks = [round(prior[1])] if prior is not None else []
    for d, sc in sorted(coarse.items(), key=lambda kv: -kv[1]):
        if all(abs(d - q) > apart for q in peaks):
            peaks.append(d)
        if len(peaks) == 8:
            break
    scored = []
    for d in peaks:
        dxc = _starts_dx(gray, w, h, stride, left, top, lines, d, reach, sx0)
        scored.append((_fit_2d(gray, w, h, stride, left, top, lines, dxc, d), d, dxc))
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.04:
        return None                                # can't tell them apart
    fit, d0, dx = scored[0]
    if fit < 0.05:
        return None
    # the last few pixels: where the boxes sit squarely on the letters
    dy = max(range(d0 - 6, d0 + 7),
             key=lambda d: _edge_fit(gray, w, h, stride, left, top, lines, dx, d))
    score = _best(_shift_scores(ink, spans, top, 0, center=dy), apart)[1]
    return Fix(float(dx), float(dy), score)


def _starts_dx(gray, w, h, stride, left, top, lines, dy, reach, sx0) -> float:
    """Sideways offset from where lines start (ink after a stretch of blank),
    in the rows the lines are in at vertical offset dy."""
    rows = sorted({r for _x, y, _w, hh in lines
                   for r in range(int(y + dy - top), int(y + hh + dy - top)) if 0 <= r < h})
    if not rows:
        return 0.0
    # ...then where lines *start*: ink after a stretch of blank, row by row
    edges = [0.0] * w
    for r in rows[::4]:
        row = gray[r * stride: r * stride + w]
        bg = sorted(row[::4])[len(row[::4]) // 2]
        last = -100
        for x in range(w):
            if abs(row[x] - bg) > 48:
                if x - last > 12:
                    edges[x] += 1.0
                last = x
    # coarse in 3-px bins, then the exact pixel
    k = 3
    bins = [sum(edges[i:i + k]) for i in range(0, w, k)]
    starts = [((l[0] - 2) / k, 6 / k) for l in lines]
    # near where the sideways scan found the lines (other windows' text further
    # away has line starts too), or across the whole width if that's clearer
    near = _best(_shift_scores(bins, starts, left / k, 85 // k, center=round(sx0 / k)), 2)
    wide = _best(_shift_scores(bins, starts, left / k, reach // k), 2)
    dxb, sx, ox = max(near, wide, key=lambda r: r[1] - 0.5 * max(0.0, r[2]))
    if sx < 0.2 or sx - ox < 0.05:
        return 0.0
    fine = _shift_scores(edges, [(l[0] - 2, 5) for l in lines], left, k + 1, center=dxb * k)
    return float(_best(fine, 0)[0])


@dataclass
class Fix:
    dx: float
    dy: float
    score: float


class Calibrator:
    """Grabs strips of the screen and nudges a WebSurfaces' offset."""

    def __init__(self, surfaces, avoid=lambda: None, own=lambda: []) -> None:
        self.surfaces = surfaces
        self.avoid = avoid                        # () -> QRect to keep out (the pet)
        self.own = own                            # () -> our windows to hide while looking
        self.enabled = sys.platform != "darwin"   # macOS would ask for Screen Recording
        self._next_locate = 0.0
        self._next_verify = 0.0
        self._unseen = 0

    def _grab(self, scr, x: int, y: int, w: int, h: int):
        """A grab of the screen without our own drawings on it (the debug
        overlay draws where we *think* the text is: matching against that
        kept PISI from ever finding the real page)."""
        from PyQt6.QtCore import QThread
        from PyQt6.QtWidgets import QApplication
        hidden = [win for win in self.own() if win is not None and win.isVisible()]
        for win in hidden:
            win.hide()
        if hidden:
            QApplication.processEvents()
            QThread.msleep(60)                        # let the compositor catch up
        try:
            return scr.grabWindow(0, x, y, w, h)
        finally:
            for win in hidden:
                win.show()

    def from_windows(self) -> bool:
        """On X11: place the page from its window's real place (see xwin).
        True when that worked."""
        from PyQt6.QtWidgets import QApplication
        from . import xwin
        if QApplication.platformName() != "xcb" or not xwin.available():
            return False
        wins = [(x, y, w, h) for _id, _c, x, y, w, h in xwin.browser_windows()]
        fix = self.surfaces.window_fix(wins)
        if fix is None:
            return False
        cur = self.surfaces.correction
        if not self.surfaces.located or abs(cur[0] - fix[0]) > 1.5 or abs(cur[1] - fix[1]) > 1.5:
            self.surfaces.place(*fix)
        return True

    def in_view(self) -> bool | None:
        """Is the active page still to be seen where we have it (another
        window may cover it now)? None: can't tell."""
        from PyQt6.QtCore import QPoint, QRect
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QApplication
        fx, fy = self.surfaces.correction
        boxes = [(x + fx, y + fy, w, h) for x, y, w, h in self.surfaces.text_boxes() if w >= 80]
        if len(boxes) < 4:
            return None
        pet = self.avoid()
        boxes = [b for b in boxes if pet is None or not QRect(int(b[0]), int(b[1]), int(b[2]),
                                                              int(b[3])).intersects(pet)]
        boxes.sort(key=lambda b: b[1])
        band = boxes[len(boxes) // 2: len(boxes) // 2 + 6]
        if len(band) < 3:
            return None
        left = min(b[0] for b in band) - 4
        top = min(b[1] for b in band) - 4
        right = max(b[0] + b[2] for b in band) + 64
        bottom = max(b[1] + b[3] for b in band) + 4
        scr = QApplication.screenAt(QPoint(int(left + 2), int(top + 2)))
        if scr is None:
            return None
        g = scr.geometry()
        area = QRect(int(left), int(top), int(right - left), int(bottom - top)).intersected(g)
        if area.width() < 60 or area.height() < 20:
            return None
        # (no need to hide the debug overlay: its thin outlines fall on the
        # lines' edges, outside what this looks at, so the overlay doesn't blink)
        pm = scr.grabWindow(0, area.x() - g.x(), area.y() - g.y(), area.width(), area.height())
        img = pm.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        img = img.scaled(area.width(), area.height())
        data = bytes(img.constBits().asstring(img.sizeInBytes()))
        return _lines_show(data, img.width(), img.height(), img.bytesPerLine(),
                           area.x(), area.y(), band)

    def check(self) -> Fix | None:
        if not self.surfaces.active:
            return None
        if self.from_windows():
            return None                           # placed exactly, no need to look
        if not self.enabled:
            return None
        if self.surfaces.located and self.surfaces.focus_age > 2.0:
            # you're in another window: is the page still there to be seen?
            seen = self.in_view()
            if seen is not None:
                self._unseen = 0 if seen else self._unseen + 1
                self.surfaces.set_covered(self._unseen >= 2)
            return None
        now = time.monotonic()
        if not self.surfaces.located:
            # a whole-screen look takes ~0.5 s: not more than every few seconds
            if now < self._next_locate:
                return None
            self._next_locate = now + 8.0
            self._next_verify = now + 30.0
            return self.locate()
        if self.surfaces.take_verify_soon():
            self._next_verify = min(self._next_verify, now + 3.0)   # a remembered place
        if now >= self._next_verify:
            # now and then, the reliable whole-page look again: if the page
            # really moved (the window, a bar shown), follow it
            self._next_verify = now + 30.0
            return self.locate(verify=True)
        return None

    LOCATE_REACH = 200            # px a page can be off when we've no idea

    def locate(self, verify: bool = False) -> Fix | None:
        """Find the whole page on screen (once per page placement; with
        ``verify``, check the current placement and move it only if the page
        is clearly somewhere else)."""
        from PyQt6.QtCore import QPoint, QRect
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QApplication
        view = self.surfaces.view()
        boxes = self.surfaces.text_boxes()
        if view is None or len(boxes) < 6:
            return None
        dx0, dy0 = self.surfaces.correction
        if verify:                                # look from where we think it is
            boxes = [(x + dx0, y + dy0, w, h) for x, y, w, h in boxes]
            vx, vy, vw, vh = view
        else:
            vx, vy, vw, vh = view[0] - dx0, view[1] - dy0, view[2], view[3]
        scr = QApplication.screenAt(QPoint(int(vx + vw / 2), int(vy + vh / 2)))
        if scr is None:
            return None
        g = scr.geometry()
        r = 60 if verify else self.LOCATE_REACH
        area = QRect(int(vx - r), int(vy - r), int(vw + 2 * r), int(vh + 2 * r)).intersected(g)
        if area.width() < 100 or area.height() < 100:
            return None
        pm = self._grab(scr, area.x() - g.x(), area.y() - g.y(), area.width(), area.height())
        img = pm.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        img = img.scaled(area.width(), area.height())
        if img.isNull():
            return None
        data = bytes(img.constBits().asstring(img.sizeInBytes()))
        prior = self.surfaces.prior()
        if verify:
            prior = (0.0, 0.0)                    # (boxes are already where we think)
        fix = locate(data, img.width(), img.height(), img.bytesPerLine(), area.x(), area.y(),
                     boxes, r, prior=prior)
        if fix is not None:
            if not verify:
                self.surfaces.place(fix.dx, fix.dy)
            elif abs(fix.dx) > 4 or abs(fix.dy) > 4:
                self.surfaces.place(dx0 + fix.dx, dy0 + fix.dy)
        return fix
