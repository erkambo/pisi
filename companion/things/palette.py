"""Material colours for things, in the cat's house style.

Every material is a (fill, shade, outline) ramp like a coat colour
(creatures/coat.py): the outline is the darkest tone, the shade a small,
cohesive step below the fill. That's what makes a bed sit next to the
cat instead of looking pasted on. Light comes from the top-left:
generators put SHADE on lower and right-facing parts.
"""
from __future__ import annotations

from ..creatures.render import FILL, OUTLINE, SHADE, Palette

RGB = tuple[int, int, int]

MATERIALS: dict[str, tuple[RGB, RGB, RGB]] = {
    # fabrics (beds, cushions)
    "rose":       ((222, 140, 150), (196, 114, 126), (110, 58, 68)),
    "blush":      ((240, 196, 196), (218, 168, 170), (130, 94, 98)),
    "sage":       ((150, 178, 138), (124, 152, 114), (64, 84, 58)),
    "sky":        ((132, 176, 214), (106, 148, 188), (52, 80, 112)),
    "mustard":    ((222, 180, 82), (194, 152, 62), (108, 80, 28)),
    "lavender":   ((176, 156, 206), (150, 130, 180), (82, 68, 108)),
    "terracotta": ((204, 112, 82), (176, 90, 64), (100, 48, 32)),
    "navy":       ((70, 84, 128), (56, 68, 106), (30, 36, 60)),
    "charcoal":   ((84, 84, 92), (66, 66, 74), (34, 34, 40)),
    "oatmeal":    ((226, 212, 186), (202, 186, 158), (122, 108, 86)),
    "mint":       ((164, 214, 190), (136, 188, 164), (68, 108, 92)),
    "cherry":     ((196, 64, 72), (166, 48, 58), (90, 24, 30)),
    # natural
    "oak":        ((196, 150, 98), (168, 124, 78), (96, 66, 38)),
    "walnut":     ((128, 86, 58), (104, 68, 46), (56, 34, 22)),
    "birch":      ((230, 212, 176), (206, 186, 148), (124, 106, 78)),
    "wicker":     ((210, 168, 108), (180, 138, 84), (104, 74, 40)),
    "sisal":      ((214, 190, 140), (186, 160, 112), (110, 90, 56)),
    "kraft":      ((198, 156, 106), (172, 130, 84), (98, 70, 40)),
    "cactus":     ((116, 168, 98), (90, 140, 78), (40, 76, 36)),
    # ceramic / plastic
    "porcelain":  ((240, 240, 236), (212, 214, 212), (120, 122, 126)),
    "glaze_blue": ((92, 140, 196), (72, 116, 168), (36, 60, 94)),
    "glaze_green": ((118, 170, 128), (94, 144, 104), (46, 80, 54)),
    "steel":      ((176, 184, 192), (146, 154, 164), (72, 78, 88)),
    "foil":       ((218, 224, 232), (176, 186, 200), (84, 92, 108)),
    # toys
    "felt_grey":  ((156, 156, 160), (130, 130, 136), (66, 66, 72)),
    "felt_pink":  ((236, 160, 172), (210, 134, 148), (118, 66, 78)),
    "yarn_red":   ((214, 76, 70), (182, 56, 54), (100, 28, 28)),
    "yarn_blue":  ((86, 136, 210), (66, 112, 182), (32, 58, 104)),
    "yarn_gold":  ((236, 192, 70), (206, 160, 50), (116, 84, 20)),
    "yarn_green": ((110, 182, 98), (86, 154, 78), (42, 88, 38)),
    "food":       ((168, 108, 62), (140, 86, 48), (80, 46, 24)),
    "water":      ((150, 200, 236), (120, 172, 216), (60, 100, 140)),
}

FABRICS = ("rose", "blush", "sage", "sky", "mustard", "lavender", "terracotta",
           "navy", "charcoal", "oatmeal", "mint", "cherry")
WOODS = ("oak", "walnut", "birch")
YARNS = ("yarn_red", "yarn_blue", "yarn_gold", "yarn_green")
GLAZES = ("porcelain", "glaze_blue", "glaze_green", "steel")


class Mats:
    """Assigns material ids (as used in render layers) to material names
    for one thing, and builds the matching palette."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def id(self, name: str) -> int:
        if name not in MATERIALS:
            raise KeyError(f"unknown material {name!r}")
        if name not in self.names:
            self.names.append(name)
        return self.names.index(name)

    def palette(self) -> Palette:
        tones = {}
        for i, name in enumerate(self.names):
            f, s, o = MATERIALS[name]
            tones[(i, FILL)] = (*f, 255)
            tones[(i, SHADE)] = (*s, 255)
            tones[(i, OUTLINE)] = (*o, 255)
        if not tones:
            tones[(0, FILL)] = tones[(0, SHADE)] = tones[(0, OUTLINE)] = (0, 0, 0, 255)
        return Palette(tones, {})


def luminance(rgb) -> float:
    """Relative luminance (sRGB, WCAG), 0..1."""
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    """WCAG contrast ratio between two colours (1..21)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def lab(rgb) -> tuple[float, float, float]:
    """sRGB -> CIE L*a*b* (D65)."""
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb[:3])
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a, b) -> float:
    """Perceptual colour difference (CIE76): ~2 just noticeable, < ~20
    reads as 'the same colour family' at pixel-art sizes."""
    la, lb = lab(a), lab(b)
    return sum((u - v) ** 2 for u, v in zip(la, lb)) ** 0.5
