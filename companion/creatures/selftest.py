"""Deterministic self-test for the procedural pet framework.

    python3 -m companion --self-test [--json]

Runs without Qt or pytest (so it also works inside a built app): checks
pixel determinism against golden hashes, separate random streams, a seed
sweep per family for valid frames, genome validation and migration errors,
and records timings. Prints a structured report; exit code 1 on failure.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time

from . import api
from .genome import GenomeError
from .render import FX_WHITE, colorize

# sha256 of (state, frame, facing) RGBA for the canonical cat and a few
# seeds. Regenerate deliberately with scripts/pet_golden.py (and bump
# genome.GENERATOR) when the look is meant to change.
GOLDEN: dict[str, str] = {
    "canon|sit|0|1": "686171b293ba073d103082f758b1a0f31766a43acd1fb36ada5ef777de40fbf4",
    "canon|sleep|2|1": "93189eb17b2759d8836b64739e3b24325d6d4aa615b43542eebf5f18b0ec0c80",
    "canon|turn|1|-1": "bebac4da8dc4b1654d3a09889d54ef3ca2f9ea94cd8ee91ed82346804f1e86ae",
    "canon|walk|3|-1": "96ba470a8c5d3a5018b534960b92d8d803dbb8d01069addfe066a05a709febc3",
    "canon|walk|3|1": "56503ab9defa9024294f715c7560b55ab7f6a99c44e2a19404080cd99012caf7",
    "seed:1234|run|2|-1": "7c9a811c538ac2e28c308839296708b9dfbb7ff09c5ed68cec60cbec16579eb1",
    "seed:7|idle|5|1": "242601dc619b1aaf07d36aa2f824607b2b454427c5c4130ea66166b617dbc0f2",
    "seed:99|sit|4|-1": "340258b5b7b5e6dfcfb79e225bf91471018ed349d640e6d55ee7f096d8ab9c27"
}

GOLDEN_CASES = [("canon", "sit", 0, 1), ("canon", "walk", 3, 1),
                ("canon", "walk", 3, -1), ("canon", "sleep", 2, 1),
                ("canon", "turn", 1, -1), ("seed:7", "idle", 5, 1),
                ("seed:1234", "run", 2, -1), ("seed:99", "sit", 4, -1)]


def _genome(tag: str):
    if tag == "canon":
        return api.canon_genome("feline")
    return api.new_genome("feline", int(tag.split(":")[1]))


def golden_now() -> dict[str, str]:
    out = {}
    for tag, st, i, fc in GOLDEN_CASES:
        pet = api.Creature(_genome(tag))
        out[f"{tag}|{st}|{i}|{fc}"] = hashlib.sha256(pet.frame(st, i, fc)).hexdigest()
    return out


def check_frame(pet, state: str, i: int, facing: int = 1) -> list[str]:
    """Structural checks on one rendered frame."""
    errs = []
    fr, _flash = pet.frame_grid(state, i, facing)
    w, h = fr.w, fr.h
    if fr.clipped:
        errs.append("touches/clips the frame edge")
    opaque = [k for k, r in enumerate(fr.role) if r]
    if len(opaque) < 120:
        errs.append(f"almost empty ({len(opaque)} px)")
    # distinct (role, material) pairs == distinct visible colours
    # count real rendered colours (eyes share a colour unless odd, lids are
    # drawn in the outline colour, …)
    data = colorize(fr, pet._pal["L"])
    colors = {data[k * 4:k * 4 + 4] for k in opaque if fr.role[k] != FX_WHITE}
    if len(colors) > 16:
        errs.append(f"{len(colors)} colours (max 16)")
    role = fr.role
    for k in opaque:
        if role[k] == FX_WHITE:
            continue
        x, y = k % w, k // w
        if not any(0 <= x + dx < w and 0 <= y + dy < h and role[(y + dy) * w + x + dx]
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            errs.append(f"orphan pixel at {x},{y}")
            break
    return errs


def check_pose_finite(pet, state: str, i: int) -> list[str]:
    nums = getattr(pet.fam, "numbers", None)
    if nums is None:
        return []
    if not all(math.isfinite(v) for v in nums(pet.built, state, i)):
        return ["non-finite pose value"]
    return []


def sweep(fam: str, seeds, states=None, facings=(1, -1)) -> dict[str, list[str]]:
    bad: dict[str, list[str]] = {}
    for s in seeds:
        g = api.new_genome(fam, s)
        pet = api.Creature(g)
        names = states or list(pet.states())
        for st in names:
            n = pet.states()[st].frames
            for i in range(n):
                for fc in facings:
                    errs = check_frame(pet, st, i, fc) + check_pose_finite(pet, st, i)
                    if errs:
                        bad.setdefault(f"{fam}:{s}", []).append(f"{st}[{i}]{fc:+d}: {errs[0]}")
    return bad


def run(quick: bool = False) -> dict:
    report: dict = {"ok": True, "checks": [], "timings_ms": {}}

    def check(name, ok, detail=""):
        report["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            report["ok"] = False

    # 1. determinism: same genome twice -> same bytes; golden hashes
    t = time.perf_counter()
    g = api.canon_genome()
    a = api.Creature(g).frame("walk", 2)
    b = api.Creature(api.genome_from_json(g.to_json())[0]).frame("walk", 2)
    check("same genome renders identically (incl. JSON round trip)", a == b)
    now = golden_now()
    if GOLDEN:
        diff = [k for k in GOLDEN if GOLDEN.get(k) != now.get(k)]
        check("golden pixel hashes match", not diff, ", ".join(diff[:4]))
    else:
        check("golden pixel hashes match", True, "no golden set recorded")
    report["timings_ms"]["determinism"] = round((time.perf_counter() - t) * 1e3, 1)

    # 2. separate streams: coat changes never move a pixel of the silhouette
    g2 = g.copy()
    g2.genes["coat"]["color"] = "ginger"
    g2.genes["coat"]["pattern"] = "tabby"
    m1 = bytes(1 if x else 0 for x in api.Creature(g).frame_grid("walk", 1)[0].role)
    m2 = bytes(1 if x else 0 for x in api.Creature(g2).frame_grid("walk", 1)[0].role)
    check("coat change keeps the silhouette", m1 == m2)
    r1 = api.new_genome("feline", 5)
    r2 = api.new_genome("feline", 6, base=r1, locked={"body", "head", "ears", "tail"})
    check("locked anatomy survives a re-roll",
          all(r1.genes[k] == r2.genes[k] for k in ("body", "head", "ears", "tail")))

    # 3. genome validation
    for label, text, want in (
            ("garbage JSON", "{nope", "not valid JSON"),
            ("future version", json.dumps({"format": "pisi-creature", "version": 99,
                                           "family": "feline"}), "newer PISI"),
            ("unknown family", json.dumps({"format": "pisi-creature", "version": 1,
                                           "family": "griffin"}), "unknown pet family")):
        try:
            api.genome_from_json(text)
            check(f"rejects {label}", False, "accepted")
        except GenomeError as e:
            check(f"rejects {label}", want in str(e), str(e))
    gg, warns = api.genome_from_dict({"format": "pisi-creature", "version": 1,
                                      "family": "feline", "seed": 3,
                                      "genes": {"body": {"legs": 999, "bogus": 1}}})
    check("clamps out-of-range genes with warnings",
          gg.genes["body"]["legs"] <= 10 and len(warns) >= 2, "; ".join(warns))

    # 4. seed sweep per family
    t = time.perf_counter()
    n = 12 if quick else 100
    key_states = ["sit", "idle", "walk", "run", "sleep", "turn", "dangle", "stretch"]
    for fam in api.families():
        bad = sweep(fam, range(n), key_states, facings=(1,))
        check(f"{fam}: {n} seeds render valid frames", not bad,
              "; ".join(f"{k}: {v[0]}" for k, v in list(bad.items())[:3]))
    report["timings_ms"]["seed_sweep"] = round((time.perf_counter() - t) * 1e3, 1)

    # 5. bake timing (cold), for the record
    t = time.perf_counter()
    baked = api.Creature(g).bake()
    report["timings_ms"]["bake_all_states_both_facings"] = round((time.perf_counter() - t) * 1e3, 1)
    report["frames_baked"] = sum(len(v) for d in baked.frames.values() for v in d.values())
    report["bytes_baked"] = baked.nbytes()
    return report


def main(as_json: bool = False, quick: bool = False) -> int:
    rep = run(quick=quick)
    if as_json:
        print(json.dumps(rep, indent=2))
    else:
        for c in rep["checks"]:
            mark = "PASS" if c["ok"] else "FAIL"
            extra = f"  ({c['detail']})" if c["detail"] and not c["ok"] else ""
            print(f"[{mark}] {c['name']}{extra}")
        for k, v in rep["timings_ms"].items():
            print(f"  {k}: {v} ms")
        print("OK" if rep["ok"] else "SELF-TEST FAILED")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main("--json" in sys.argv, "--quick" in sys.argv))
