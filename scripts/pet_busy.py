"""Outline busyness per state (dev tool): interior contour pixels, tiny
interior contour fragments and doubled outlines — lower is calmer.

    python3 scripts/pet_busy.py [seed ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from companion.creatures import api  # noqa: E402
from companion.creatures.render import OUTLINE  # noqa: E402


def busy(fr):
    w, h, role = fr.w, fr.h, fr.role
    interior = set()
    for k, r in enumerate(role):
        if r != OUTLINE:
            continue
        x, y = k % w, k // w
        if all(0 <= x + dx < w and 0 <= y + dy < h and role[(y + dy) * w + x + dx]
               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            interior.add((x, y))
    seen, tiny = set(), 0
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
        if len(comp) <= 2:
            tiny += 1
    double = sum(1 for (x, y) in interior if (x + 1, y) in interior and (x, y + 1) in interior)
    return len(interior), tiny, double


def report(g, label):
    pet = api.Creature(g)
    tot = [0, 0, 0]
    rows = []
    for st, spec in pet.states().items():
        s = [0, 0, 0]
        for i in range(spec.frames):
            b = busy(pet.frame_grid(st, i)[0])
            s = [a + c for a, c in zip(s, b)]
        rows.append((st, spec.frames, [round(v / spec.frames, 1) for v in s]))
        tot = [a + c for a, c in zip(tot, s)]
    print(f"== {label}: interior/tiny/double per frame")
    for st, n, s in sorted(rows, key=lambda r: -r[2][1] - r[2][2]):
        print(f"  {st:11s} {n:3d}f  {s}")
    print("  TOTAL", tot)
    return tot


if __name__ == "__main__":
    report(api.canon_genome(), "canon")
    for s in sys.argv[1:]:
        report(api.new_genome("feline", int(s)), f"seed {s}")
