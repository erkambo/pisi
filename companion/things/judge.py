"""The judging pipeline: nothing ships unless it passes, on every panel cat.

Gates, in order (the first three are automatic and hard; ``review`` and
``inuse`` sheets go to a person):

1. **pixels** - each image on its own: a closed outline (every opaque pixel
   touching the outside is an outline pixel), no stray single pixels, at
   most ``MAX_COLOURS`` colours, outlines the darkest tone of their material.
2. **wallpapers** - the thing's silhouette still separates from a light and
   from a dark wallpaper.
3. **in use** - per kind (``kinds.<kind>.check``) for *every* panel cat:
   e.g. a bed: the cat lies exactly on the cushion, stays between the bed's
   ends in every frame, its face is never covered, and it doesn't vanish
   into the bed's colours.

``judge(kind, design, cats)`` returns a :class:`Report`; ``passed`` is True
only if there are no failures (warnings are listed for the reviewer).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..creatures import api
from ..creatures.render import OUTLINE
from . import fit as F
from .draw import Rendered
from .kinds import KINDS
from .palette import contrast

MAX_COLOURS = 12
LIGHT_BG = (232, 236, 232)
DARK_BG = (36, 40, 46)


@dataclass
class Finding:
    gate: str
    level: str            # "fail" | "warn"
    cat: str
    message: str


@dataclass
class Report:
    kind: str
    design: dict
    findings: list[Finding] = field(default_factory=list)
    cats: int = 0

    @property
    def passed(self) -> bool:
        return not any(f.level == "fail" for f in self.findings)

    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "fail"]

    def summary(self) -> str:
        n_fail = len(self.fails())
        n_warn = len(self.findings) - n_fail
        state = "PASS" if self.passed else "FAIL"
        return f"{state} {self.kind} {self.design}: {self.cats} cats, {n_fail} fails, {n_warn} warnings"


# ---- gate 1: pixels -----------------------------------------------------------
def pixel_gate(r: Rendered, cat: str, out: list[Finding]) -> None:
    for name, rgba, fr in (("back", r.back, r.back_frame), ("front", r.front, r.front_frame)):
        if rgba is None or fr is None:
            continue
        w, h = fr.w, fr.h
        role = fr.role

        def on(x, y, w=w, h=h, role=role):
            return 0 <= x < w and 0 <= y < h and role[y * w + x] != 0
        colours = set()
        for y in range(h):
            for x in range(w):
                i = y * w + x
                if not role[i]:
                    continue
                colours.add(rgba[i * 4:i * 4 + 4])
                n4 = [on(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
                if not any(n4):
                    out.append(Finding("pixels", "fail", cat, f"{name}: stray pixel at {x},{y}"))
                if not all(n4) and role[i] != OUTLINE:
                    out.append(Finding("pixels", "fail", cat,
                                       f"{name}: open outline at {x},{y}"))
                    return
        if len(colours) > MAX_COLOURS:
            out.append(Finding("pixels", "fail", cat, f"{name}: {len(colours)} colours"))


# ---- gate 2: wallpapers ------------------------------------------------------------
def wallpaper_gate(r: Rendered, cat: str, out: list[Finding]) -> None:
    """The edge of the silhouette (outline next to its fill) must stand out
    from at least one of: the outline itself, or the fill just inside it."""
    fr = r.back_frame
    if fr is None:
        return
    w = fr.w
    edge = []
    for i, ro in enumerate(fr.role):
        if ro == OUTLINE:
            edge.append(tuple(r.back[i * 4:i * 4 + 3]))
    if not edge:
        return
    fills = []
    for i, ro in enumerate(fr.role):
        if ro and ro != OUTLINE:
            x, y = i % w, i // w
            if any(fr.role[(y + dy) * w + x + dx] == OUTLINE
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                   if 0 <= x + dx < w and 0 <= y + dy < fr.h):
                fills.append(tuple(r.back[i * 4:i * 4 + 3]))
    for bg, label in ((LIGHT_BG, "light"), (DARK_BG, "dark")):
        best = max([contrast(c, bg) for c in edge] + [contrast(c, bg) for c in fills])
        if best < 1.6:
            out.append(Finding("wallpaper", "fail", cat,
                               f"disappears on a {label} wallpaper (best contrast {best:.2f})"))


# ---- the pipeline -----------------------------------------------------------------
def judge(kind: str, design: dict, cats: list[tuple[str, object]] | None = None) -> Report:
    from ..creatures import panel
    cats = cats if cats is not None else panel.panel()
    mod = KINDS[kind]
    rep = Report(kind, dict(design))
    for label, g in cats:
        pet = api.Creature(g)
        ft = F.measure(pet)
        r = mod.render(design, ft)
        pixel_gate(r, label, rep.findings)           # sizes change with the cat
        wallpaper_gate(r, label, rep.findings)
        check = getattr(mod, "check", None)
        if check:
            for level, msg in check(r, pet, ft):
                rep.findings.append(Finding("inuse", level, label, msg))
        rep.cats += 1
    return rep


# ---- gate 4: variety (within one kind, things must look different) ------------------
VARIETY_DE = 10.0     # mean perceptual difference below which two things are "the same"


def difference(a: Rendered, b: Rendered) -> float:
    """Mean perceptual difference between two things' back+front images,
    aligned bottom-centre (a pixel only one of them has counts as 100)."""
    from .palette import delta_e
    W, H = max(a.w, b.w), max(a.h, b.h)

    def flat(r: Rendered):
        img = {}
        ox, oy = (W - r.w) // 2, H - r.h
        for data in (r.back, r.front):
            if data is None:
                continue
            for i in range(r.w * r.h):
                if data[i * 4 + 3]:
                    img[(i % r.w + ox, i // r.w + oy)] = tuple(data[i * 4:i * 4 + 3])
        return img
    fa, fb = flat(a), flat(b)
    keys = set(fa) | set(fb)
    tot = 0.0
    for k in keys:
        if k in fa and k in fb:
            tot += delta_e(fa[k], fb[k])
        else:
            tot += 100.0
    return tot / max(1, len(keys))


def variety_gate(rendered: list[tuple[str, Rendered]]) -> list[Finding]:
    out = []
    for i, (na, ra) in enumerate(rendered):
        for nb, rb in rendered[i + 1:]:
            if ra.kind != rb.kind:
                continue
            d = difference(ra, rb)
            if d < VARIETY_DE:
                out.append(Finding("variety", "fail", "canon",
                                   f"{na} and {nb} look the same (difference {d:.1f})"))
    return out
