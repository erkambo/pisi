"""The parcel a bought thing arrives in: a kraft-paper box tied with a rose
ribbon and a bow, sized to the cat (it fits under its nose), closed or
opened (flaps up, the bow undone). Drawn in the house style like every
thing, and judged like one (tests/test_shop.py)."""
from __future__ import annotations

from .draw import SHADE, Layer, Mats, Rendered, paint, rect, rounded
from .fit import CatFit


def render(fit: CatFit, opened: bool = False) -> Rendered:
    mats = Mats()
    kraft = mats.id("kraft")
    ribbon = mats.id("rose")
    w = max(13, min(21, int(round(fit.curl_w * 0.72))))
    w += (w + 1) % 2                               # odd: the ribbon sits in the middle
    body_h = max(8, int(round(w * 0.55)))
    lid_h = 3
    bow_h = 4
    flap_h = 5
    top_room = flap_h if opened else bow_h
    lean = 3 if opened else 0                      # room for the open flaps leaning out
    W = w + 4 + 2 * lean                           # the lid overhangs 1 px each side, + outline
    H = 1 + top_room + lid_h + body_h + 1
    y_floor = H - 2
    body_top = y_floor - body_h + 1
    lid_top = body_top - lid_h
    x0, x1 = 2 + lean, W - 3 - lean                # the box's sides
    mid = W // 2

    back: list[Layer] = []
    box = rect(x0, body_top, x1, y_floor)
    shade = {p: SHADE for p in box if p[0] >= x1 - max(1, w // 5)}
    back.append(Layer("box", box, z=0, group=0, material=kraft, tone_overrides=shade))
    if opened:
        # an open box from the front: the back flap standing up behind the
        # opening, the two side flaps folded out at 45 degrees, the ribbon
        # untied and hanging down the front
        rear = rect(x0 + 2, body_top - flap_h + 1, x1 - 2, body_top - 1)
        back.append(Layer("rear_flap", rear, z=-1, group=0, material=kraft, tone=SHADE))
        fl = {(x0 - k + j, body_top - 1 - k) for k in range(flap_h - 1) for j in range(3)}
        fr = {(x1 + k - j, body_top - 1 - k) for k in range(flap_h - 1) for j in range(3)}
        back.append(Layer("flap_l", fl, z=2, group=1, material=kraft))
        back.append(Layer("flap_r", fr, z=2, group=1, material=kraft, tone=SHADE))
        band = rect(mid - 1, body_top + 1, mid + 1, y_floor)
        back.append(Layer("ribbon", band, z=3, group=2, material=ribbon))
    else:
        lid = rect(x0 - 1, lid_top, x1 + 1, body_top - 1)
        back.append(Layer("lid", lid, z=1, group=1, material=kraft,
                          tone_overrides={p: SHADE for p in lid if p[0] >= x1 - max(1, w // 5)}))
        band = rect(mid - 1, lid_top, mid + 1, y_floor)
        back.append(Layer("ribbon", band, z=3, group=2, material=ribbon))
        loops = rounded(mid - 5, lid_top - bow_h, mid - 1, lid_top - 1, 1.6) | \
            rounded(mid + 1, lid_top - bow_h, mid + 5, lid_top - 1, 1.6)
        back.append(Layer("bow", loops, z=4, group=3, material=ribbon,
                          tone_overrides={p: SHADE for p in loops if p[1] == lid_top - 1}))
        back.append(Layer("knot", rect(mid - 1, lid_top - 2, mid + 1, lid_top - 1), z=5,
                          group=4, material=ribbon, tone=SHADE))
    rgba, frame = paint(back, W, H, mats)
    return Rendered("parcel", W, H, rgba, None, y_floor + 1, back_frame=frame,
                    spots={"top": (mid, lid_top if not opened else body_top)},
                    design={"opened": opened})
