"""Compose posed layers into one pixel frame, then colour it.

A family turns a pose into a list of :class:`Layer` s (pixel sets with a
depth, a draw group and a material function). The renderer is family-
agnostic and implements PISI's house style:

* each *group* (e.g. the far legs, then the main body) gets a 1px 4-neighbour
  outline ring around the union of its layers, so parts of one group join
  seamlessly while a group in front draws a clean contour over the one behind;
* a layer can ask for a partial *seam*: its own contour drawn inside the
  group, but only away from its joint (the thigh line on a cat's flank that
  fades out towards the hip);
* per-pixel overrides stamp face features, inner-ear shading, etc.

Output is a role/material grid; :func:`colorize` maps it to RGBA with a
palette, so recolouring never re-poses or re-rasterises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

from .raster import ring

# tones of a coat material
EMPTY, FILL, SHADE, OUTLINE = 0, 1, 2, 3
# fixed feature roles (not affected by coat pattern)
EYE_FAR, EYE_FAR_SHADE, EYE_NEAR, EYE_NEAR_SHADE = 10, 11, 12, 13
GLINT, NOSE, MOUTH, MOUTH_DARK, TONGUE, TEETH = 14, 15, 16, 17, 18, 19
FX_WHITE, INNER_EAR, LID = 20, 21, 22
CLAW, BEAK, BEAK_SHADE = 23, 24, 25

Pixel = tuple[int, int]


@dataclass
class Layer:
    name: str
    pixels: set[Pixel]
    z: int = 0
    group: int = 1                      # lower groups are drawn first, behind
    tone: int = FILL
    material: Callable[[int, int], int] | int = 0
    seam_from: tuple[float, float] | None = None
    seam_min: float = 0.0
    seam_dy: float = 0.0          # seam only at/below seam_from.y + seam_dy
    seam_side: int = 0            # +1: only in front of the joint, -1 behind
    overrides: dict[Pixel, int] = field(default_factory=dict)
    # tone-only overrides keep the coat material (e.g. a shade stroke)
    tone_overrides: dict[Pixel, int] = field(default_factory=dict)


class Frame:
    """w*h grid of (role, material). role is a tone (FILL/SHADE/OUTLINE) or a
    fixed feature role."""
    __slots__ = ("w", "h", "role", "mat", "clipped", "flip")

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.role = bytearray(w * h)
        self.mat = bytearray(w * h)
        self.clipped = False
        self.flip = False

    def get(self, x: int, y: int) -> int:
        return self.role[y * self.w + x]

    def opaque_box(self) -> tuple[int, int, int, int] | None:
        xs, ys = [], []
        w = self.w
        for i, r in enumerate(self.role):
            if r:
                xs.append(i % w)
                ys.append(i // w)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)


def _mat_of(layer: Layer, x: int, y: int) -> int:
    m = layer.material
    return m(x, y) if callable(m) else m


def compose(layers: list[Layer], w: int, h: int) -> Frame:
    fr = Frame(w, h)
    role, mat = fr.role, fr.mat
    groups: dict[int, list[Layer]] = {}
    for ly in layers:
        groups.setdefault(ly.group, []).append(ly)
    for g in sorted(groups):
        lys = sorted(groups[g], key=lambda l: l.z)
        union: set[Pixel] = set()
        owner: dict[Pixel, Layer] = {}
        for ly in lys:
            for p in ly.pixels:
                if 0 <= p[0] < w and 0 <= p[1] < h:
                    union.add(p)
                    owner[p] = ly
                else:
                    fr.clipped = True
        # outline ring around the whole group; its colour follows the coat
        # material of the neighbouring core pixel
        for p in ring(union, w, h):
            x, y = p
            src = None
            for q in ((x, y + 1), (x, y - 1), (x - 1, y), (x + 1, y)):
                if q in owner:
                    src = q
                    break
            i = y * w + x
            role[i] = OUTLINE
            mat[i] = _mat_of(owner[src], *src) if src else 0
        if any(x <= 0 or y <= 0 or x >= w - 1 for x, y in union):
            fr.clipped = True
        for ly in lys:
            for (x, y) in ly.pixels:
                if 0 <= x < w and 0 <= y < h:
                    i = y * w + x
                    role[i] = ly.tone
                    mat[i] = _mat_of(ly, x, y)
        # partial seams: a layer's contour drawn over its own group
        for ly in lys:
            if ly.seam_from is None:
                continue
            sx, sy = ly.seam_from
            mm = ly.seam_min * ly.seam_min
            for (x, y) in ring(ly.pixels, w, h):
                if y + 0.5 < sy + ly.seam_dy:
                    continue
                if ly.seam_side and (x + 0.5 - sx) * ly.seam_side < 0:
                    continue
                if (x, y) in union and (x + 0.5 - sx) ** 2 + (y + 0.5 - sy) ** 2 >= mm:
                    o = owner[(x, y)]
                    if o is not ly and o.z <= ly.z:
                        i = y * w + x
                        role[i] = OUTLINE
                        mat[i] = _mat_of(ly, x, y) if (x, y) in ly.pixels else mat[i]
        for ly in lys:
            for (x, y), t in ly.tone_overrides.items():
                if 0 <= x < w and 0 <= y < h and owner.get((x, y)) is ly:
                    role[y * w + x] = t
            for (x, y), r in ly.overrides.items():
                if 0 <= x < w and 0 <= y < h:
                    o = owner.get((x, y))
                    if o is None or o is ly or o.z <= ly.z:
                        i = y * w + x
                        role[i] = r
                        if r in (FILL, SHADE, OUTLINE) and o is None:
                            mat[i] = _mat_of(ly, x, y)
    return fr


def close_corners(fr: Frame) -> None:
    """House-style contour fix: an empty pixel diagonally below-right of a
    core pixel, with outline left of, above and below it (or the frame
    bottom), becomes outline. Closes the front of a paw on the ground line
    and the notch behind the near ear. Facing is always +x when this runs."""
    w, h, role = fr.w, fr.h, fr.role
    add = []
    for y in range(1, h):
        for x in range(1, w):
            i = y * w + x
            if role[i]:
                continue
            below = role[i + w] if y + 1 < h else OUTLINE
            if (role[i - 1] == OUTLINE and role[i - w] == OUTLINE
                    and below == OUTLINE
                    and role[i - w - 1] not in (EMPTY, OUTLINE)):
                add.append(i)
    for i in add:
        role[i] = OUTLINE
        fr.mat[i] = fr.mat[i - 1]


def calm_contours(fr: Frame, protect: set | None = None, max_len: int = 2) -> int:
    """Busyness control: interior contour fragments (outline pixels with no
    transparent 4-neighbour, 8-connected) of ``max_len`` px or fewer read as
    noise at 1×, so they become fill again with their neighbours' tone and
    material. ``protect`` (e.g. the face) is left alone. Returns pixels
    changed."""
    w, h, role, mat = fr.w, fr.h, fr.role, fr.mat
    protect = protect or set()
    interior = set()
    for k in range(w * h):
        if role[k] != OUTLINE:
            continue
        x, y = k % w, k // w
        if (x, y) in protect or x in (0, w - 1) or y in (0, h - 1):
            continue
        if role[k - 1] and role[k + 1] and role[k - w] and role[k + w]:
            interior.add((x, y))
    seen: set = set()
    changed = 0
    for p in interior:
        if p in seen:
            continue
        comp, stack = [], [p]
        seen.add(p)
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in interior and q not in seen:
                        seen.add(q)
                        stack.append(q)
        if len(comp) > max_len:
            continue
        # a fragment touching the outer silhouette ring is a seam ending,
        # which the artist draws too; only free-floating bits go
        for x, y in comp:
            k = y * w + x
            nb = [(role[j], mat[j]) for j in (k - 1, k + 1, k - w, k + w)
                  if role[j] in (FILL, SHADE)]
            if not nb:
                continue
            tone, m_ = max(set(nb), key=nb.count)
            role[k], mat[k] = tone, m_
            changed += 1
    return changed


def clean_materials(fr: Frame) -> None:
    """Pattern hygiene: a coat pixel whose material differs from all of its
    (>=3) coat-coloured 4-neighbours takes their most common material — no
    lone stray pattern pixels ("pixel noise")."""
    w, h, role, mat = fr.w, fr.h, fr.role, fr.mat
    fixes = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            if role[i] not in (FILL, SHADE):
                continue
            mine = mat[i]
            nb = []
            for j in (i - 1, i + 1, i - w, i + w):
                if role[j] in (FILL, SHADE):
                    nb.append(mat[j])
            if len(nb) >= 3 and mine not in nb:
                fixes.append((i, max(set(nb), key=nb.count)))
    for i, m_ in fixes:
        mat[i] = m_


RGBA = tuple[int, int, int, int]


@dataclass
class Palette:
    """Colours per (material, tone) plus fixed feature roles."""
    tones: dict[tuple[int, int], RGBA]
    roles: dict[int, RGBA]

    def color(self, role: int, mat: int) -> RGBA:
        if role in (FILL, SHADE, OUTLINE):
            c = self.tones.get((mat, role))
            if c is None:
                c = self.tones[(0, role)]
            return c
        return self.roles.get(role, (255, 0, 255, 255))


def colorize(fr: Frame, pal: Palette) -> bytes:
    """Frame -> straight RGBA bytes (row-major)."""
    out = bytearray(fr.w * fr.h * 4)
    cache: dict[tuple[int, int], RGBA] = {}
    for i in range(fr.w * fr.h):
        r = fr.role[i]
        if not r:
            continue
        key = (r, fr.mat[i])
        c = cache.get(key)
        if c is None:
            c = cache[key] = pal.color(r, fr.mat[i])
        j = i * 4
        out[j:j + 4] = bytes(c)
    return bytes(out)


def mirror_rgba(data: bytes, w: int, h: int) -> bytes:
    """Flip an RGBA frame horizontally (C-speed via 32-bit arrays)."""
    from array import array
    out = bytearray()
    stride = w * 4
    for y in range(h):
        row = array("I")
        row.frombytes(data[y * stride:(y + 1) * stride])
        row.reverse()
        out += row.tobytes()
    return bytes(out)
