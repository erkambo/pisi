"""Deterministic randomness for the creature generator.

Python's ``random`` module, ``hash()`` (salted per process) and float libm
calls are not guaranteed to agree across processes or operating systems, so
the generator uses its own tiny PRNG: SplitMix64, seeded through a stable
FNV-1a hash of a stream name. Every consumer asks for a *named stream*
(``"anatomy"``, ``"coat"``, ``"motion"``, …) so re-rolling one aspect of a pet
never disturbs another.
"""
from __future__ import annotations

MASK64 = (1 << 64) - 1


def fnv1a64(text: str) -> int:
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) & MASK64
    return h


def splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & MASK64
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return z ^ (z >> 31)


class Rng:
    """A SplitMix64 stream. ``Rng(seed, "coat")`` always yields the same
    sequence on every platform."""

    __slots__ = ("_state",)

    def __init__(self, seed: int, stream: str = "") -> None:
        self._state = splitmix64((int(seed) & MASK64) ^ fnv1a64(stream))

    def next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def random(self) -> float:
        """Uniform float in [0, 1) built from 53 random bits (exact)."""
        return (self.next_u64() >> 11) * (1.0 / 9007199254740992.0)

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self.random()

    def randint(self, a: int, b: int) -> int:
        """Inclusive integer range."""
        return a + self.next_u64() % (b - a + 1)

    def chance(self, p: float) -> bool:
        return self.random() < p

    def choice(self, seq):
        return seq[self.next_u64() % len(seq)]

    def weighted(self, items: list[tuple[object, float]]):
        total = sum(w for _, w in items)
        r = self.random() * total
        for item, w in items:
            r -= w
            if r < 0:
                return item
        return items[-1][0]

    def centered(self, spread: float = 1.0) -> float:
        """Bell-ish value in [-spread, spread] (mean of three uniforms) —
        favours typical anatomy over extremes."""
        return spread * ((self.random() + self.random() + self.random()) / 1.5 - 1.0)


def derive_seed(seed: int, *labels: object) -> int:
    """Stable child seed, e.g. per trait or per child in a mutation."""
    x = int(seed) & MASK64
    for lab in labels:
        x = splitmix64(x ^ fnv1a64(str(lab)))
    return x
