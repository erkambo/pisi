"""Where things stand in PISI's corner (no Qt).

Things stand on the floor in a row going out from the screen corner: the
bed in the corner, then the scratching post, the bowl, the toy basket.
Each thing leaves room beside it for the cat to stand while using it (the
cat always uses things facing into the room, away from the corner), so the
cat never stands in front of the bed to reach its bowl.

Positions are in frame pixels (the cat's pixel grid, before the on-screen
scale), measured from the strip's corner-side edge.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..creatures.render import FX_WHITE
from .draw import Rendered

ORDER = ("bed", "post", "bowl", "basket")   # from the corner outwards
GAP = 3                                      # px between one thing and the next
EDGE = 4                                     # px from the screen edge


@dataclass
class Placed:
    kind: str
    item_id: str
    r: Rendered
    x: int            # the thing's left edge in strip px (facing the room: see side)


def cat_room(r: Rendered, pet) -> int:
    """How far the cat's body reaches left of the thing's left edge while
    using it (0 if it stays over the thing, like a bed)."""
    if r.cat_at is None or pet is None:
        return 0
    x0 = None
    n = pet.states()[r.cat_state].frames
    for i in range(n):
        fr, _ = pet.frame_grid(r.cat_state, i, 1)
        for k, role in enumerate(fr.role):
            if role and role != FX_WHITE:
                x = k % fr.w
                x0 = x if x0 is None else min(x0, x)
    if x0 is None:
        return 0
    return max(0, -(r.cat_at[0] + x0))


def order_of(order=None) -> list[str]:
    """The kinds from the corner outwards: ``order`` (yours, from the
    Arrange window) first, then anything it leaves out in the usual order."""
    mine = [k for k in (order or ()) if k in ORDER]
    return list(dict.fromkeys(mine)) + [k for k in ORDER if k not in mine]


def layout(things: dict[str, tuple[str, Rendered]], pet=None,
           order=None) -> tuple[list[Placed], int, int]:
    """``things``: kind -> (item id, rendered thing). Returns the placements
    (left to right, the corner on the left), the strip's width and height."""
    out: list[Placed] = []
    x = EDGE
    for kind in order_of(order):
        if kind not in things:
            continue
        item_id, r = things[kind]
        x += cat_room(r, pet)
        out.append(Placed(kind, item_id, r, x))
        x += r.w + GAP
    width = x - GAP + EDGE if out else 0
    height = max((p.r.h for p in out), default=0)
    return out, width, height
