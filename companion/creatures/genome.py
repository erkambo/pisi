"""The versioned creature genome.

A genome is plain data: a family name, a seed (provenance) and explicit
*gene values* grouped by aspect. Rendering depends only on the genes and the
generator version — never on the seed directly — so a saved pet looks the
same forever, and the seed only matters when (re)rolling genes.

JSON shape (``FORMAT`` / ``VERSION`` below)::

    {
      "format": "pisi-creature",
      "version": 1,
      "generator": 1,
      "family": "feline",
      "seed": 1234,
      "name": "Mochi",
      "genes": {"body": {...}, "head": {...}, "tail": {...},
                "coat": {...}, "eyes": {...}, "motion": {...}}
    }

Every gene is described by a :class:`Gene` in the family schema (range,
default, group). Each gene draws from its *own* random stream derived from
``(seed, group, name)``, so adding a gene in a later version never shifts
the others, and re-rolling the coat never touches the anatomy.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

from .rng import Rng, derive_seed

FORMAT = "pisi-creature"
VERSION = 1                 # genome JSON schema version
GENERATOR = 8               # bump when the same genes would render differently
                            # (or the baked set of states/anchors changes)

MAX_SEED = (1 << 63) - 1


class GenomeError(ValueError):
    """Raised for genomes that can't be used (with a user-facing message)."""


@dataclass(frozen=True)
class Gene:
    group: str                    # body | head | ears | tail | coat | eyes | motion
    name: str
    kind: str                     # "float" | "int" | "choice" | "bool" | "seed"
    default: Any
    lo: float = 0.0
    hi: float = 1.0
    choices: tuple = ()
    weights: tuple = ()           # for "choice": relative odds when rolling
    spread: float = 1.0           # 0..1: how far a random roll strays from default
    label: str = ""
    doc: str = ""

    def clamp(self, v: Any) -> Any:
        if self.kind == "seed":
            return int(v) % (int(self.hi) + 1)
        if self.kind == "float":
            v = float(v)
            if v != v:                         # NaN
                return self.default
            return min(self.hi, max(self.lo, v))
        if self.kind == "int":
            return int(min(self.hi, max(self.lo, int(round(float(v))))))
        if self.kind == "bool":
            return bool(v)
        if self.kind == "choice":
            return v if v in self.choices else self.default
        return v

    def roll(self, rng: Rng) -> Any:
        if self.kind == "seed":
            return rng.randint(int(self.lo), int(self.hi))
        if self.kind == "choice":
            ws = self.weights or tuple(1.0 for _ in self.choices)
            return rng.weighted(list(zip(self.choices, ws)))
        if self.kind == "bool":
            p = self.weights[0] if self.weights else 0.5
            return rng.chance(p)
        lo, hi = float(self.lo), float(self.hi)
        d = float(self.default)
        # bell-shaped around the default, scaled to the side's range
        c = rng.centered(1.0)
        v = d + c * self.spread * ((hi - d) if c > 0 else (d - lo))
        return self.clamp(v)

    def mutate(self, v: Any, rng: Rng, strength: float) -> Any:
        if self.kind == "seed":
            return self.roll(rng) if rng.chance(strength * 0.5) else v
        if self.kind in ("choice", "bool"):
            return self.roll(rng) if rng.chance(strength * 0.35) else v
        span = float(self.hi) - float(self.lo)
        nv = float(v) + rng.centered(1.0) * span * 0.5 * strength
        return self.clamp(nv)


@dataclass
class Genome:
    family: str
    seed: int
    genes: dict[str, dict[str, Any]]
    name: str = ""
    generator: int = GENERATOR
    version: int = VERSION
    notes: list = field(default_factory=list, compare=False, repr=False)

    def get(self, group: str, name: str, default: Any = None) -> Any:
        return self.genes.get(group, {}).get(name, default)

    def copy(self) -> Genome:
        return Genome(self.family, self.seed, copy.deepcopy(self.genes),
                      self.name, self.generator, self.version)

    def key(self) -> str:
        """Stable identity of the *look* (for caches): genes + versions."""
        return json.dumps({"f": self.family, "g": self.genes,
                           "v": self.generator}, sort_keys=True,
                          separators=(",", ":"))

    def to_dict(self) -> dict:
        return {"format": FORMAT, "version": self.version,
                "generator": self.generator, "family": self.family,
                "seed": self.seed, "name": self.name,
                "genes": copy.deepcopy(self.genes)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


# ---- schema helpers ---------------------------------------------------------
Schema = list[Gene]


def defaults(schema: Schema) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for g in schema:
        out.setdefault(g.group, {})[g.name] = g.default
    return out


def roll(schema: Schema, seed: int, base: dict | None = None,
         locked: set[str] | frozenset = frozenset()) -> dict:
    """Roll genes for ``seed``. Genes in ``locked`` groups (or individual
    "group.name" keys) keep their value from ``base``."""
    out = defaults(schema) if base is None else copy.deepcopy(base)
    for g in schema:
        if g.group in locked or f"{g.group}.{g.name}" in locked:
            if base is not None and g.name in base.get(g.group, {}):
                continue
        rng = Rng(derive_seed(seed, g.group, g.name))
        out.setdefault(g.group, {})[g.name] = g.roll(rng)
    return out


def mutate(schema: Schema, genes: dict, seed: int, strength: float,
           locked: set[str] | frozenset = frozenset()) -> dict:
    out = copy.deepcopy(genes)
    for g in schema:
        if g.group in locked or f"{g.group}.{g.name}" in locked:
            continue
        rng = Rng(derive_seed(seed, "mutate", g.group, g.name))
        cur = out.get(g.group, {}).get(g.name, g.default)
        out.setdefault(g.group, {})[g.name] = g.mutate(cur, rng, strength)
    return out


def sanitize(schema: Schema, genes: Any) -> tuple[dict, list[str]]:
    """Clamp/repair gene values; unknown genes are dropped with a warning,
    missing ones take their default."""
    warnings: list[str] = []
    out = defaults(schema)
    known = {(g.group, g.name): g for g in schema}
    if not isinstance(genes, dict):
        return out, ["genes missing, using defaults"]
    for group, vals in genes.items():
        if not isinstance(vals, dict):
            warnings.append(f"gene group {group!r} is not an object")
            continue
        for name, v in vals.items():
            g = known.get((group, name))
            if g is None:
                warnings.append(f"unknown gene {group}.{name} ignored")
                continue
            try:
                nv = g.clamp(v)
            except (TypeError, ValueError):
                warnings.append(f"bad value for {group}.{name}: {v!r}")
                continue
            if nv != v and not (g.kind == "float" and isinstance(v, (int, float))
                                and abs(float(v) - nv) < 1e-9):
                warnings.append(f"{group}.{name} clamped to {nv!r}")
            out[group][name] = nv
    return out, warnings


# ---- (de)serialisation with migration ----------------------------------------
# version -> function upgrading a dict from that version to version+1
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def from_dict(d: Any, schemas: dict[str, Schema]) -> tuple[Genome, list[str]]:
    """Validate and migrate a genome dict. Raises GenomeError when unusable."""
    if not isinstance(d, dict):
        raise GenomeError("not a creature genome (expected a JSON object)")
    if d.get("format") != FORMAT:
        raise GenomeError(f"not a PISI creature file (format={d.get('format')!r})")
    try:
        ver = int(d.get("version", 0))
    except (TypeError, ValueError):
        raise GenomeError("genome version is not a number") from None
    if ver > VERSION:
        raise GenomeError(
            f"this pet was made by a newer PISI (genome v{ver}, this app "
            f"reads up to v{VERSION}). Update PISI to use it")
    if ver < 1:
        raise GenomeError(f"unsupported genome version {ver}")
    d = copy.deepcopy(d)
    while ver < VERSION:
        d = MIGRATIONS[ver](d)
        ver += 1
        d["version"] = ver
    fam = d.get("family")
    if fam not in schemas:
        raise GenomeError(f"unknown pet family {fam!r}")
    try:
        seed = int(d.get("seed", 0)) & MAX_SEED
    except (TypeError, ValueError):
        raise GenomeError("seed is not a number") from None
    gen = d.get("generator", GENERATOR)
    warnings: list[str] = []
    try:
        gen = int(gen)
    except (TypeError, ValueError):
        gen = GENERATOR
        warnings.append("bad generator version, using current")
    if gen > GENERATOR:
        warnings.append(f"made with a newer generator (v{gen}); drawn with v{GENERATOR}")
        gen = GENERATOR
    genes, w2 = sanitize(schemas[fam], d.get("genes"))
    warnings += w2
    name = d.get("name", "")
    if not isinstance(name, str):
        name = ""
    return Genome(fam, seed, genes, name[:40], gen, VERSION), warnings


def from_json(text: str, schemas: dict[str, Schema]) -> tuple[Genome, list[str]]:
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise GenomeError(f"not valid JSON: {e}") from None
    return from_dict(d, schemas)


@dataclass
class History:
    """Bounded undo/redo of gene states (used by the editor)."""
    limit: int = 100
    _undo: list = field(default_factory=list)
    _redo: list = field(default_factory=list)

    def push(self, state) -> None:
        self._undo.append(copy.deepcopy(state))
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self, current):
        if not self._undo:
            return None
        self._redo.append(copy.deepcopy(current))
        return self._undo.pop()

    def redo(self, current):
        if not self._redo:
            return None
        self._undo.append(copy.deepcopy(current))
        return self._redo.pop()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)
