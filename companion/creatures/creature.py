"""Public API: genome -> creature -> frames.

    from companion.creatures import api
    g = api.new_genome("feline", seed=42)
    pet = api.Creature(g)
    rgba = pet.frame("walk", 3, facing=1)       # bytes, pet.size = (48, 48)
    baked = pet.bake()                          # every state, both facings

Nothing here depends on Qt. Frames are straight RGBA bytes; facing=-1 frames
are rendered for the *other flank* and then mirrored, so asymmetric markings
and odd eyes land on the correct side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

from . import coat as C
from .families import REGISTRY
from .genome import GENERATOR, Genome, GenomeError, defaults, roll
from .render import FILL, OUTLINE, SHADE, Frame, Palette, colorize, mirror_rgba


def family(name: str):
    try:
        return REGISTRY[name]
    except KeyError:
        raise GenomeError(f"unknown pet family {name!r}") from None


def schemas() -> dict:
    return {k: f.schema for k, f in REGISTRY.items()}


def new_genome(fam: str, seed: int, base: Genome | None = None,
               locked: frozenset[str] | set[str] = frozenset()) -> Genome:
    """Roll a genome for ``seed``; with ``base`` + ``locked`` keeps the locked
    gene groups (``"coat"``) or single genes (``"coat.color"``)."""
    f = family(fam)
    genes = roll(f.schema, seed, base.genes if base else None, locked)
    notes = f.repair(genes)
    g = Genome(fam, seed, genes)
    g.notes = notes
    return g


DEFAULT_FAMILY = "feline"      # the app's default pet (PISI is a cat)


def canon_genome(fam: str = DEFAULT_FAMILY) -> Genome:
    """The family's reference look (for cats: PISI's tuxedo)."""
    f = family(fam)
    genes = defaults(f.schema)
    for group, vals in getattr(f, "canon", {}).items():
        genes.setdefault(group, {}).update(vals)
    return Genome(fam, 0, genes, name="")


def classic_genome() -> Genome:
    """PISI's black cat from before 1.0: the usual build in the "Black" coat.
    Kept for people who chose that look ("original" in older settings)."""
    f = family(DEFAULT_FAMILY)
    genes = defaults(f.schema)
    for group, vals in f.presets["Black"].items():
        genes[group].update(vals)
    return Genome(DEFAULT_FAMILY, 0, genes, name="")


def _flash_palette(p: Palette) -> Palette:
    red = {(0, FILL): (232, 68, 68, 255), (0, SHADE): (200, 50, 50, 255),
           (0, OUTLINE): (120, 24, 24, 255)}
    tones = {k: red[(0, k[1])] for k in p.tones}
    tones.update(red)
    return Palette(tones, {k: red[(0, FILL)] for k in p.roles})


class Creature:
    """An immutable built pet: anatomy, coat and motion are derived once from
    the genome; frames are posed and rasterised on demand."""

    def __init__(self, genome: Genome) -> None:
        self.genome = genome
        self.fam = family(genome.family)
        self.built = self.fam.build(genome.genes, genome.seed)
        a = self.built.anat
        self.size = (a.w, a.h)
        if hasattr(self.fam, "palette"):          # a body plan with its own coat rules
            self._pal = {s: self.fam.palette(self.built, s) for s in ("L", "R")}
        else:
            self._pal = {s: C.palette(self.fam.coat(self.built), s) for s in ("L", "R")}
        self._flash = {s: _flash_palette(p) for s, p in self._pal.items()}

    # -- introspection
    def states(self) -> dict:
        return self.fam.states(self.built)

    def speed(self, state: str) -> float:
        return self.fam.speed(self.built, state)

    # -- rendering
    def frame_grid(self, state: str, i: int, facing: int = 1) -> tuple[Frame, bool]:
        side = "L" if facing >= 0 else "R"
        return self.fam.frame(self.built, state, i, side)

    def frame(self, state: str, i: int, facing: int = 1) -> bytes:
        side = "L" if facing >= 0 else "R"
        fr, flash = self.fam.frame(self.built, state, i, side)
        if fr.flip:                      # e.g. the first half of a turn
            facing, side = -facing, ("R" if side == "L" else "L")
        pal = (self._flash if flash else self._pal)[side]
        data = colorize(fr, pal)
        if facing < 0:
            data = mirror_rgba(data, fr.w, fr.h)
        return data

    def anchors(self, state: str, i: int, facing: int = 1) -> dict:
        """Where the mouth, head top and paws are in ``frame(state, i,
        facing)``, as pixel coordinates in that frame (so a toy can be held
        in the mouth or a paw put on a scratching post, whatever the cat's
        shape). Families without anchors return an empty dict."""
        fn = getattr(self.fam, "anchors", None)
        if fn is None:
            return {}
        an = fn(self.built, state, i)
        mirrored = (facing < 0) != bool(an.pop("flip", False))
        if not mirrored:
            return an
        w = self.size[0]

        def mx(pt):
            return None if pt is None else (w - 1 - pt[0], pt[1])
        return {"ground": an["ground"], "mouth": mx(an["mouth"]),
                "head_top": mx(an["head_top"]),
                "paws": {k: mx(v) for k, v in an["paws"].items()}}

    def bake(self, states: list[str] | None = None, facings=(1, -1),
             cancelled: Callable[[], bool] | None = None,
             progress: Callable[[int, int], None] | None = None) -> Baked:
        specs = self.states()
        names = states or list(specs)
        total = sum(specs[n].frames for n in names) * len(facings)
        done = 0
        out = Baked(self.genome.key(), self.size, GENERATOR)
        for fc in facings:
            for name in names:
                spec = specs[name]
                frames = []
                for i in range(spec.frames):
                    if cancelled and cancelled():
                        raise BakeCancelled()
                    frames.append(self.frame(name, i, fc))
                    an = self.anchors(name, i, fc)
                    if an:
                        out.anchors.setdefault(fc, {}).setdefault(name, []).append(an)
                    done += 1
                    if progress and done % 16 == 0:
                        progress(done, total)
                out.frames.setdefault(fc, {})[name] = frames
        for name in names:
            spec = specs[name]
            out.fps[name] = spec.fps
            out.loop[name] = spec.loop
            out.hold_last[name] = spec.hold_last
            sp = self.speed(name)
            if sp:
                out.speed[name] = sp
        if progress:
            progress(total, total)
        return out


class BakeCancelled(Exception):
    pass


@dataclass
class Baked:
    """Every frame of every state for both facings (RGBA bytes)."""
    key: str
    size: tuple[int, int]
    generator: int
    frames: dict[int, dict[str, list[bytes]]] = field(default_factory=dict)
    fps: dict[str, float] = field(default_factory=dict)
    loop: dict[str, bool] = field(default_factory=dict)
    hold_last: dict[str, bool] = field(default_factory=dict)
    speed: dict[str, float] = field(default_factory=dict)
    anchors: dict[int, dict[str, list[dict]]] = field(default_factory=dict)

    def nbytes(self) -> int:
        return sum(len(b) for d in self.frames.values() for fr in d.values() for b in fr)
