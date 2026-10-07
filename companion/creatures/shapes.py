"""Shared parametric shape modules (used by every family).

These build pixel sets from a handful of numbers; families combine and pose
them. Heads and ears are built from per-row *spans* rather than rotated
polygons, because at 8-12 px a head must keep exact pixel shapes (eyes 1px
apart from the skull edge, a 1px ear tip) and never rotate in sub-pixel
steps — it only moves in whole pixels, the way a pixel artist would.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import dmath as m
from . import raster

Pixel = tuple[int, int]


# ---- 2D helpers --------------------------------------------------------
def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def scale(a, k):
    return (a[0] * k, a[1] * k)


def rot(v, ang):
    c, s = m.cos(ang), m.sin(ang)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def length(v):
    return (v[0] * v[0] + v[1] * v[1]) ** 0.5


def polar(ang, r):
    return (m.cos(ang) * r, m.sin(ang) * r)


def frame_point(origin, axis_ang, u, v):
    """Point at (u along axis, v perpendicular, +v = 'down' side)."""
    return add(origin, rot((u, v), axis_ang))


# ---- IK -------------------------------------------------------------------
def two_bone(root, target, l1, l2, bend: int):
    """Planar two-bone IK. ``bend`` = +1 puts the middle joint on the +x side
    of the root->target line (knee forward for a right-facing creature),
    -1 behind. Unreachable targets are clamped (leg fully extended), too-close
    targets fold to a joint limit instead of collapsing."""
    d = sub(target, root)
    dist = length(d)
    lo, hi = abs(l1 - l2) + 0.25, l1 + l2 - 0.01
    if dist < 1e-6:
        d, dist = (0.0, 1.0), 1.0
    if dist > hi or dist < lo:
        dist2 = hi if dist > hi else lo
        d = scale(d, dist2 / dist)
        dist = dist2
    # law of cosines -> distance along d to the knee foot point, and offset
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    hh = max(0.0, l1 * l1 - a * a) ** 0.5
    ux, uy = d[0] / dist, d[1] / dist
    # perpendicular; choose side so +bend points towards +x when leg is down
    px, py = -uy, ux
    if px < 0:
        px, py = -px, -py
    knee = (root[0] + ux * a + px * hh * bend, root[1] + uy * a + py * hh * bend)
    end = add(root, d)
    return knee, end


# ---- span shapes (heads, ears) --------------------------------------------
@dataclass(frozen=True)
class EarSpec:
    height: int = 4         # core rows from tip to base
    width: int = 3          # widest core row
    fold: int = 0           # 0 = upright; 1 = folded tip (drawn as a cap)
    lean: int = 0           # -1 leans back, +1 forward (shifts the tip)
    drop: int = 0           # soft ears: 1 = hang (hounds, lops), 2 = fold forward


def ear_spans(spec: EarSpec, near: bool) -> dict[int, tuple[int, int]]:
    """Ear core spans relative to the tip column (row 0 = tip row).

    The far ear shows its open inside (symmetric), the near ear is seen side-
    on: narrower, its body hugging the back of the head."""
    out = {}
    maxhalf = max(0, (spec.width - 1) // 2)
    if near:
        h = max(2, spec.height - 1)
        for i in range(h):
            grow = min(maxhalf * 2 - 1 if maxhalf > 1 else maxhalf,
                       (i * 2 * maxhalf + h - 1) // h)
            a, b = -grow, 0
            if i == h - 1 and h > 2:
                a = -max(0, grow - 1)
            out[i] = (a, b)
    else:
        h = max(2, spec.height)
        for i in range(h):
            half = min(maxhalf, (i * 2 * maxhalf + h - 1) // h)
            a, b = -half, half
            if i == h - 1 and h > 2:
                b -= 1           # base row: cut by the skull contour
            out[i] = (a, b)
    if spec.lean:
        for i in range(min(2, len(out))):
            a, b = out[i]
            out[i] = (a + spec.lean, b + spec.lean)
    if spec.fold:
        # folded: drop the tip, widen the top into a soft cap
        tip = min(out)
        a, b = out.pop(tip)
        nxt = out[tip + 1]
        out[tip + 1] = (nxt[0], nxt[1] + 1)
    return out


def ear_inner(spans: dict[int, tuple[int, int]], near: bool) -> set[tuple[int, int]]:
    """Which ear pixels show the shaded inner ear."""
    rows = sorted(spans)
    out = set()
    for k, r in enumerate(rows):
        a, b = spans[r]
        if near:
            if k >= 1 and b > a:
                out.add((a, r))
            if k == len(rows) - 1:
                out.update((x, r) for x in range(a, b + 1))
        else:
            if k >= 2:
                out.add((a, r))
                out.add((b, r))
            if k == len(rows) - 1:
                out.update((x, r) for x in range(a, b + 1))
    return out


def torso_polygon(hip, shoulder, back: float, top: float, belly: float,
                  front: float, chest: float, rump_round: float = 1.0,
                  sag: float = 0.0):
    """Boxy feline/canine torso around the spine hip->shoulder.

    Returns polygon points in sprite space. ``top``/``belly`` are distances
    above/below the spine; ``chest`` pulls the lower front corner back
    (deep chest -> slanted brisket); ``sag`` drops the belly middle."""
    d = sub(shoulder, hip)
    ln = length(d)
    ang = 0.0 if ln < 1e-6 else _atan2(d[1], d[0])
    r = rump_round
    pts_local = [
        (-back, -top + r), (-back + r, -top),
        (ln + front - 1.0, -top), (ln + front, -top + 1.0),
        (ln + front, -top + 3.0), (ln + front - chest, belly),
        (ln * 0.5, belly + sag),
        (-back + 0.5, belly),
    ]
    return [frame_point(hip, ang, u, v) for u, v in pts_local]


def _atan2(y: float, x: float) -> float:
    """Deterministic atan2 via a polynomial (|err| < 1e-5 rad), enough for
    orienting shapes; never used for pixel-exact decisions on its own."""
    if x == 0.0 and y == 0.0:
        return 0.0
    ax, ay = abs(x), abs(y)
    swap = ay > ax
    t = (ax / ay) if swap else (ay / ax)
    t2 = t * t
    r = t * (0.99997726 + t2 * (-0.33262347 + t2 * (0.19354346 + t2 * (
        -0.11643287 + t2 * (0.05265332 - t2 * 0.01172120)))))
    if swap:
        r = m.HALF_PI - r
    if x < 0:
        r = m.PI - r
    if y < 0:
        r = -r
    return r


atan2 = _atan2


def chain(base, base_ang: float, seg: float, bends: list[float]):
    """Points of a segmented appendage (tail, neck) from a base angle and a
    list of relative bends per segment."""
    pts = [base]
    a = base_ang
    p = base
    for b in bends:
        a += b
        p = add(p, polar(a, seg))
        pts.append(p)
    return pts


def stroke(points, radii, w, h):
    return raster.polyline(points, radii, w, h)
