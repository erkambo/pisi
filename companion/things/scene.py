"""Put a cat and a thing together (no Qt): for the judge, tests and review
sheets. The app does the same with QPainter."""
from __future__ import annotations

from ..creatures import api
from .draw import Rendered


def over(dst: bytearray, dw: int, dh: int, src: bytes, sw: int, sh: int, ox: int, oy: int) -> None:
    """Alpha-over ``src`` onto ``dst`` at (ox, oy). Pixel art is opaque or
    clear, so a straight copy of opaque pixels is exact."""
    for y in range(sh):
        dy = y + oy
        if not 0 <= dy < dh:
            continue
        for x in range(sw):
            dx = x + ox
            if not 0 <= dx < dw:
                continue
            j = (y * sw + x) * 4
            if src[j + 3]:
                k = (dy * dw + dx) * 4
                dst[k:k + 4] = src[j:j + 4]


def compose(thing: Rendered, pet: api.Creature | None, state: str | None = None,
            frame: int = 0, facing: int = 1, margin: int = 0) -> tuple[bytes, int, int, tuple]:
    """The thing with the cat using it: back, cat, front. Returns (rgba, w, h,
    (cat_x, cat_y)) with the cat's frame position in the scene."""
    fw, fh = pet.size if pet else (0, 0)
    at = thing.cat_at_facing(facing, fw) if pet else None
    xs = [0, thing.w]
    ys = [0, thing.h]
    if at:
        xs += [at[0], at[0] + fw]
        ys += [at[1], at[1] + fh]
    x0, y0 = min(xs) - margin, min(ys) - margin
    w, h = max(xs) + margin - x0, max(ys) + margin - y0
    out = bytearray(w * h * 4)
    over(out, w, h, thing.image("back", facing), thing.w, thing.h, -x0, -y0)
    if pet and at:
        over(out, w, h, pet.frame(state or thing.cat_state, frame, facing), fw, fh,
             at[0] - x0, at[1] - y0)
    if thing.front:
        over(out, w, h, thing.image("front", facing), thing.w, thing.h, -x0, -y0)
    return bytes(out), w, h, ((at[0] - x0, at[1] - y0) if at else None)


def carry(toy: Rendered, pet: api.Creature, state: str = "carrywalk", frame: int = 0,
          facing: int = 1) -> tuple[bytes, int, int]:
    """The cat with a toy in its mouth (the toy drawn over the muzzle)."""
    from .kinds.toy import held_at
    w, h = pet.size
    out = bytearray(pet.frame(state, frame, facing))
    an = pet.anchors(state, frame, facing)
    tx, ty = held_at(toy, an["mouth"], facing)
    over(out, w, h, toy.image("back", facing), toy.w, toy.h, tx, ty)
    return bytes(out), w, h
