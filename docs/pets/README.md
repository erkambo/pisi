# Procedural pets (`companion/creatures/`)

PISI draws its cat itself. A pet is a
small versioned **genome** (JSON); the generator turns it into every
animation the desktop pet uses, in PISI's own pixel style.
PISI is a cat (the `feline` family), with 6 saved samples in
`companion/creatures/samples/`.

```
seed + genes + generator version → anatomy → pose (per state, per frame) → 48×48 pixel grid → RGBA
```

## Run it

| What | Command |
|---|---|
| PISI (uses your pet if you made one) | `./run.sh` or `python3 -m companion` |
| Pet Studio (standalone) | `python3 -m companion --pet-studio [file.pisipet.json]` |
| Pet Studio (in the app) | right-click the pet → More → 🐾 Pet Studio…, or Settings → Your pet |
| Framework self-test | `python3 -m companion --self-test [--json]` (exit 1 on failure) |
| Tests | `python3 -m pytest tests/test_creatures.py` |
| Visual sheets + GIFs | `python3 scripts/pet_sheets.py all` (dev only, needs Pillow) |
| Runtime benchmark | `QT_QPA_PLATFORM=offscreen python3 scripts/pet_bench.py 15` |
| Outline busyness report | `python3 scripts/pet_busy.py [seed …]` |
| Re-record golden hashes | `python3 scripts/pet_golden.py` (only when the look is *meant* to change) |

### Pet Studio controls
- **Preview:** state picker (every state, including transitions), Facing →/←,
  ◀ / Play-Pause / ▶ frame step (also ←, Space, →), speed 1×/½×/¼×,
  background (checker, light, dark, desktop + taskbar where gaits travel),
  zoom 2–8×, **Show rig** (spine, IK legs, tail chain, ground contacts —
  green paw = planted, red = lifted).
- **Pet:** name, animal, seed, 🎲 New pet (keeps 🔒 locked groups), Quick
  coats (the old Settings → Coat skins plus tuxedo/calico/siamese), every
  gene grouped as Body / Head / Ears / Tail / Coat / Eyes & nose / Movement.
- **Undo / Redo** (Ctrl+Z / Ctrl+Shift+Z; a slider drag is one step),
  **Reset to saved**, **Save to file… / Open file…** (`*.pisipet.json`).
- **Use as my pet**: bakes in the background (already done if you paused
  for half a second) and swaps the desktop pet live.

## Architecture

| Module | Role |
|---|---|
| `rng.py` | SplitMix64 + FNV-1a stream derivation; no `random`, no `hash()` |
| `dmath.py` | libm-free sin/cos so pixels match on Linux/Windows/macOS |
| `genome.py` | `Gene` schema, roll / mutate / sanitize, JSON (de)serialisation, migrations, `History` |
| `raster.py` | pixel-centre polygon/capsule/ellipse/thin-line rasterisers, 4-neighbour ring |
| `render.py` | family-agnostic compositor: groups, outline ring, partial seams, corner rule, material cleanup, palette → RGBA |
| `shapes.py`, `heads.py` | shared parametric modules: IK, chains, torso, span-built ¾ and front heads, ears |
| `quadruped.py` | the four-legged body plan: anatomy + pose → layers |
| `quadmotion.py` | every state as pose functions of (anatomy, motion genes, frame) |
| `coat.py` | colour ramps and body-anchored patterns |
| `families/` | registry + `base.QuadFamily` (build, fit-to-frame, render); `feline.py`, the cat, on the quadruped plan |
| `samples/` | 6 saved `.pisipet.json` cats (`scripts/pet_samples.py`) |
| `creature.py`, `api.py` | public, Qt-free API: `Creature.frame()`, `bake()` |
| `qt.py` | the only Qt module: Sheet conversion, bounded PNG disk cache, latest-wins cancellable `Baker` |
| `selftest.py` | `--self-test` |

The desktop pet (`sprite.py`), the studio preview, the cache and the tests
all call the same `Creature.frame()`, so a fix lands everywhere.

**Integration with PISI.** `pixelsheet.load()` returns a procedural Sheet
when `config.pet_look == "procedural"` (genome in `config.pet_genome`); with
no art at all it falls back to the procedural default cat. Procedural sheets
add `anims_left` (frames drawn for the other flank — never mirrored),
`speed` (gait px/frame: the sprite plays walk/run exactly as fast as the
window moves, so paws don't slide at any speed setting) and `transitions`
(sit down, stand up, lie down, get up, turn around).

## Genome format (v1)

```json
{
  "format": "pisi-creature", "version": 1, "generator": 1,
  "family": "feline", "seed": 1234, "name": "Mochi",
  "genes": {"body": {...}, "head": {...}, "ears": {...}, "tail": {...},
            "coat": {...}, "eyes": {...}, "motion": {...}}
}
```

- Rendering depends only on `genes` + `generator`; `seed` is provenance for
  re-rolling. Each gene rolls from its own stream `(seed, group, name)`.
- Unknown genes are dropped with a warning, out-of-range values clamped,
  missing ones defaulted. A newer `version` is refused with "update PISI";
  an unknown family is refused. PISI never crashes on a bad saved pet — it
  logs and shows the default cat.
- **Migration path:** bump `genome.VERSION` and register
  `MIGRATIONS[old] = fn(dict) -> dict`; `from_dict` applies them in order.
  Bump `GENERATOR` whenever the same genes would render differently (this
  also invalidates the bake cache and requires `scripts/pet_golden.py`).

## Determinism
Same genes + generator → identical RGBA on every OS: integer-snapped body
joints, quantised raster coordinates, no libm trig, no salted hashes, no
iteration-order dependence. `test_golden_hashes` pins 8 frames and runs on
the Linux/Windows/macOS CI matrix.

See also: [QUALITY.md](QUALITY.md).
