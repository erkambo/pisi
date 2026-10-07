"""Small toys: a felt mouse, a yarn ball, a jingle ball, a crinkle ball, a
catnip fish, a bumble bee and a rainbow spring.

A toy is one small image with a **grip**: the pixel that goes in the cat's
mouth when it's carried (the rig's mouth anchor) and that the cat reaches
for when it picks the toy up off the floor. Every toy keeps its grip
``TOY_GRIP`` rows above the floor row, the height every cat's pick-up pose
reaches down to, so any toy works with any cat.
"""
from __future__ import annotations

from ...creatures import quadmotion as QM
from ..draw import SHADE, Layer, Mats, Rendered, paint, rect, rounded
from ..fit import CatFit

STYLES = ("mouse", "yarn", "ball", "crinkle", "fish", "bee", "spring")
DEFAULT = {"style": "mouse", "color": "felt_grey"}


def render(design: dict, fit: CatFit) -> Rendered:
    d = {**DEFAULT, **design}
    style = d["style"]
    mats = Mats()
    lay: list[Layer] = []
    G = QM.TOY_GRIP
    if style == "mouse":
        body_m = mats.id(d["color"] if d["color"].startswith("felt") else "felt_grey")
        pink = mats.id("felt_pink")
        W, H = 13, G + 3                       # the floor is the bottom outline row
        y_floor = H - 2
        body = rounded(4, y_floor - 2, 9, y_floor, 1.5) | {(9, y_floor - 1), (10, y_floor - 1),
                                                           (10, y_floor)}
        ov = {(x, y): SHADE for (x, y) in body if y == y_floor}
        ov[(9, y_floor - 2)] = SHADE
        lay.append(Layer("body", body, z=1, group=1, material=body_m, tone_overrides=ov))
        lay.append(Layer("ear", {(7, y_floor - 3), (8, y_floor - 3)}, z=2, group=1, material=pink))
        lay.append(Layer("eye", set(), z=3, group=1, overrides={(9, y_floor - 1): 3}))
        tail = {(3, y_floor), (2, y_floor), (1, y_floor - 1)}
        lay.append(Layer("tail", tail, z=0, group=0, material=pink, tone=SHADE))
        grip = (6, y_floor - 2 - 1 + 1)        # the top of its back
    elif style == "yarn":
        body_m = mats.id(d["color"] if d["color"].startswith("yarn") else "yarn_red")
        W, H = 10, G + 4
        y_floor = H - 2
        ball = rounded(2, y_floor - 4, 6, y_floor, 2.5)
        ov = {}
        for (x, y) in ball:
            if (x - y) % 3 == 0 or y == y_floor or x == 6:
                ov[(x, y)] = SHADE           # wraps, and the side away from the light
        lay.append(Layer("ball", ball, z=1, group=1, material=body_m, tone_overrides=ov))
        thread = {(7, y_floor), (8, y_floor)}
        lay.append(Layer("thread", thread, z=0, group=0, material=body_m, tone=SHADE))
        grip = (4, y_floor - 4)
    elif style == "crinkle":                    # a scrunched foil ball: facets catch the light
        body_m = mats.id("foil")
        W, H = 9, G + 4
        y_floor = H - 2
        ball = rounded(2, y_floor - 4, 6, y_floor, 2.5)
        ov = {(x, y): SHADE for (x, y) in ball
              if (x + 2 * y) % 4 == 0 or y == y_floor or x == 6}
        for p in ((3, y_floor - 3), (3, y_floor - 2), (4, y_floor - 3)):
            ov.pop(p, None)                     # the shine
        lay.append(Layer("ball", ball, z=1, group=1, material=body_m, tone_overrides=ov))
        grip = (4, y_floor - 4)
    elif style == "fish":                       # a felt fish stuffed with catnip
        body_m = mats.id(d["color"] if d["color"] in ("sky", "mustard", "terracotta", "mint")
                         else "sky")
        fin = mats.id(d.get("fin", "felt_pink"))
        W, H = 14, G + 3
        y_floor = H - 2
        body = rounded(5, y_floor - 2, 11, y_floor, 1.5) | {(12, y_floor - 1)}
        ov = {(x, y): SHADE for (x, y) in body if y == y_floor or x in (7, 9) and y > y_floor - 2}
        lay.append(Layer("body", body, z=1, group=1, material=body_m, tone_overrides=ov))
        lay.append(Layer("eye", set(), z=3, group=1, overrides={(10, y_floor - 1): 3}))
        m = y_floor - 1
        tail = {(4, m), (3, m - 1), (3, m), (3, m + 1), (2, m - 1), (2, m + 1)}   # forked
        lay.append(Layer("tail", tail, z=0, group=0, material=fin,
                         tone_overrides={(x, y): SHADE for (x, y) in tail if y == y_floor}))
        lay.append(Layer("fin", {(7, y_floor - 3), (8, y_floor - 3)}, z=2, group=1, material=fin))
        grip = (8, y_floor - 3)
    elif style == "bee":                        # a fuzzy bumble bee with felt wings
        body_m = mats.id("yarn_gold")
        stripe = mats.id("charcoal")
        wing = mats.id("porcelain")
        W, H = 13, G + 3
        y_floor = H - 2
        body = rounded(3, y_floor - 2, 9, y_floor, 1.5)
        ov = {(x, y): SHADE for (x, y) in body if y == y_floor}
        lay.append(Layer("body", body, z=1, group=1, material=body_m, tone_overrides=ov))
        lay.append(Layer("stripes", {(x, y) for (x, y) in body if x in (5, 7)}, z=2, group=1,
                         material=stripe))
        lay.append(Layer("sting", {(2, y_floor - 1)}, z=0, group=1, material=stripe))
        lay.append(Layer("eye", set(), z=3, group=1, overrides={(9, y_floor - 1): 3}))
        lay.append(Layer("wings", {(5, y_floor - 3), (6, y_floor - 3), (7, y_floor - 3)}, z=4,
                         group=2, material=wing, tone_overrides={(7, y_floor - 3): SHADE}))
        grip = (6, y_floor - 3)
    elif style == "spring":                     # a rainbow coil lying on its side
        W, H = 13, G + 3
        y_floor = H - 2
        colours = ("yarn_red", "yarn_gold", "yarn_green", "yarn_blue")
        for i in range(5):                      # one ring per column, the outline between
            m = mats.id(colours[i % len(colours)])
            x = 2 + 2 * i
            coil = {(x, y) for y in range(y_floor - 3, y_floor + 1)}
            lay.append(Layer(f"coil{i}", coil, z=i, group=i, material=m,
                             tone_overrides={(x, y_floor): SHADE, (x, y_floor - 1): SHADE}))
        grip = (6, y_floor - 3)
    else:                                       # a jingle ball with a band
        body_m = mats.id(d["color"] if d["color"] in ("yarn_blue", "yarn_gold", "yarn_green",
                                                      "yarn_red") else "yarn_blue")
        band = mats.id("porcelain")
        W, H = 8, G + 3
        y_floor = H - 2
        ball = rounded(2, y_floor - 3, 5, y_floor, 2.0)
        ov = {(x, y): SHADE for (x, y) in ball if y == y_floor or x == 5}
        lay.append(Layer("ball", ball, z=1, group=1, material=body_m, tone_overrides=ov))
        lay.append(Layer("band", {(x, y_floor - 2) for x in range(2, 6)} & ball, z=2, group=1,
                         material=band))
        grip = (3, y_floor - 3)
    # keep the grip exactly TOY_GRIP rows above the floor row
    floor_row = H - 1
    grip = (grip[0], floor_row - G)
    rgba, fr = paint(lay, W, H, mats)
    return Rendered(kind="toy", w=W, h=H, back=rgba, front=None, floor=floor_row,
                    back_frame=fr, cat_state="carrywalk", cat_at=None,
                    spots={"grip": grip}, design=d)


def held_at(r: Rendered, mouth: tuple[int, int], facing: int = 1) -> tuple[int, int]:
    """Top-left of the toy so its grip is at the cat's ``mouth`` (frame or
    screen pixels). A cat facing left carries the toy mirrored."""
    gx, gy = r.spots["grip"]
    if facing < 0:
        gx = r.w - 1 - gx
    return mouth[0] - gx, mouth[1] - gy


def check(r: Rendered, pet, fit: CatFit) -> list[tuple[str, str]]:
    """In use: carried, the toy never covers an eye and never dips through
    the floor; on the floor, its grip is where the cat's mouth reaches."""
    from ...creatures.render import EYE_FAR, EYE_NEAR, LID
    out: list[tuple[str, str]] = []
    w, h = pet.size
    for facing in (1, -1):
        img = r.image("back", facing)
        for st in ("carrywalk", "carrytrot", "carrysit", "pickup"):
            n = pet.states()[st].frames
            for i in range(n):
                if st == "pickup" and i < n - 2:
                    continue                  # held only once it's lifted
                an = pet.anchors(st, i, facing)
                tx, ty = held_at(r, an["mouth"], facing)
                if ty + r.h - 1 > fit.floor:
                    out.append(("fail", f"the toy dips through the floor ({st} {i})"))
                    return out
                fr, _ = pet.frame_grid(st, i, facing)
                for k, role in enumerate(fr.role):
                    if role in (EYE_FAR, EYE_NEAR, LID):
                        x, y = k % w, k // w
                        x = w - 1 - x if facing < 0 else x
                        u, v = x - tx, y - ty
                        if 0 <= u < r.w and 0 <= v < r.h and img[(v * r.w + u) * 4 + 3]:
                            out.append(("fail", f"the toy covers an eye ({st} {i}, facing {facing})"))
                            return out
    # lying on the floor, the grip is where the mouth reaches
    if r.floor - r.spots["grip"][1] != fit.floor - fit.toy_spot[1]:
        out.append(("fail", "the grip isn't at the height the cat reaches down to"))
    return out


_ = rect
