"""The toy basket: a wicker basket the cat fetches its toys from.

Toys peek over the rim; the cat dips its muzzle in and bites the top toy at
the height every cat's pick-up pose reaches down to (``TOY_GRIP``), so it
lifts one straight out. The back wall and the toys are behind the cat's head, the front wall
in front of it.
"""
from __future__ import annotations

from ...creatures import quadmotion as QM
from ..draw import SHADE, Layer, Mats, Rendered, paint, rect, rounded
from ..fit import CatFit

STYLES = ("wicker", "crate", "felt", "box", "rope", "chest")
DEFAULT = {"style": "wicker", "toys": ("yarn_red", "yarn_blue")}


def render(design: dict, fit: CatFit) -> Rendered:
    d = {**DEFAULT, **design}
    style = d["style"]
    mats = Mats()
    wall = mats.id({"wicker": "wicker", "crate": "oak", "felt": d.get("fabric", "sage"),
                    "box": "kraft", "rope": "sisal", "chest": d.get("wood", "walnut")}[style])
    toy_a = mats.id(d["toys"][0])
    toy_b = mats.id(d["toys"][1] if len(d["toys"]) > 1 else d["toys"][0])
    G = QM.TOY_GRIP
    W = 16
    extra = {"box": 3, "chest": 6}.get(style, 0)   # room above for flaps or an open lid
    H = G + 5 + extra                       # the toys peek above the rim
    y_floor = H - 2
    floor_row = H - 1
    grip_row = floor_row - G
    rim = grip_row - 1                      # the wall stands above the grip: the muzzle dips in
    x0, x1 = 1, W - 2
    back: list[Layer] = []
    front: list[Layer] = []
    # the toys inside: a yarn ball (its top is the grip) and a ball beside it
    gx = 6
    inside = rect(0, 0, W - 1, y_floor - 1)  # (what sinks below the rim stays in the basket)
    yarn = rounded(gx - 2, grip_row - 3, gx + 2, grip_row + 1, 2.5) & inside
    yov = {(x, y): SHADE for (x, y) in yarn if (x - y) % 3 == 0}
    back.append(Layer("yarn", yarn, z=1, group=1, material=toy_a, tone_overrides=yov))
    ball = rounded(10, grip_row - 2, 13, grip_row + 1, 2.0) & inside
    back.append(Layer("ball", ball, z=0, group=0, material=toy_b,
                      tone_overrides={(x, y): SHADE for (x, y) in ball if x == 13}))
    # the far rim behind them
    far = rect(x0 + 1, rim - 1, x1 - 1, rim)
    back.append(Layer("far_rim", far, z=-1, group=0, material=wall, tone=SHADE))
    if style == "box":                      # the flaps stand up at the ends
        lf = {(x, rim - 2 - k) for k in range(3) for x in range(x0 + k // 2, x0 + 3 + k // 2)}
        rf = {(x, rim - 2 - k) for k in range(3) for x in range(x1 - 2 - k // 2, x1 + 1 - k // 2)}
        back.append(Layer("flaps", lf | rf, z=-2, group=0, material=wall,
                          tone_overrides={p: SHADE for p in rf}))
    elif style == "chest":                  # the lid, open and leaning back, lined inside
        lid = rect(x0 + 1, rim - 6, x1 - 1, rim - 2)
        back.append(Layer("lid", lid, z=0, group=-1, material=wall,
                          tone_overrides={(x, y): SHADE for (x, y) in lid if x == x1 - 1}))
        velvet = rect(x0 + 3, rim - 5, x1 - 3, rim - 2)
        back.append(Layer("lining", velvet, z=1, group=-1, material=mats.id(d.get("lining", "cherry")),
                          tone_overrides={(x, y): SHADE for (x, y) in velvet if y == rim - 5}))
    # the front wall
    body = rounded(x0, rim, x1, y_floor, {"rope": 2.5, "box": 0.0, "chest": 0.5}.get(style, 1.5))
    ov = {}
    for (x, y) in body:
        if style == "wicker":
            row = (y - rim) // 2
            if (y - rim) % 2 == 1 or (x + (2 if row % 2 else 0)) % 4 == 0:
                ov[(x, y)] = SHADE
        elif style == "crate":
            if x in (x0 + 4, x1 - 4) or y == y_floor:
                ov[(x, y)] = SHADE
        elif style == "rope":               # coils of rope, row on row
            if (y - rim) % 2 == 1 or x == x1:
                ov[(x, y)] = SHADE
        elif style == "box":
            if y == (rim + y_floor) // 2 + 1 and x0 + 1 < x < x1 - 1 or y == y_floor or x == x1:
                ov[(x, y)] = SHADE
        elif style == "chest":
            if y == y_floor or x == x1:
                ov[(x, y)] = SHADE
        elif y == y_floor or x == x1:
            ov[(x, y)] = SHADE
    front.append(Layer("wall", body, z=0, group=0, material=wall, tone_overrides=ov))
    lip = {(x, rim) for x in range(x0, x1 + 1)} & body
    front.append(Layer("lip", lip, z=1, group=0, material=wall, seam_from=(W / 2, -50.0)))
    if style == "chest":                    # iron bands and a little lock plate
        iron = mats.id("steel")
        bands = {(x, y) for (x, y) in body if x in (x0 + 3, x1 - 3) and y > rim}
        lock = {(W // 2 - 1, rim + 1), (W // 2, rim + 1), (W // 2 - 1, rim + 2), (W // 2, rim + 2)}
        front.append(Layer("bands", bands | (lock & body), z=2, group=0, material=iron,
                           tone_overrides={(W // 2, rim + 2): SHADE}))

    brgba, bfr = paint(back, W, H, mats)
    frgba, ffr = paint(front, W, H, mats)
    cat_x = gx - fit.toy_spot[0]
    cat_y = floor_row - fit.floor
    return Rendered(kind="basket", w=W, h=H, back=brgba, front=frgba, floor=floor_row,
                    back_frame=bfr, front_frame=ffr, cat_state="pickup", cat_at=(cat_x, cat_y),
                    spots={"grip": (gx, grip_row)}, design=d)


def check(r: Rendered, pet, fit: CatFit) -> list[tuple[str, str]]:
    """In use: picking up, the mouth reaches the top toy; the eyes stay
    above the front wall."""
    from ...creatures.render import EYE_FAR, EYE_NEAR, LID
    out: list[tuple[str, str]] = []
    w = pet.size[0]
    for facing in (1, -1):
        cx, cy = r.cat_at_facing(facing, w)
        front = r.image("front", facing)
        gx, gy = r.spots["grip"]
        if facing < 0:
            gx = r.w - 1 - gx
        n = pet.states()["pickup"].frames
        best = 99
        for i in range(n):
            mx, my = pet.anchors("pickup", i, facing)["mouth"]
            best = min(best, abs(mx + cx - gx) + abs(my + cy - gy))
            fr, _ = pet.frame_grid("pickup", i, facing)
            for k, role in enumerate(fr.role):
                if role in (EYE_FAR, EYE_NEAR, LID):
                    x, y = k % w, k // w
                    x = w - 1 - x if facing < 0 else x
                    u, v = x + cx, y + cy
                    if 0 <= u < r.w and 0 <= v < r.h and front[(v * r.w + u) * 4 + 3]:
                        out.append(("fail", f"the basket covers an eye (frame {i})"))
                        return out
        if best > 1:
            out.append(("fail", f"the mouth misses the toy by {best}px (facing {facing})"))
    return out
