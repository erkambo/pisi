"""Family extension point.

A *family* turns genes into an immutable built creature and renders any of
its states. To add a family, implement :class:`Family` (or reuse
:class:`QuadFamily` with your own anatomy function, schema and optional
state overrides) and call :func:`register` — the core never special-cases
species. See docs/pets/EXTENDING.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from collections.abc import Callable

from .. import coat as C
from .. import quadmotion as QM
from ..genome import Gene
from ..quadruped import QuadAnatomy, apply_tones, build_layers
from ..render import Frame, calm_contours, clean_materials, close_corners, compose


class Family(Protocol):
    name: str
    label: str
    schema: list[Gene]

    def build(self, genes: dict) -> object: ...
    def states(self, built) -> dict[str, QM.AnimSpec]: ...
    def frame(self, built, state: str, i: int, side: str) -> tuple[Frame, bool]: ...
    def speed(self, built, state: str) -> float: ...
    def coat(self, built) -> C.Coat: ...
    def repair(self, genes: dict) -> list[str]: ...


@dataclass
class QuadBuilt:
    anat: QuadAnatomy
    coat: C.Coat
    motion: QM.Motion
    head_cache: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def coat_from_genes(genes: dict) -> C.Coat:
    c, e = genes["coat"], genes["eyes"]
    left = e.get("left", "amber")
    return C.Coat(base=c.get("color", "black"), pattern=c.get("pattern", "solid"),
                  second=c.get("second", ""), white=float(c.get("white", 0.5)),
                  stripe_gap=float(c.get("stripes", 4.0)),
                  patch_scale=float(c.get("patches", 5.0)), seed=int(c.get("seed", 0)),
                  eye_left=left, eye_right=e.get("right", left) if e.get("odd") else left,
                  nose=e.get("nose", "plum"), socks=bool(c.get("socks", True)),
                  blaze=bool(c.get("blaze", False)))


def motion_from_genes(genes: dict, seed: int = 0) -> QM.Motion:
    m = genes.get("motion", {})
    t = genes.get("tail", {})
    return QM.Motion(energy=float(m.get("energy", 0.5)),
                     tail_sway=float(m.get("tail_sway", 0.5)),
                     stride=float(m.get("stride", 1.0)),
                     blink=float(m.get("blink", 0.5)),
                     curious=float(m.get("curious", 0.5)),
                     carriage=float(t.get("carry", 0.0)), seed=seed)


@dataclass
class QuadFamily:
    """Any four-legged family built on the shared quadruped plan."""
    name: str
    label: str
    schema: list[Gene]
    anatomy_fn: Callable[[dict], QuadAnatomy]
    canon: dict = field(default_factory=dict)
    vocal: str = "meow"
    state_overrides: dict = field(default_factory=dict)   # name -> (AnimSpec, fn)
    coat_fn: Callable[[dict], C.Coat] = coat_from_genes
    repair_fn: Callable[[dict], list[str]] | None = None
    presets: dict = field(default_factory=dict)          # name -> partial genes

    def repair(self, genes: dict) -> list[str]:
        return self.repair_fn(genes) if self.repair_fn else []

    def _table(self):
        t = dict(QM.STATES)
        t.update(self.state_overrides)
        return t

    def build(self, genes: dict, seed: int = 0) -> QuadBuilt:
        motion = motion_from_genes(genes, seed)
        raw = self.anatomy_fn(genes)
        key = repr((raw, motion))
        cache = self.__dict__.setdefault("_fit_cache", {})
        hit = cache.get(key)
        if hit is None:
            hit = self.fit(raw, motion)
            if len(cache) > 64:                 # bounded
                cache.clear()
            cache[key] = hit
        anat, notes = hit
        b = QuadBuilt(anat, self.coat_fn(genes), motion)
        b.notes = notes
        return b

    # states/frames that reach furthest out of the frame
    FIT_PROBES = ("sleep", "liedown", "death", "eat", "crouch", "pounce", "jump",
                  "celebrate", "run", "stretch", "dangle", "attack", "sit", "idle")

    def fit(self, a: QuadAnatomy, m: QM.Motion, tries: int = 12):
        """Bounded repair so every probed pose stays inside the frame (a 1px
        margin for the outline ring). In order of preference: shorten the
        tail, shift the whole creature sideways (same shift for every state,
        so nothing pops between animations), lower leaps, shorten ears.
        Deterministic, at most ``tries`` steps, reported as notes."""
        from dataclasses import replace as _replace
        notes: list[str] = []
        table = self._table()
        seg0 = a.tail_seg
        for _ in range(tries):
            left = right = top = False
            for name in self.FIT_PROBES:
                if name not in table:
                    continue
                spec, fn = table[name]
                for i in range(spec.frames):
                    p = fn(a, m, i, spec.frames)
                    layers, _t = build_layers(a, p, lambda *_: 0)
                    for ly in layers:
                        for (x, y) in ly.pixels:
                            if x <= 0:
                                left = True
                            elif x >= a.w - 1:
                                right = True
                            if y <= 0:
                                top = True
            if not (left or right or top):
                return a, notes
            if left and right:
                a = _replace(a, tail_seg=a.tail_seg * 0.9)
                notes.append("tail shortened to fit the frame")
            elif left:
                if a.tail_seg > seg0 * 0.7:
                    a = _replace(a, tail_seg=a.tail_seg * 0.9)
                    notes.append("tail shortened to fit the frame")
                else:
                    a = _shift(a, 1.0)
                    notes.append("moved right to fit the frame")
            elif right:
                a = _shift(a, -1.0)
                notes.append("moved left to fit the frame")
            if top:
                if a.leap > 0.45:
                    a = _replace(a, leap=a.leap * 0.8)
                    notes.append("jumps lowered to fit the frame")
                elif a.head.ear.height > 3:
                    ear = _replace(a.head.ear, height=a.head.ear.height - 1)
                    a = _replace(a, head=_replace(a.head, ear=ear))
                    notes.append("ears shortened to fit the frame")
        return a, notes

    def states(self, built=None) -> dict[str, QM.AnimSpec]:
        return {k: v[0] for k, v in self._table().items()}

    def pose(self, built: QuadBuilt, state: str, i: int):
        spec, fn = self._table()[state]
        return fn(built.anat, built.motion, i % spec.frames, spec.frames)

    def frame(self, built: QuadBuilt, state: str, i: int, side: str = "L"
              ) -> tuple[Frame, bool]:
        p = self.pose(built, state, i)
        coat = built.coat
        if p.flip:                       # first half of a turn: other flank
            side = "R" if side == "L" else "L"

        def mat(region, x, y, info):
            return C.material(coat, region, x, y, info)
        layers, tones = build_layers(built.anat, p, mat, built.head_cache, side)
        fr = compose(layers, built.anat.w, built.anat.h)
        apply_tones(fr, tones)
        face = set()
        for ly in layers:
            if ly.name in ("head", "ear_flap"):
                for (x, y) in ly.pixels:
                    face.update(((x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
        calm_contours(fr, face)
        close_corners(fr)
        clean_materials(fr)
        fr.flip = p.flip
        return fr, p.flash

    def speed(self, built: QuadBuilt, state: str) -> float:
        spec, fn = self._table()[state]
        sp = getattr(fn, "speed", None)          # locomotion clips carry one
        return sp(built.anat, built.motion, spec.frames) if sp else 0.0

    def coat(self, built: QuadBuilt) -> C.Coat:
        return built.coat

    def rig(self, built: QuadBuilt, state: str, i: int) -> dict:
        """Debug overlay for the editor: line segments (bones, tail) and
        contact points, in sprite space facing right."""
        from .. import quadruped as Q
        p = self.pose(built, state, i)
        a = built.anat
        bones, contacts = [(p.hip, p.shoulder, "spine")], []
        for leg in Q.LEGS:
            if leg in p.hidden or leg in p.paw_only:
                continue
            root, knee, ankle = Q.leg_points(a, p, leg)
            kind = "near" if a.legs[leg].near else "far"
            bones += [(root, knee, kind), (knee, ankle, kind)]
            planted = ankle[1] >= a.ground - (0 if a.legs[leg].near else 0.6) - 0.01
            contacts.append(((ankle[0], ankle[1] + 2.5), planted))
        tp = Q.tail_points(a, p)
        bones += [(tp[k], tp[k + 1], "tail") for k in range(len(tp) - 1)]
        return {"bones": bones, "contacts": contacts, "ground": a.ground + 3}

    def anchors(self, built: QuadBuilt, state: str, i: int) -> dict:
        """Mouth, head top, paws and floor row for this frame, facing right
        (see quadruped.anchors)."""
        from .. import quadruped as Q
        p = self.pose(built, state, i)
        out = Q.anchors(built.anat, p, built.head_cache)
        out["flip"] = p.flip
        return out

    def numbers(self, built: QuadBuilt, state: str, i: int) -> list[float]:
        """Every continuous pose value (for finiteness checks)."""
        p = self.pose(built, state, i)
        vals = [*p.hip, *p.shoulder, p.tail_ang, *p.tail_bends]
        for v in p.feet.values():
            vals += list(v)
        return vals


def _shift(a: QuadAnatomy, dx: float) -> QuadAnatomy:
    from dataclasses import replace as _replace
    return _replace(a, hip=(a.hip[0] + dx, a.hip[1]),
                    shoulder=(a.shoulder[0] + dx, a.shoulder[1]))


REGISTRY: dict[str, Family] = {}


def register(fam: Family) -> None:
    REGISTRY[fam.name] = fam
