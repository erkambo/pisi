"""Scratching posts, side view, placed and sized from how that cat
scratches: the post's near face is where its front paws land, the sisal
reaches well above the top of its stroke, and the wear (frayed fibres)
sits exactly in the band it rakes.

The whole post is behind the cat (it stands in front of it, paws on the
near face).
"""
from __future__ import annotations

from ..draw import SHADE, Layer, Mats, Rendered, paint, rect, rounded
from ..fit import CatFit

STYLES = ("sisal", "tower", "log", "cactus", "cardboard", "deluxe")
DEFAULT = {"style": "sisal", "base": "oak", "top": "rose", "wear": 0.0}

POST_W = 4                     # core columns of the post itself


def render(design: dict, fit: CatFit) -> Rendered:
    d = {**DEFAULT, **design}
    style = d["style"]
    mats = Mats()
    rope = mats.id({"log": "walnut", "cactus": "cactus", "cardboard": "kraft"}.get(style, "sisal"))
    wood = mats.id(d["base"])
    top_m = mats.id(d["top"])
    pom = mats.id("yarn_red")

    # in the cat's frame rows: the post rises 6 px above the stroke's top
    towers = ("tower", "deluxe")
    top_row = fit.scratch_top - 6 - (3 if style in towers else 0)
    floor_row = fit.floor                     # the cat's floor (its bottom outline row)
    plat_w = 14 if style in towers else 0
    base_w = POST_W + {"cactus": 10, "cardboard": 8}.get(style, 6)
    pw = POST_W + {"cactus": 1, "cardboard": 4}.get(style, 0)   # the post's width
    W = max(base_w, plat_w) + 2 + {"tower": 4, "deluxe": 12, "cactus": 2}.get(style, 0)
    H = floor_row - top_row + 2 + (5 if style in towers else 0) + (2 if style == "cactus" else 0)
    off = H - 1 - floor_row                   # cat-frame row -> image row
    cx = (W - 1) / 2 - (4 if style == "deluxe" else 0)   # the deluxe's shelf reaches right
    p0 = int(round(cx - pw / 2 + 0.5))        # the post's near (left) core column
    p1 = p0 + pw - 1
    y_floor = H - 2
    y_top = top_row + off

    back: list[Layer] = []
    if style == "cactus":
        _cactus(back, mats, d, fit, p0, p1, y_top, y_floor, off, cx, base_w)
        return _done(back, mats, W, H, floor_row, p0, y_top, y_floor, fit, off, d)
    # base plate
    right = p1 + 11 if style == "deluxe" else int(cx + base_w / 2 - 0.5)   # under the shelf too
    base = rounded(int(cx - base_w / 2 + 0.5), y_floor - 1, right, y_floor, 0.5)
    bov = {(x, y): SHADE for (x, y) in base if y == y_floor}
    back.append(Layer("base", base, z=0, group=0, material=wood, tone_overrides=bov))
    # the post: rope wraps (rows alternate), right column in shade
    post = rect(p0, y_top, p1, y_floor - 2)
    pov = {}
    for (x, y) in post:
        if style == "cardboard":                 # layers of corrugated card, flutes showing
            if (y - y_top) % 3 == 2 and x % 2 == 0 or (y - y_top) % 3 == 0 and x > p0 or x == p1:
                pov[(x, y)] = SHADE
        elif style == "log":
            if (x * 3 + y * 5) % 7 == 0 or x == p1:
                pov[(x, y)] = SHADE
        elif (y - y_top) % 2 == 1 or x == p1:
            pov[(x, y)] = SHADE
    # wear: frayed fibres sticking out of the near face where the claws rake
    wear = float(d.get("wear", 0.0))
    fray = set()
    if wear > 0 and style not in ("log", "cardboard"):
        band = range(fit.scratch_top + off - 1, fit.scratch_bottom + off + 2)
        for k, y in enumerate(band):
            if (k * 7 + 3) % 10 < wear * 10:
                fray.add((p0 - 1, y))
                pov[(p0, y)] = SHADE
    back.append(Layer("post", post | fray, z=1, group=0, material=rope, tone_overrides=pov))
    if style == "deluxe":
        # a shelf halfway up on the far side, a cushion on top
        sy = (y_top + y_floor) // 2 - 2
        shelf = rounded(p1 + 1, sy, p1 + 9, sy + 2, 1.0)
        back.append(Layer("shelf", shelf, z=2, group=2, material=top_m,
                          tone_overrides={(x, y): SHADE for (x, y) in shelf if y == sy + 2}))
        leg = rect(p1 + 7, sy + 3, p1 + 8, y_floor - 2)
        back.append(Layer("shelf_post", leg, z=1, group=0, material=rope,
                          tone_overrides={(x, y): SHADE for (x, y) in leg
                                          if (y - sy) % 2 == 0 or x == p1 + 8}))
        cushion = rounded(int(cx - 5), y_top - 5, int(cx + 5), y_top - 4, 1.0)
        back.append(Layer("cushion", cushion, z=5, group=3, material=mats.id(d.get("cushion", d["base"])),
                          tone_overrides={(x, y): SHADE for (x, y) in cushion if y == y_top - 4}))
    if style in towers:
        plat = rounded(int(cx - plat_w / 2 + 0.5), y_top - 3, int(cx + plat_w / 2 - 0.5), y_top - 1, 1.0)
        tov = {(x, y): SHADE for (x, y) in plat if y == y_top - 1}
        back.append(Layer("platform", plat, z=2, group=0, material=top_m, tone_overrides=tov,
                          seam_from=(cx, y_top + 50.0)))
        # a pom-pom on a string from the platform's far edge
        sx = int(cx + plat_w / 2 - 2) if style == "tower" else int(cx - plat_w / 2 + 2) + 0
        if style == "deluxe":
            sx = p1 + 3
        string = {(sx, y) for y in range(y_top, y_top + 6)}
        ball = rounded(sx - 1, y_top + 6, sx + 1, y_top + 8, 1.5)
        back.append(Layer("string", string, z=3, group=1, material=wood, tone=SHADE))
        back.append(Layer("pompom", ball, z=4, group=1, material=pom))

    return _done(back, mats, W, H, floor_row, p0, y_top, y_floor, fit, off, d)


def _done(back, mats, W, H, floor_row, p0, y_top, y_floor, fit, off, d) -> Rendered:
    brgba, bfr = paint(back, W, H, mats)
    # the cat: its scratching paw lands on the post's near face
    cat_x = p0 - fit.post_x
    cat_y = (H - 1) - floor_row
    return Rendered(kind="post", w=W, h=H, back=brgba, front=None, floor=H - 1,
                    back_frame=bfr, front_frame=None, cat_state="scratch", cat_at=(cat_x, cat_y),
                    spots={"face": p0, "top": y_top, "bottom": y_floor - 2,
                           "band": (fit.scratch_top + off, fit.scratch_bottom + off)},
                    design=d)


def _cactus(back, mats, d, fit, p0, p1, y_top, y_floor, off, cx, base_w) -> None:
    """A cactus in a terracotta pot, a sisal band where the claws go, arms
    and a pink flower on top."""
    green, sisal = mats.id("cactus"), mats.id("sisal")
    pot_m, flower = mats.id("terracotta"), mats.id("felt_pink")
    pot_top = y_floor - 4
    pot = rounded(p0 - 2, pot_top + 1, p1 + 2, y_floor, 1.0) | rect(p0 - 3, pot_top, p1 + 3, pot_top + 1)
    back.append(Layer("pot", pot, z=0, group=0, material=pot_m,
                      tone_overrides={(x, y): SHADE for (x, y) in pot
                                      if y == pot_top + 1 or x >= p1 + 2 or y == y_floor}))
    body = rounded(p0, y_top, p1, pot_top - 1, 2.0)
    mid = (y_top + pot_top) // 2
    arm_r = rect(p1 + 1, mid, p1 + 2, mid + 1) | rounded(p1 + 2, mid - 5, p1 + 3, mid + 1, 1.0)
    arm_l = rect(p0 - 2, y_top + 4, p0 - 1, y_top + 5) | rounded(p0 - 3, y_top + 1, p0 - 2, y_top + 5, 1.0)
    cact = body | arm_r | arm_l
    ov = {(x, y): SHADE for (x, y) in cact if x in (p0 + 2, p1, p1 + 3, p0 - 2)}
    band = set(range(fit.scratch_top + off - 1, fit.scratch_bottom + off + 2))
    wrap = {(x, y) for (x, y) in body if y in band}
    back.append(Layer("cactus", cact - wrap, z=1, group=1, material=green, tone_overrides=ov))
    back.append(Layer("sisal", wrap, z=2, group=1, material=sisal,
                      tone_overrides={(x, y): SHADE for (x, y) in wrap
                                      if (y - y_top) % 2 == 1 or x == p1}))
    bloom = {(p0 + 1, y_top - 1), (p0 + 2, y_top - 1), (p0 + 3, y_top - 1), (p0 + 2, y_top - 2)}
    back.append(Layer("flower", bloom, z=3, group=2, material=flower,
                      tone_overrides={(p0 + 3, y_top - 1): SHADE}))


def check(r: Rendered, pet, fit: CatFit) -> list[tuple[str, str]]:
    """In use: the scratching paw is on the post's near face in every frame,
    inside the rope (never above the top or on the base), and the hind paws
    stand on the floor."""
    out: list[tuple[str, str]] = []
    fw = pet.size[0]
    for facing in (1, -1):
        cx, cy = r.cat_at_facing(facing, fw)
        face = r.spots["face"] - 1 if facing > 0 else r.w - 1 - r.spots["face"] + 1
        for i in range(pet.states()["scratch"].frames):
            an = pet.anchors("scratch", i, facing)
            px, py = an["paws"]["nf"]
            px, py = px + cx, py + cy
            if abs(px - face) > 1:
                out.append(("fail", f"the paw is off the post (x {px}, face {face}, frame {i}, facing {facing})"))
                return out
            if not (r.spots["top"] + 1 <= py <= r.spots["bottom"] - 1):
                out.append(("fail", f"the paw is past the rope (row {py}, frame {i})"))
                return out
            hy = an["paws"]["nh"][1] + cy
            if hy != r.h - 1 - 2:
                out.append(("fail", f"the hind paws aren't on the floor (row {hy}, frame {i})"))
                return out
    return out
