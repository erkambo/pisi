"""Beds, side view, sized to the cat curled up inside.

The inside is as wide as the cat's measured curl plus a little room; the
front rim comes up just far enough to tuck in the paws and the wrapped tail
(it's drawn over the cat); the back rim rises behind the cat's lower back.
Styles: ``donut`` (round bolster), ``cup`` (straighter, taller sides),
``pillow`` (a flat cushion with a low lip), ``box`` (a cardboard box with
its flaps up), ``basket`` (wicker), ``cave`` (a hooded bed: the hood arches
behind the cat), ``sofa`` (a little couch with arms and legs), ``teacup``
(a porcelain cup on a saucer, handle and all).
"""
from __future__ import annotations

from ..draw import FILL, SHADE, Layer, Mats, Rendered, ellipse, paint, rect, rounded
from ...creatures import quadmotion as QM
from ..fit import CatFit

STYLES = ("donut", "cup", "pillow", "box", "basket", "cave", "sofa", "teacup")
PATTERNS = ("plain", "stripes", "dots", "piping")

DEFAULT = {"style": "donut", "fabric": "rose", "lining": "blush", "pattern": "plain",
           "trim": "oatmeal"}


def _shade_lower_right(px: set, depth: int = 1, right: int = 1):
    """The faces turned away from the light (top-left): the bottom rows and
    the right edge of a shape."""
    if not px:
        return {}
    ys = [y for _, y in px]
    y1 = max(ys)
    out = {}
    rows: dict[int, int] = {}
    for x, y in px:
        rows[y] = max(rows.get(y, x), x)
    for x, y in px:
        if y > y1 - depth or x > rows[y] - right:
            out[(x, y)] = SHADE
    return out


def _weave(px: set, ov: dict, top: int) -> None:
    """Wicker: rows of 2px-tall bricks 3 wide, every other row offset, with
    the joints in shade (not a checkerboard)."""
    for (x, y) in px:
        row = (y - top) // 2
        if (y - top) % 2 == 1 or (x + (2 if row % 2 else 0)) % 4 == 0:
            ov.setdefault((x, y), SHADE)


def render(design: dict, fit: CatFit) -> Rendered:
    d = {**DEFAULT, **design}
    style = d["style"]
    mats = Mats()
    fab = mats.id({"box": "kraft", "basket": "wicker", "teacup": "porcelain"}.get(style, d["fabric"]))
    lin = mats.id("kraft" if style == "box" else d["lining"])
    trim = mats.id(d["trim"])
    legs = mats.id(d.get("legs", "walnut")) if style == "sofa" else None

    pad = 2 if style == "pillow" else 3
    t = {"donut": 4, "cup": 3, "pillow": 2, "box": 2, "basket": 3, "cave": 3, "sofa": 3,
         "teacup": 2}[style]                    # side thickness
    base = {"donut": 2, "cup": 2, "pillow": 3, "box": 1, "basket": 2, "cave": 2, "sofa": 3,
            "teacup": 3}[style]
    inner_w = fit.curl_w + 2 * pad
    handle = 4 if style == "teacup" else 0      # the cup's handle sticks out on the right
    W = inner_w + 2 * t + 2 + handle            # + the outline ring
    dome_h = fit.curl_h
    # the front rim tucks in the paws and the wrapped tail; the cat rests
    # its chin on it (the "curlrim" pose lifts the head exactly RIM px)
    cover = 0 if style == "pillow" else QM.RIM
    back_rise = {"donut": 0.5, "cup": 0.65, "pillow": 0.25, "box": 0.85, "basket": 0.6,
                 "cave": 1.45, "sofa": 0.95, "teacup": 0.0}[style]
    flap = 4 if style == "box" else 0
    back_h = max(cover + (3 if style == "teacup" else 2), int(round(dome_h * back_rise)))
    H = 1 + flap + back_h + base + 2            # outline above + ... + outline below
    y_floor = H - 2                             # bottom core row
    cushion = y_floor - base                    # the row the cat's bottom outline lies on
    back_top = cushion - back_h
    front_top = cushion - cover
    x0, x1 = 1, W - 2 - handle

    back: list[Layer] = []
    front: list[Layer] = []

    if style in ("cave", "sofa", "teacup"):
        _special(style, d, back, front, x0, x1, back_top, front_top, cushion, y_floor, t,
                 fab, lin, trim, legs, W, H)
    elif style == "donut":
        # a round bolster ring: the far side behind the cat, the near side
        # (a tube with round ends) in front of it, on a flat base
        tube = max(3, cover + 2)
        far = rounded(x0, back_top, x1, back_top + tube, tube / 2)
        sides = rounded(x0, back_top, x0 + t, y_floor, t / 2) | rounded(x1 - t, back_top, x1, y_floor, t / 2)
        back.append(Layer("far_bolster", far | sides, z=0, group=0, material=fab,
                          tone_overrides=_shade_lower_right(far | sides)))
        inside = rect(x0 + t, back_top + tube // 2, x1 - t, cushion)
        back.append(Layer("lining", inside, z=-1, group=0, material=lin, tone=SHADE))
        near = rounded(x0, front_top, x1, front_top + tube, tube / 2)
        basepx = rounded(x0 + 1, front_top + tube // 2, x1 - 1, y_floor, 1.5)
        nov = _shade_lower_right(near)
        _pattern(d["pattern"], near, nov, x0, front_top)
        front.append(Layer("base", basepx, z=0, group=0, material=fab, tone=SHADE))
        front.append(Layer("near_bolster", near, z=1, group=0, material=fab, tone_overrides=nov,
                           seam_from=(W / 2, front_top - 50.0), seam_min=0.0))
        if d["pattern"] == "piping":
            pipe = {(x, y) for (x, y) in near if y == front_top + tube // 2}
            front.append(Layer("piping", pipe, z=2, group=0, material=trim))
    else:
        r_out = {"cup": 2.0, "pillow": 2.0, "box": 0.0, "basket": 1.5}[style]
        body = rounded(x0, back_top, x1, y_floor, r_out)
        back.append(Layer("back_wall", body, z=0, group=0, material=fab,
                          tone_overrides=_shade_lower_right(body)))
        if style != "pillow":
            inside = rounded(x0 + t, back_top + max(1, t - 1), x1 - t, cushion, max(0.0, r_out - 1))
            back.append(Layer("lining", inside, z=1, group=0, material=lin, tone=SHADE))
        if style == "box":
            lf = {(x, back_top - 1 - k) for k in range(flap) for x in range(x0 + k // 2, x0 + 4 + k // 2)}
            rf = {(x, back_top - 1 - k) for k in range(flap) for x in range(x1 - 3 - k // 2, x1 + 1 - k // 2)}
            back.append(Layer("flap_l", lf, z=2, group=0, material=fab))
            back.append(Layer("flap_r", rf, z=2, group=0, material=fab, tone=SHADE))
        rim = rounded(x0, front_top, x1, y_floor, 1.5 if style == "pillow" else r_out)
        rov = _shade_lower_right(rim)
        if style == "basket":
            _weave(rim, rov, front_top + 2)
            lip = {(x, y) for (x, y) in rim if y <= front_top + 1}
            front.append(Layer("lip", lip, z=1, group=0, material=fab,
                               seam_from=(W / 2, front_top - 50.0)))
        elif style == "box":
            mid = (front_top + y_floor) // 2
            for (x, y) in rim:
                if y == mid and x0 + 2 < x < x1 - 2:
                    rov[(x, y)] = SHADE
        else:
            _pattern(d["pattern"], rim, rov, x0, front_top)
        front.append(Layer("front_rim", rim, z=0, group=0, material=fab, tone_overrides=rov))
        if d["pattern"] == "piping" and style == "cup":
            pipe = {(x, front_top + 1) for x in range(x0 + 1, x1)} & rim
            front.append(Layer("piping", pipe, z=2, group=0, material=trim))

    cat_x = int(round((x0 + x1 - fit.curl[0] - fit.curl[2]) / 2))   # curl centred inside
    cat_y = cushion - fit.floor
    brgba, bfr = paint(back, W, H, mats)
    frgba, ffr = paint(front, W, H, mats)
    return Rendered(kind="bed", w=W, h=H, back=brgba, front=frgba, floor=H - 1,
                    back_frame=bfr, front_frame=ffr,
                    cat_state="curl" if style == "pillow" else "curlrim", cat_at=(cat_x, cat_y),
                    spots={"cushion": cushion, "front_top": front_top, "back_top": back_top},
                    design=d)


def _special(style, d, back, front, x0, x1, back_top, front_top, cushion, y_floor, t,
             fab, lin, trim, legs, W, H) -> None:
    """The cave, the sofa and the teacup."""
    mid = (x0 + x1 + 1) / 2
    if style == "cave":
        # the hood: a tall arch behind the cat, its dark opening, and a
        # cushion rim in front like a cup's
        ry = cushion + 1 - back_top
        hood = {(x, y) for (x, y) in ellipse(mid, cushion + 1, (x1 - x0 + 1) / 2, ry, W, H)
                if y <= cushion} | rect(x0, cushion - 2, x1, y_floor)
        back.append(Layer("hood", hood, z=0, group=0, material=fab,
                          tone_overrides=_shade_lower_right(hood, 1, 2)))
        door = {(x, y) for (x, y) in ellipse(mid, cushion + 1, (x1 - x0 + 1) / 2 - t, ry - t, W, H)
                if y <= cushion}
        back.append(Layer("opening", door, z=1, group=0, material=lin, tone=SHADE))
        rim = rounded(x0, front_top, x1, y_floor, 2.0)
        rov = _shade_lower_right(rim)
        _pattern(d["pattern"], rim, rov, x0, front_top)
        front.append(Layer("front_rim", rim, z=0, group=0, material=fab, tone_overrides=rov))
        if d["pattern"] == "piping":
            pipe = {(x, front_top + 1) for x in range(x0 + 1, x1)} & rim
            front.append(Layer("piping", pipe, z=2, group=0, material=trim))
    elif style == "sofa":
        # a back rest with buttons, a seat cushion, arms at both ends, legs
        seat_bottom = y_floor - 1
        rest = rounded(x0 + 1, back_top, x1 - 1, cushion, 2.0)
        bov = _shade_lower_right(rest, 1, 1)
        for (x, y) in rest:
            if (x - x0) % 5 == 3 and (y - back_top) % 4 == 2 and y < cushion - 1:
                bov[(x, y)] = SHADE                     # tufting buttons
        back.append(Layer("backrest", rest, z=0, group=0, material=fab, tone_overrides=bov))
        seat = rounded(x0 + t, front_top, x1 - t, seat_bottom, 1.0)
        sov = {(x, y): SHADE for (x, y) in seat if y >= seat_bottom - 1}
        front.append(Layer("seat", seat, z=0, group=0, material=fab, tone_overrides=sov))
        arm_top = front_top - 2
        for ax0, ax1, name in ((x0, x0 + t, "arm_l"), (x1 - t, x1, "arm_r")):
            arm = rounded(ax0, arm_top, ax1, seat_bottom, 1.5)
            front.append(Layer(name, arm, z=1, group=1 if name == "arm_l" else 2, material=fab,
                               tone_overrides=_shade_lower_right(arm)))
        feet = {(x0 + 1, y_floor), (x0 + 2, y_floor), (x1 - 2, y_floor), (x1 - 1, y_floor)}
        front.append(Layer("legs", feet, z=-1, group=3, material=legs, tone=SHADE))
    else:
        # a porcelain cup on a saucer: round-bellied, a
        # coloured band under the rim, a handle loop on the right, the
        # lining showing inside
        sau_top = y_floor                               # a thin saucer: the cup gets the rows
        rim_back = rect(x0 + 1, back_top, x1 - 1, cushion)
        back.append(Layer("far_rim", rim_back, z=0, group=0, material=fab, tone=SHADE))
        back.append(Layer("lining", rect(x0 + 2, back_top + 1, x1 - 2, cushion), z=1, group=0,
                          material=lin, tone=SHADE))
        wall = set()
        rows = max(1, sau_top - 1 - front_top)
        for y in range(front_top, sau_top):           # round-bellied, narrowing to the foot
            k = round(((y - front_top) / rows) ** 2 * 5)
            wall |= {(x, y) for x in range(x0 + k, x1 - k + 1)}
        wov = _shade_lower_right(wall, 1, 2)
        for (x, y) in wall:
            if x == x0 + 2 and front_top + 2 < y < sau_top - 2:
                wov[(x, y)] = FILL                      # a glint down the side
        front.append(Layer("front_wall", wall, z=0, group=0, material=fab, tone_overrides=wov))
        band = {(x, front_top + 1) for x in range(x0 + 1, x1)} & wall
        front.append(Layer("band", band, z=1, group=0, material=trim))
        a, b2 = front_top + 1, front_top + 5
        loop = {(x1 + 1, a), (x1 + 2, a), (x1 + 3, a + 1)} | {(x1 + 3, y) for y in range(a + 1, b2)} \
            | {(x1 + 2, b2), (x1 + 1, b2)}
        front.append(Layer("handle", loop, z=-1, group=1, material=fab, tone=SHADE))
        saucer = rect(x0 + 1, sau_top, x1 - 1, y_floor)
        front.append(Layer("saucer", saucer, z=2, group=2, material=fab,
                           tone_overrides={(x, y): SHADE for (x, y) in saucer if x > x1 - 4}))


def _pattern(pattern: str, px: set, ov: dict, x0: int, top: int) -> None:
    if pattern == "stripes":
        for (x, y) in px:
            if (x - x0) % 4 == 2:
                ov[(x, y)] = SHADE
    elif pattern == "dots":
        for (x, y) in px:
            if (x - x0) % 4 == 1 and (y - top) % 3 == 1:
                ov[(x, y)] = SHADE



BLEND_DE = 22.0     # the cat reads apart from a bed whose colours differ by more


def check(r: Rendered, pet, fit: CatFit) -> list[tuple[str, str]]:
    """In use, for this cat: lies exactly on the cushion, stays between the
    bed's ends, the face is never covered, and doesn't vanish into it."""
    from ...creatures.render import (EYE_FAR, EYE_NEAR, FX_WHITE, LID, NOSE)
    from ..palette import delta_e
    out: list[tuple[str, str]] = []
    face_roles = {EYE_FAR, EYE_NEAR, LID, NOSE}
    fw = pet.size[0]
    for facing in (1, -1):
        cx, cy = r.cat_at_facing(facing, fw)
        front = r.image("front", facing)
        n = pet.states()[r.cat_state].frames
        for i in range(n):
            fr, _ = pet.frame_grid(r.cat_state, i, facing)
            if fr.flip:
                continue
            bottom, xs, face = -1, [], []
            for k, role in enumerate(fr.role):
                if not role or role == FX_WHITE:
                    continue
                x, y = k % fr.w, k // fr.w
                if facing < 0:
                    x = fr.w - 1 - x
                bottom = max(bottom, y)
                xs.append(x + cx)
                if role in face_roles:
                    face.append((x + cx, y + cy))
            if bottom + cy != r.spots["cushion"]:
                out.append(("fail", f"{'floats above' if bottom + cy < r.spots['cushion'] else 'sinks into'} the cushion (frame {i})"))
            if min(xs) < 1 or max(xs) > r.w - 2:
                out.append(("fail", f"sticks out of the bed (frame {i}, facing {facing})"))
            covered = [p for p in face if 0 <= p[0] < r.w and 0 <= p[1] < r.h
                       and front[(p[1] * r.w + p[0]) * 4 + 3]]
            if covered:
                out.append(("fail", f"the rim covers the face (frame {i}, facing {facing})"))
            if not face and r.cat_state != "curl":
                out.append(("warn", "no face visible"))
            if out and out[-1][0] == "fail":
                return out
    # the cat shouldn't disappear into the bed
    ff = r.front_frame
    rim = {tuple(r.front[k * 4:k * 4 + 3]) for k, ro in enumerate(ff.role) if ro and ro != 3}
    best = max((delta_e(fit.coat, c) for c in rim), default=99)
    if best < BLEND_DE:
        out.append(("warn", f"the coat is close to the bed's colour (dE {best:.0f})"))
    return out
