"""Shape helpers and the render result shared by every kind of thing.

Things are composed with the cat's own renderer (creatures/render.py): the
same 1px outline ring around each draw group, the same partial seams and
corner rule, coloured from (fill, shade, outline) ramps. A thing draws in
two images: ``back`` (behind the cat) and ``front`` (over it: a bed's front
rim, a basket's wall).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..creatures import raster
from ..creatures.render import FILL, OUTLINE, SHADE, Layer, close_corners, colorize, compose
from .palette import Mats

Pixel = tuple[int, int]
__all__ = ["FILL", "SHADE", "OUTLINE", "Layer", "Mats", "Rendered", "rect", "rounded",
           "ellipse", "paint"]


def rect(x0: int, y0: int, x1: int, y1: int) -> set[Pixel]:
    return {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}


def rounded(x0: int, y0: int, x1: int, y1: int, r: float) -> set[Pixel]:
    """A rectangle with round corners of radius ``r`` (pixel centres)."""
    out = set()
    r = max(0.0, min(r, (x1 - x0 + 1) / 2, (y1 - y0 + 1) / 2))
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            cx = min(max(x + 0.5, x0 + r), x1 + 1 - r)
            cy = min(max(y + 0.5, y0 + r), y1 + 1 - r)
            if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r + 0.01:
                out.add((x, y))
    return out


def ellipse(cx: float, cy: float, rx: float, ry: float, w: int, h: int) -> set[Pixel]:
    return raster.ellipse((cx, cy), rx, ry, w, h)


def paint(layers: list[Layer], w: int, h: int, mats: Mats) -> tuple[bytes, object]:
    """Compose layers in the house style and colour them. Returns the RGBA
    and the role grid (the judge checks outlines on it)."""
    fr = compose(layers, w, h)
    close_corners(fr)
    return colorize(fr, mats.palette()), fr


@dataclass
class Rendered:
    """A thing drawn for one cat.

    ``floor`` is the row of the image that stands on the floor (its bottom
    outline). The cat's frame goes at ``cat_at`` (top-left of the cat's
    frame, relative to the thing's top-left, cat facing right) when it uses
    the thing; ``spots`` are other named points in thing pixels.
    """
    kind: str
    w: int
    h: int
    back: bytes
    front: bytes | None
    floor: int
    back_frame: object = None            # role grids (render.Frame) for the judge
    front_frame: object = None
    cat_state: str | None = None
    cat_at: tuple[int, int] | None = None
    spots: dict = field(default_factory=dict)
    design: dict = field(default_factory=dict)

    def image(self, which: str, facing: int = 1) -> bytes | None:
        """``back`` or ``front`` as seen when the cat faces ``facing``: the
        cat facing left uses the thing from the other side, so the whole
        scene is the mirror image (a tower's pom-pom stays on the far side)."""
        from ..creatures.render import mirror_rgba
        data = self.back if which == "back" else self.front
        if data is None or facing >= 0:
            return data
        return mirror_rgba(data, self.w, self.h)

    def cat_at_facing(self, facing: int, frame_w: int) -> tuple[int, int] | None:
        """Where the cat's frame goes when it faces ``facing`` (the scene is
        mirrored for facing left, see :meth:`image`)."""
        if self.cat_at is None:
            return None
        x, y = self.cat_at
        return (x, y) if facing >= 0 else (self.w - frame_w - x, y)
