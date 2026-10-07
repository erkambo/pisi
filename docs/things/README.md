# Things (`companion/things/`)

Beds, bowls, scratching posts, toys and toy baskets for PISI's home, drawn
procedurally in the cat's own pixel style and **fitted to a specific cat**.

```
design (plain data) + CatFit (measured from the cat) -> Rendered (back + front images, where the cat goes)
```

| Module | Role |
|---|---|
| `fit.py` | `measure(creature)`: the curl's real footprint, the eating mouth, toy spot, swipe target, post geometry, main coat colour |
| `palette.py` | material ramps (fill, shade, outline: the cat's house style), WCAG contrast, CIE ΔE |
| `draw.py` | shape helpers, `paint()` with the cat's renderer, `Rendered` (mirrored for a cat facing left) |
| `kinds/` | `bed` (donut, cup, pillow, box, basket, cave, sofa, teacup), `bowl` (ceramic, steel, fish, speckled, stand, fountain), `post` (sisal, log, tower, cactus, cardboard, deluxe), `toy` (mouse, yarn, ball, crinkle, fish, bee, spring), `basket` (wicker, crate, felt, box, rope, chest) — each with `render()` and an in-use `check()` |
| `scene.py` | back + cat + front composites, a toy held in the mouth (Qt-free) |
| `judge.py` | the gates: pixels, wallpapers, in use on every panel cat, variety |
| `catalog.py` | the curated, named, priced items that ship |

Contracts with the cat's rig (`creatures/quadmotion.py`): a rimmed bed's
front rim is `RIM` px high and the cat lies in `curlrim` with its chin on
it; toys keep their grip `TOY_GRIP` rows above the floor, where every cat's
pick-up pose reaches; a post's near face is where `scratch_geometry()` puts
the paws.

| Do | Command |
|---|---|
| Judge the whole catalog, write QUALITY.md + sheet | `python3 scripts/thing_judge.py` |
| One design on the panel | `python3 scripts/thing_review.py inuse bed --design '{"style": "box"}'` |
| Many designs on one cat | `python3 scripts/thing_review.py designs post` |
| Tests | `python3 -m pytest tests/test_things.py` |

A toy style also needs its feel in `playground.py`: `FRICTION` (how far it
slides or rolls), and optionally `BOUNCES` and `ROLLS`.

Adding a thing: a design in `catalog.py` (or a new kind in `kinds/` with
`render` + `check`), run `thing_judge.py`, look at the sheet, and only ship
what passes and looks right.
