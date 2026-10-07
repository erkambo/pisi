"""The review panel: a fixed set of cats every new animation, anchor and item
must work for.

A feature that looks right on the default cat can still break on a long cat,
a stubby one or a tiny head. The panel covers the gene space deliberately:

* ``random``   — 32 unedited seeds (1000–1031), the same ones the quality
  sheets use, so nothing is cherry-picked;
* ``extremes`` — the canonical cat with one or two genes pushed to the ends
  of their ranges (the shapes most likely to break a pose);
* ``samples``  — the saved sample cats;
* ``owners``   — real cats people use (``samples/panel/``).

Everything is deterministic: the same panel on every machine.
"""
from __future__ import annotations

from pathlib import Path

from . import api
from .genome import Genome

RANDOM_SEEDS = tuple(range(1000, 1032))

# label -> {group: {gene: value}} applied on top of the canonical cat
EXTREMES: dict[str, dict] = {
    "long+tall": {"body": {"length": 13.0, "legs": 10.0}},
    "long+short-legs": {"body": {"length": 13.0, "legs": 6.0, "depth": 7.0}},
    "short+stubby": {"body": {"length": 8.0, "legs": 6.0, "depth": 7.0}},
    "short+tall": {"body": {"length": 8.0, "legs": 10.0}},
    "deep": {"body": {"depth": 11.0, "legs": 8.0, "thigh": 3.6, "belly": 1.5}},
    "slim": {"body": {"depth": 7.0, "thigh": 2.4, "chest": 1.5}},
    "big-head": {"head": {"width": 12, "face": 6, "neck": 10, "cheeks": True}},
    "small-head": {"head": {"width": 8, "face": 4, "neck": 8, "jaw": 1}},
    "big-ears": {"ears": {"height": 6, "width": 5}},
    "folded-ears": {"ears": {"fold": True}},
    "long-fluffy-tail": {"tail": {"length": 1.3, "fluff": 1.6, "hook": 1.6}},
    "stub-tail": {"tail": {"length": 0.45, "fluff": 0.8, "hook": 0.0}},
    "tail-high": {"tail": {"carry": 1.0}},
    "tail-low": {"tail": {"carry": -1.0}},
    "big-paws": {"body": {"paw": 4}},
    "small-paws": {"body": {"paw": 2}},
    "white": {"coat": {"color": "white", "pattern": "solid"},
              "eyes": {"left": "blue", "nose": "pink"}},
    "cream-van": {"coat": {"color": "cream", "pattern": "van", "white": 0.9}},
}

OWNERS_DIR = Path(__file__).resolve().parent / "samples" / "panel"


def _extreme(label: str, change: dict) -> Genome:
    g = api.canon_genome("feline")
    d = g.to_dict()
    for group, vals in change.items():
        d["genes"].setdefault(group, {}).update(vals)
    d["name"] = label
    out, _warn = api.genome_from_dict(d)
    return out


def random_cats() -> list[tuple[str, Genome]]:
    return [(f"seed {s}", api.new_genome("feline", s)) for s in RANDOM_SEEDS]


def extremes() -> list[tuple[str, Genome]]:
    return [(k, _extreme(k, v)) for k, v in EXTREMES.items()]


def samples() -> list[tuple[str, Genome]]:
    return [(g.name or f"sample {i}", g) for i, g in enumerate(api.samples("feline"))]


def owners() -> list[tuple[str, Genome]]:
    out = []
    for f in sorted(OWNERS_DIR.glob("*.pisipet.json")):
        g, _ = api.genome_from_json(f.read_text("utf-8"))
        out.append((g.name or f.stem, g))
    return out


GROUPS = {"owners": owners, "extremes": extremes, "samples": samples, "random": random_cats}


def panel(groups: tuple[str, ...] = ("owners", "extremes", "samples", "random")
          ) -> list[tuple[str, Genome]]:
    """(label, genome) for the chosen groups, in a fixed order."""
    out: list[tuple[str, Genome]] = [("canon", api.canon_genome("feline"))]
    for name in groups:
        out += GROUPS[name]()
    return out
