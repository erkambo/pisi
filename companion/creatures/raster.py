"""Pixel rasterisation onto one shared low-res grid.

Shapes are sampled at pixel centres (x+0.5, y+0.5) with plain float
arithmetic on snapped coordinates, so results are deterministic. Every shape
returns the *set of covered pixels*; the renderer composes those sets by
depth, adds the outline ring and colours by role.

Conventions: y grows downwards, the ground line is the bottom row of the
frame, a creature faces +x ("right") in its own space.
"""
from __future__ import annotations

from .dmath import snap

Pixel = tuple[int, int]


def _bbox(points, pad: float, w: int, h: int):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0 = max(0, int(min(xs) - pad) - 1)
    y0 = max(0, int(min(ys) - pad) - 1)
    x1 = min(w - 1, int(max(xs) + pad) + 1)
    y1 = min(h - 1, int(max(ys) + pad) + 1)
    return x0, y0, x1, y1


def polygon(pts: list[tuple[float, float]], w: int, h: int) -> set[Pixel]:
    """Pixels whose centre is inside the polygon (even-odd rule)."""
    pts = [(snap(x), snap(y)) for x, y in pts]
    out: set[Pixel] = set()
    if len(pts) < 3:
        return out
    x0, y0, x1, y1 = _bbox(pts, 0, w, h)
    n = len(pts)
    for y in range(y0, y1 + 1):
        cy = y + 0.5
        xs = []
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            if (ay <= cy < by) or (by <= cy < ay):
                xs.append(ax + (cy - ay) * (bx - ax) / (by - ay))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            lo, hi = xs[i], xs[i + 1]
            for x in range(max(x0, int(lo) - 1), min(x1, int(hi) + 1) + 1):
                if lo <= x + 0.5 < hi:
                    out.add((x, y))
    return out


def capsule(a: tuple[float, float], b: tuple[float, float], ra: float,
            rb: float, w: int, h: int) -> set[Pixel]:
    """Tapered stroke from a (radius ra) to b (radius rb): pixel centres
    within the interpolated radius of the segment."""
    ax, ay = snap(a[0]), snap(a[1])
    bx, by = snap(b[0]), snap(b[1])
    out: set[Pixel] = set()
    x0, y0, x1, y1 = _bbox([(ax, ay), (bx, by)], max(ra, rb), w, h)
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    for y in range(y0, y1 + 1):
        cy = y + 0.5
        for x in range(x0, x1 + 1):
            cx = x + 0.5
            if ll > 1e-9:
                t = ((cx - ax) * dx + (cy - ay) * dy) / ll
                t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
            else:
                t = 0.0
            px, py = ax + dx * t - cx, ay + dy * t - cy
            r = ra + (rb - ra) * t
            if px * px + py * py <= r * r + 1e-6:
                out.add((x, y))
    return out


def polyline(points: list[tuple[float, float]], radii: list[float],
             w: int, h: int) -> set[Pixel]:
    out: set[Pixel] = set()
    for i in range(len(points) - 1):
        out |= capsule(points[i], points[i + 1], radii[i], radii[i + 1], w, h)
    return out


def ellipse(c: tuple[float, float], rx: float, ry: float,
            w: int, h: int) -> set[Pixel]:
    cx0, cy0 = snap(c[0]), snap(c[1])
    out: set[Pixel] = set()
    x0, y0, x1, y1 = _bbox([(cx0, cy0)], max(rx, ry), w, h)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            u = (x + 0.5 - cx0) / rx
            v = (y + 0.5 - cy0) / ry
            if u * u + v * v <= 1.0 + 1e-6:
                out.add((x, y))
    return out


N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def ring(core: set[Pixel], w: int, h: int) -> set[Pixel]:
    """4-neighbour outline ring just outside ``core`` (diagonal steps stay
    one pixel thin)."""
    out: set[Pixel] = set()
    for x, y in core:
        for dx, dy in N4:
            q = (x + dx, y + dy)
            if q not in core and 0 <= q[0] < w and 0 <= q[1] < h:
                out.add(q)
    return out


def thin_line(points: list[tuple[float, float]], w: int, h: int) -> set[Pixel]:
    """Connected 1px line through the points: per step along the major axis
    take the pixel whose centre is nearest the line (clean pixel-art steps,
    never a gap, never a double pixel)."""
    out: set[Pixel] = set()
    for i in range(len(points) - 1):
        ax, ay = snap(points[i][0]), snap(points[i][1])
        bx, by = snap(points[i + 1][0]), snap(points[i + 1][1])
        dx, dy = bx - ax, by - ay
        if abs(dy) >= abs(dx):
            y0, y1 = int(ay // 1), int((by - 1e-9) // 1) if by > ay else int(by // 1)
            lo, hi = (y0, y1) if y0 <= y1 else (y1, y0)
            for y in range(lo, hi + 1):
                cy = y + 0.5
                t = 0.0 if abs(dy) < 1e-9 else (cy - ay) / dy
                t = 0.0 if t < 0 else 1.0 if t > 1 else t
                x = int((ax + dx * t) // 1)
                if 0 <= x < w and 0 <= y < h:
                    out.add((x, y))
        else:
            x0, x1 = int(ax // 1), int(bx // 1)
            lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)
            for x in range(lo, hi + 1):
                cx = x + 0.5
                t = (cx - ax) / dx
                t = 0.0 if t < 0 else 1.0 if t > 1 else t
                y = int((ay + dy * t) // 1)
                if 0 <= x < w and 0 <= y < h:
                    out.add((x, y))
    return out
