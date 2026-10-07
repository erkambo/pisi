"""Stable public surface of the procedural pet framework.

Everything a host app (PISI or another program) needs, without Qt:

    from companion.creatures import api
    g = api.new_genome("feline", seed=7)
    pet = api.Creature(g)
    rgba = pet.frame("walk", 0)              # 48x48 RGBA bytes
    baked = pet.bake()                       # all states, both facings
    text = g.to_json(); g2, warnings = api.genome_from_json(text)

Qt users add ``companion.creatures.qt`` (Sheet conversion, cache, async).
"""
from __future__ import annotations

from . import families as _families  # noqa: F401  (registers built-ins)
from .creature import (Baked, BakeCancelled, Creature, canon_genome, classic_genome, family,
                       new_genome, schemas)
from .families.base import REGISTRY, register
from .genome import (FORMAT, GENERATOR, VERSION, Gene, Genome, GenomeError,
                     History, mutate, sanitize)
from .genome import from_dict as _from_dict
from .genome import from_json as _from_json

__all__ = ["Baked", "BakeCancelled", "Creature", "FORMAT", "GENERATOR", "Gene",
           "Genome", "GenomeError", "History", "REGISTRY", "VERSION",
           "canon_genome", "classic_genome", "family", "families", "genome_from_dict",
           "genome_from_json", "mutate_genome", "new_genome", "register", "samples",
           "sanitize", "schemas"]


def families() -> list[str]:
    return list(REGISTRY)


def samples(fam: str) -> list[Genome]:
    """The saved sample genomes shipped for a family (sorted by file name).
    Broken files are skipped, never fatal."""
    from pathlib import Path
    d = Path(__file__).resolve().parent / "samples" / fam
    out = []
    for f in sorted(d.glob("*.pisipet.json")):
        try:
            g, _ = genome_from_json(f.read_text("utf-8"))
            out.append(g)
        except (OSError, GenomeError):
            continue
    return out


def genome_from_dict(d) -> tuple[Genome, list[str]]:
    return _from_dict(d, schemas())


def genome_from_json(text: str) -> tuple[Genome, list[str]]:
    return _from_json(text, schemas())


def mutate_genome(g: Genome, seed: int, strength: float,
                  locked: frozenset[str] | set[str] = frozenset()) -> Genome:
    fam = family(g.family)
    genes = mutate(fam.schema, g.genes, seed, strength, locked)
    out = Genome(g.family, seed, genes, g.name, g.generator)
    out.notes = fam.repair(genes)
    return out
