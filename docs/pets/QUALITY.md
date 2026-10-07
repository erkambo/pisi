# Quality report

## Things: animations for PISI's home (generator 6)

New states the cat uses with toys, a bed and a scratching post. Every one is
placed from the cat's own anatomy, and the thing it uses is placed from the
cat's **anchors** (`Creature.anchors()`: mouth, head top, paws, floor row per
frame), so they work for any procedural cat, not just the default.

Checked on the **review panel** (`creatures/panel.py`, 58 cats: canon, an
owner's real cat, 18 gene extremes, the samples, 32 unedited seeds):

* automatically (`tests/test_pet_anchors.py`): every frame inside the
  48 px frame on both flanks; anchors on the cat; a carried toy's mouth
  point never jumps more than 1 px between frames; the mouth reaches the toy
  spot when picking up and putting down; the swipe's paw touches the toy;
  scratching paws stay on the post with the hind paws planted and a stroke
  of at least 4 px;
* by eye with `scripts/pet_review.py` (sheets, grids, boards, GIFs; stand-in
  post and toy drawn where the pose expects them). GIFs: `img/things/`.

| State | Rating | Notes |
|---|---|---|
| `curl` (+ `curldown`, `curlup`) | ✅ | A dome sized from body length and depth (kept between 1.15 and 1.4 times as tall as it is half-wide, so a long cat is an oval, not a slug), the folded thigh as a low curve, head on the front with the chin down, tail wrapped along the floor with the tip under the nose; breathing, tail-tip twitch, z's. `curl_geometry()` gives a bed its size. The tail tucks in over one frame when curling up. |
| `pickup`, `drop` | ✅ | Front end lowered, the mouth put on `toy_spot()` exactly; mouth opens to grab and to let go. |
| `carrywalk`, `carrytrot`, `carrysit` | ✅ | Head held 1 px higher; the mouth anchor moves at most 1 px per frame, so a held toy doesn't jitter. |
| `bat` | ✅ | Crouched, a swipe that reaches as far as that cat's leg really reaches from the crouch (`bat_reach()`, from the leg's root height and length), so every cat touches a toy at `bat_target()`. |
| `scratch` | ✅ | Stretched up tall on the hind legs (62°), head up at full height, forelegs reaching up the post in front of the face. The forelegs are shorter than the neck at this size, so the shoulder blade slides up 4 px as a real cat's does; the post's distance and the stroke band (≥ 4 px) come from where that raised leg starts and how far it reaches. First version (head tucked under the arms) read as hunched and was redone after review. |
| `knead` | 🟡 | Half-sitting, front paws pressing in turn (3 px), happy squint, tail up. Readable as kneading at 6 fps; at 1x it can pass for shifting weight. |


# Cats

## Outline busyness
Measured with `python3 scripts/pet_busy.py` (interior contour pixels /
free-floating 1–2 px contour fragments / doubled outlines, per frame).

| | fragments/frame | doubled/frame |
|---|---|---|
| idle / run / sit (v1) | 2.4 / 1.8 / 2.1 | 1.0 / 1.7 / 1.0 |
| idle / run / sit (v2) | **0.3 / 0.7 / 1.9** | 1.0 / 1.7 / 1.0 |

v2 adds a contour-calming pass (stray interior fragments become fill again;
the face is protected), a D-shaped sitting haunch, plain far legs on tabbies,
and a drooping-tail half-sit key. Remaining fragments in sleep/eat/yawn/hurt
are closed-eye and squint lines, which belong there.

Judged on the real pipeline output in `docs/pets/img/` (regenerate with
`python3 scripts/pet_sheets.py all`). Curated: `curated_*.png`; **unedited
fixed random sample (seeds 1000–1031)**: `random_*.png`; every state of the
default cat: `all_states.png`; motion: `*.gif`.

Scale: ✅ ships, 🟡 acceptable with a known weakness, ❌ not acceptable.

| Aspect | Rating | Notes |
|---|---|---|
| Silhouette | ✅ | Reads as a cat at 1× in every state. Builds vary visibly (long/short body, leg length, haunch, big ears, fluffy tail). |
| Anatomical plausibility | ✅ | IK legs with stance/swing; near/far leg depth order; haunch in sit; legs fold in loaf. Repairs keep legs long enough to carry deep bodies. |
| Pixel execution | ✅ | 1px rings, no orphan pixels (checked on 100 seeds × 8 states), ≤16 colours per frame, discrete paw shapes instead of rotated polygons, material cleanup removes stray pattern pixels. |
| Coat patterns | 🟡 | Solid, tuxedo, bicolor, van, point, calico, tortie read well. Tabby leg bands can look busy on long-legged cats; spotted is subtle. |
| Expression | ✅ | Blink, half-lid, closed, happy squint; open/wide mouth with tongue and teeth; ears up/back/flat/flick; look left/right; front-view face. |
| Animation | 🟡 | Run, pounce, jump, attack, stretch, eat, sleep breathing, tail follow-through are good. Walk reads well; the hind thigh still bulges past the rump for 2 of 8 frames when the leg swings back. |
| Transitions | ✅ | Sit down via "hindquarters first" (4 f), stand up (4 f), lie down (5 f), get up (4 f), a full 8-frame turn-around (old side → front view → new side, stepping paws); the tail switches anchor instead of sweeping through the body. One-shots all settle back to sit. |
| Directions | ✅ | Left/right are separate renders of opposite flanks (odd eyes and calico patches land on the correct side); turn-around plays on every direction change. |

## Known weaknesses (honest list)
- **Black cat on very dark wallpapers:** the outline `#131313` is barely
  darker than a dark taskbar; there's no halo, to keep the outline crisp.
- **Walk frames 6–7:** hind thigh bulges past the rump while swinging back.
- **Dangle:** reads as "held by the scruff" but the body is a rather
  straight column.
- **Light coats:** the shade step on white/cream is subtle, so far legs read
  a little flat on white cats.
- **Extremes:** at maximum body+tail length the fit step shortens the tail
  (logged as a note) so every pose stays in the 48 px frame.
