"""Food and water bowls, side view, placed where that cat's mouth goes
when it eats.

The bowl's rim stands just under the mouth at the bottom of an eating bob,
so the muzzle dips in: the back of the rim and the food are drawn behind
the cat's head, the front wall in front of it.
"""
from __future__ import annotations

from ..draw import SHADE, Layer, Mats, Rendered, paint, rect, rounded
from ..fit import CatFit

STYLES = ("ceramic", "steel", "fish", "speckled", "stand", "fountain")
CONTENTS = ("food", "water", "empty")
DEFAULT = {"style": "ceramic", "glaze": "glaze_blue", "contents": "food"}


def render(design: dict, fit: CatFit) -> Rendered:
    d = {**DEFAULT, **design}
    style = d["style"]
    mats = Mats()
    wall = mats.id({"steel": "steel", "stand": d.get("wood", "oak")}.get(style, d["glaze"]))
    inner = mats.id("porcelain" if style != "steel" else "steel")
    fill = mats.id("water" if d["contents"] == "water" or style == "fountain" else "food")

    mx, my = fit.eat_mouth
    floor_row = fit.floor                     # the cat's floor row in its frame
    rim = my + 1                              # the front wall's top core row
    height = floor_row - 1 - rim + 1          # core rows from the rim to the floor
    top_w = {"steel": 12, "stand": 13, "fountain": 15}.get(style, 11)
    extra = 4 if style == "fountain" else 0   # room above for the spout
    W, H = top_w + 2, height + 5 + extra      # + outline, the far rim and a food mound above
    x0, x1 = 1, W - 2
    y_rim = 4 + extra                         # front wall top in the image
    y_floor = H - 2
    back: list[Layer] = []
    front: list[Layer] = []

    # back: the far rim and what's in the bowl, seen just over the front wall
    back_rim = rect(x0 + 1, y_rim - 1, x1 - 1, y_rim)
    back.append(Layer("far_rim", back_rim, z=0, group=0, material=inner, tone=SHADE))
    if d["contents"] != "empty":
        surface = rect(x0 + 2, y_rim - 1, x1 - 2, y_rim)
        ov = {}
        if d["contents"] == "food":           # kibble: a little mound with bits
            surface |= {(x, y_rim - 2) for x in range(x0 + 3, x1 - 2)}
            for (x, y) in surface:
                if (x + y) % 3 == 0:
                    ov[(x, y)] = SHADE
        back.append(Layer("contents", surface, z=1, group=0, material=fill, tone_overrides=ov))

    if style == "fountain":
        # a bubbler at the back: a glazed dome, water welling up from its
        # top and running down its sides
        sx = x1 - 4
        dome = rect(sx - 1, y_rim - 3, sx + 1, y_rim)
        back.append(Layer("dome", dome, z=2, group=1, material=wall,
                          tone_overrides={(sx + 1, y): SHADE for y in range(y_rim - 3, y_rim + 1)}))
        flow = {(sx, y_rim - 5), (sx - 1, y_rim - 4), (sx, y_rim - 4), (sx + 1, y_rim - 4),
                (sx - 2, y_rim - 3), (sx + 2, y_rim - 3), (sx - 2, y_rim - 2), (sx + 2, y_rim - 2)}
        back.append(Layer("flow", flow, z=3, group=1, material=fill,
                          tone_overrides={(sx + 2, y_rim - 3): SHADE, (sx + 2, y_rim - 2): SHADE}))

    # front: the wall, wider at the top, a rim band and a foot
    taper = {"steel": 2, "stand": 0, "fountain": 1}.get(style, 1)
    body = set()
    for y in range(y_rim, y_floor + 1):
        k = round(taper * (y - y_rim) / max(1, y_floor - y_rim))
        body |= {(x, y) for x in range(x0 + k, x1 - k + 1)}
    if style in ("ceramic", "speckled", "fountain"):
        body = (body - {(x0, y_floor), (x1, y_floor)}) | rounded(x0 + 1, y_floor - 1, x1 - 1, y_floor, 1)
    elif style == "stand":                     # a wooden stand: legs at the ends
        body -= {(x, y_floor) for x in range(x0 + 2, x1 - 1)}
    ov = {}
    for (x, y) in body:
        if y >= y_floor or x >= x1 - (y - y_rim) * taper // max(1, y_floor - y_rim) - 1:
            ov[(x, y)] = SHADE                 # away from the light
    band = {(x, y) for (x, y) in body if y == y_rim}
    if style == "steel":                       # a bright streak down the wall
        for (x, y) in body:
            if x == x0 + 3 and y > y_rim:
                ov.pop((x, y), None)
    if style == "stand":                       # the planks' grain
        for (x, y) in body:
            if y == y_rim + 2 and x0 + 1 < x < x1 - 1:
                ov[(x, y)] = SHADE
    front.append(Layer("wall", body, z=0, group=0, material=wall, tone_overrides=ov))
    if style == "speckled":                    # stoneware: dark flecks in the glaze
        specks = {(x, y) for (x, y) in body if y > y_rim and (x + 2 * y) % 3 == 0
                  and (x, y) not in ov}
        front.append(Layer("specks", specks, z=2, group=0, material=mats.id(d.get("speck", "walnut"))))
    if style == "fish":                        # a little white fish on the side
        fy = (y_rim + y_floor) // 2 + 1
        fx = (x0 + x1) // 2
        fish = {(fx - 1, fy), (fx, fy), (fx + 1, fy), (fx, fy - 1), (fx - 2, fy - 1), (fx - 2, fy + 1)}
        front.append(Layer("fish", fish & body, z=2, group=0, material=inner))
    front.append(Layer("rim", band, z=1, group=0, material=inner,
                       seam_from=(W / 2, -50.0), seam_min=0.0))

    brgba, bfr = paint(back, W, H, mats)
    frgba, ffr = paint(front, W, H, mats)
    # where the cat stands: its eating mouth over the middle-back of the bowl
    mouth_in = x0 + 3
    cat_x = mouth_in - mx
    cat_y = (H - 1) - floor_row
    return Rendered(kind="bowl", w=W, h=H, back=brgba, front=frgba, floor=H - 1,
                    back_frame=bfr, front_frame=ffr, cat_state="eat", cat_at=(cat_x, cat_y),
                    spots={"rim": y_rim, "opening": (x0 + 1, x1 - 1)}, design=d)


def check(r: Rendered, pet, fit: CatFit) -> list[tuple[str, str]]:
    """In use: at the bottom of each eating bob the mouth is in the bowl's
    opening, just over the rim; the eyes are never behind the bowl; the cat
    stands on the same floor."""
    from ...creatures.render import EYE_FAR, EYE_NEAR, LID
    out: list[tuple[str, str]] = []
    fw = pet.size[0]
    for facing in (1, -1):
        cx, cy = r.cat_at_facing(facing, fw)
        front = r.image("front", facing)
        n = pet.states()["eat"].frames
        mouths = []
        for i in range(n):
            an = pet.anchors("eat", i, facing)
            mouths.append((an["mouth"][0] + cx, an["mouth"][1] + cy))
            fr, _ = pet.frame_grid("eat", i, facing)
            for k, role in enumerate(fr.role):
                if role in (EYE_FAR, EYE_NEAR, LID):
                    x, y = k % fr.w, k // fr.w
                    x = fr.w - 1 - x if facing < 0 else x
                    px, py = x + cx, y + cy
                    if 0 <= px < r.w and 0 <= py < r.h and front[(py * r.w + px) * 4 + 3]:
                        out.append(("fail", f"the bowl covers an eye (frame {i})"))
                        return out
        low = max(mouths, key=lambda m: m[1])
        o0, o1 = r.spots["opening"]
        if not (o0 <= low[0] <= o1):
            out.append(("fail", f"the mouth misses the bowl ({low[0]} not in {o0}..{o1}, facing {facing})"))
        if not (r.spots["rim"] - 2 <= low[1] <= r.spots["rim"]):
            out.append(("fail", f"the mouth isn't at the rim (row {low[1]}, rim {r.spots['rim']})"))
    return out
