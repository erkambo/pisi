"""Coat colours and body-anchored patterns (shared by all furred families).

Colours are *material ramps*: every material has a fill, a shade and an
outline colour, so far legs, chin shading and contours stay readable on any
coat. Black is the darkest ramp, white the lightest.

Patterns are evaluated in body space, never screen space: torso pixels are
located by (distance along the spine, offset from the spine), legs by how far
down the leg they are, tails by arc length, heads by whole-pixel offsets from
the head origin. So markings ride on the body while it moves, and nothing
re-rolls between frames. Asymmetric patterns (calico patches, bicolour
edges) use the *visible flank* as part of their noise seed: facing left you
see the cat's other side, not a mirror image of the first.
"""
from __future__ import annotations

from dataclasses import dataclass

from .rng import MASK64, derive_seed, splitmix64
from .render import (EYE_FAR, EYE_FAR_SHADE, EYE_NEAR, EYE_NEAR_SHADE, FILL,
                     FX_WHITE, GLINT, LID, MOUTH, MOUTH_DARK, NOSE, OUTLINE,
                     SHADE, TEETH, TONGUE, CLAW, INNER_EAR, Palette)

RGB = tuple[int, int, int]

# materials
BASE, WHITE, PATCH, STRIPE, POINT = 0, 1, 2, 3, 4

# fill, shade, outline — tuned so the outline stays the darkest tone and
# shade is a small, cohesive step (PISI's look is low-contrast)
COLORS: dict[str, tuple[RGB, RGB, RGB]] = {
    "black":     ((38, 38, 38), (27, 27, 27), (19, 19, 19)),
    "charcoal":  ((62, 60, 64), (48, 46, 50), (26, 25, 28)),
    "chocolate": ((104, 72, 54), (84, 58, 44), (46, 30, 22)),
    "cinnamon":  ((168, 112, 78), (142, 92, 64), (78, 48, 32)),
    "grey":      ((118, 126, 138), (98, 105, 116), (54, 58, 66)),
    "lilac":     ((164, 152, 158), (140, 128, 136), (78, 70, 76)),
    "silver":    ((184, 188, 194), (156, 160, 168), (82, 86, 94)),
    "ginger":    ((220, 138, 58), (188, 108, 42), (112, 60, 24)),
    "apricot":   ((236, 176, 120), (212, 148, 96), (124, 82, 50)),
    "cream":     ((244, 230, 204), (224, 206, 174), (138, 118, 92)),
    "brown":     ((150, 116, 80), (126, 94, 64), (70, 50, 32)),
    "white":     ((236, 232, 224), (206, 200, 190), (112, 106, 100)),
    # warm marking tones
    "red":       ((196, 92, 40), (164, 72, 30), (92, 38, 16)),
    "tan":       ((206, 160, 104), (180, 134, 84), (104, 72, 42)),
    "sable":     ((122, 88, 52), (98, 70, 42), (54, 36, 20)),
}

STRIPE_OF: dict[str, str] = {   # stripe/patch partner colour per base
    "grey": "charcoal", "silver": "grey", "ginger": "red", "apricot": "ginger",
    "cream": "apricot", "brown": "sable", "chocolate": "black",
    "cinnamon": "chocolate", "lilac": "grey", "tan": "sable", "red": "sable",
    "sable": "black", "white": "silver", "charcoal": "black", "black": "charcoal",
}

EYES: dict[str, tuple[RGB, RGB]] = {
    "amber":  ((250, 188, 19), (192, 145, 17)),
    "gold":   ((236, 206, 60), (182, 150, 30)),
    "green":  ((104, 190, 64), (52, 128, 36)),
    "hazel":  ((188, 160, 64), (128, 104, 36)),
    "copper": ((232, 128, 44), (172, 86, 24)),
    "blue":   ((96, 170, 236), (58, 118, 196)),
    "brown":  ((92, 54, 30), (58, 32, 18)),        # dark enough on tan coats
}

NOSES: dict[str, RGB] = {
    "plum": (140, 31, 86), "pink": (224, 128, 142), "brick": (196, 90, 96),
    "dusky": (150, 96, 110), "black": (40, 30, 34),
}

FIXED = {
    GLINT: (255, 255, 255), MOUTH: (184, 63, 63), MOUTH_DARK: (195, 25, 25),
    TONGUE: (208, 88, 88), TEETH: (189, 189, 189), FX_WHITE: (255, 255, 255),
    CLAW: (214, 210, 200),
    INNER_EAR: (232, 146, 156),
}

PATTERNS = ("solid", "tabby", "spotted", "tuxedo", "bicolor", "van",
            "calico", "tortie", "point")


@dataclass(frozen=True)
class Coat:
    base: str = "black"
    pattern: str = "solid"
    second: str = ""            # stripe/patch colour ("" = automatic)
    white: float = 0.5          # amount of white for white-spotting patterns
    stripe_gap: float = 4.0     # tabby: px between stripes
    stripe_w: float = 1.0       # tabby: stripe thickness
    patch_scale: float = 5.0    # calico/tortie/spotted blob size
    seed: int = 0               # coat stream seed (patches)
    eye_left: str = "amber"
    eye_right: str = "amber"
    nose: str = "plum"
    socks: bool = True          # white paws for tuxedo/bicolor
    blaze: bool = False         # white stripe up the face

    def second_color(self) -> str:
        return self.second or STRIPE_OF.get(self.base, "black")


def _ramp(name: str) -> tuple[RGB, RGB, RGB]:
    return COLORS.get(name, COLORS["black"])


def palette(coat: Coat, side: str = "L") -> Palette:
    """Build the render palette. ``side`` is the flank facing the viewer:
    the near eye is that side's eye."""
    tones = {}
    second = coat.second_color()
    mats = {BASE: coat.base, WHITE: "white", PATCH: second,
            STRIPE: second, POINT: second}
    if coat.pattern == "point":
        mats[BASE] = "cream" if coat.base not in ("white", "silver") else coat.base
        mats[POINT] = coat.base if coat.base not in ("cream", "white") else "chocolate"
    if coat.pattern in ("calico", "tortie"):
        mats[PATCH] = "ginger" if coat.base not in ("ginger", "red", "apricot") else "black"
        if coat.base in ("grey", "lilac", "silver"):
            mats[PATCH] = "cream"
    for mid, cname in mats.items():
        f, s, o = _ramp(cname)
        tones[(mid, FILL)] = (*f, 255)
        tones[(mid, SHADE)] = (*s, 255)
        tones[(mid, OUTLINE)] = (*o, 255)
    near, far = (coat.eye_left, coat.eye_right) if side == "L" else (coat.eye_right, coat.eye_left)
    ne, fe = EYES.get(near, EYES["amber"]), EYES.get(far, EYES["amber"])
    roles = {k: (*v, 255) for k, v in FIXED.items()}
    roles[EYE_NEAR], roles[EYE_NEAR_SHADE] = (*ne[0], 255), (*ne[1], 255)
    roles[EYE_FAR], roles[EYE_FAR_SHADE] = (*fe[0], 255), (*fe[1], 255)
    roles[NOSE] = (*NOSES.get(coat.nose, NOSES["plum"]), 255)
    roles[LID] = tones[(BASE, OUTLINE)]
    return Palette(tones, roles)


# ---- deterministic value noise --------------------------------------------
def _hash01(ix: int, iy: int, seed: int) -> float:
    h = splitmix64((seed ^ ((ix & 0xFFFFFFFF) * 0x9E3779B1) ^
                    ((iy & 0xFFFFFFFF) << 32)) & MASK64)
    return (h >> 11) * (1.0 / 9007199254740992.0)


def noise(x: float, y: float, seed: int) -> float:
    ix, iy = int(x // 1), int(y // 1)
    fx, fy = x - ix, y - iy
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    a = _hash01(ix, iy, seed)
    b = _hash01(ix + 1, iy, seed)
    c = _hash01(ix, iy + 1, seed)
    d = _hash01(ix + 1, iy + 1, seed)
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy


# ---- local body coordinates -------------------------------------------------
def torso_uv(x: int, y: int, info: dict) -> tuple[float, float, float]:
    """(along, across, length): ``along`` px from the hip towards the
    shoulder, ``across`` px below the spine (negative = back)."""
    hx, hy = info["hip"]
    sx, sy = info["sh"]
    dx, dy = sx - hx, sy - hy
    L = (dx * dx + dy * dy) ** 0.5 or 1.0
    px, py = x + 0.5 - hx, y + 0.5 - hy
    along = (px * dx + py * dy) / L
    across = (py * dx - px * dy) / L
    return along, across, L


def _leg_t(x: int, y: int, info: dict) -> float:
    rx, ry = info["root"]
    ax, ay = info["ankle"]
    span = (ay + 3.0) - ry
    if span < 1.0:
        span = 1.0
    return (y + 0.5 - ry) / span


def _tail_s(x: int, y: int, info: dict) -> float:
    pts = info["tail"]
    best, best_s, acc = 1e9, 0.0, 0.0
    total = 0.0
    segs = []
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        ln = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        segs.append((ax, ay, bx, by, ln))
        total += ln
    cx, cy = x + 0.5, y + 0.5
    for ax, ay, bx, by, ln in segs:
        if ln < 1e-9:
            continue
        t = ((cx - ax) * (bx - ax) + (cy - ay) * (by - ay)) / (ln * ln)
        t = 0.0 if t < 0 else 1.0 if t > 1 else t
        qx, qy = ax + (bx - ax) * t - cx, ay + (by - ay) * t - cy
        d = qx * qx + qy * qy
        if d < best:
            best, best_s = d, (acc + t * ln)
        acc += ln
    return best_s / (total or 1.0)


def material(coat: Coat, region: str, x: int, y: int, info: dict) -> int:
    pat = coat.pattern
    if pat == "solid":
        return BASE
    side = info.get("side", "L")
    seed = derive_seed(coat.seed, "patch", side)
    wht = coat.white
    if region in ("torso",):
        along, across, L = torso_uv(x, y, info)
        a = info["anat"]
        v = across / (a.belly if across > 0 else a.top)     # -1 back .. +1 belly
        fr = along / L                                     # 0 hip .. 1 shoulder
        return _torso_mat(coat, pat, along, v, fr, seed, wht)
    if region == "leg":
        t = _leg_t(x, y, info)
        hind = info["leg"][1] == "h"
        return _leg_mat(coat, pat, t, hind, y, seed, wht, info)
    if region == "tail":
        s = _tail_s(x, y, info)
        return _tail_mat(coat, pat, s, seed, wht)
    if region == "head":
        ox, oy = info["origin"]
        return _head_mat(coat, pat, x - ox, y - oy, info, seed, wht)
    if region == "ear":
        return _ear_mat(coat, pat)
    return BASE


def _torso_mat(coat, pat, along, v, fr, seed, wht):
    if pat == "tabby":
        if v < 0.55:
            k = (along + 0.6 * v * 2.0 + coat.seed % 7) % coat.stripe_gap
            if k < coat.stripe_w:
                return STRIPE
        return BASE
    if pat == "spotted":
        if v < 0.7 and noise(along / (coat.patch_scale * 0.6), v * 2.2, seed) > 0.72:
            return STRIPE
        return BASE
    if pat == "tuxedo":
        if v > 0.45 and fr > 0.35 - 0.3 * wht:
            return WHITE
        if fr > 0.82 and v > -0.2:
            return WHITE
        return BASE
    if pat == "bicolor":
        edge = 0.35 - 0.9 * wht + 0.35 * (noise(along / 4.0, 0.0, seed) - 0.5)
        return WHITE if v > edge else BASE
    if pat == "van":
        if wht < 0.6 and noise(along / 3.5, v * 1.5, seed) > 0.80 and v < 0:
            return BASE
        return WHITE
    if pat in ("calico", "tortie"):
        if pat == "calico":
            edge = 0.45 - 0.9 * wht + 0.3 * (noise(along / 4.0, 3.0, seed) - 0.5)
            if v > edge:
                return WHITE
        n = noise(along / coat.patch_scale, (v + 1.0) * 1.6, seed)
        return PATCH if n > 0.5 else BASE
    if pat == "point":
        return BASE if fr < 0.9 else POINT if v < -0.3 else BASE
    return BASE


def _leg_mat(coat, pat, t, hind, y, seed, wht, info):
    if pat == "tabby":
        # near legs: two clean bands; 1px far legs stay plain (bands on a
        # 1px column read as noise)
        if info["leg"][0] == "f":
            return BASE
        return STRIPE if (0.45 < t < 0.55 or 0.68 < t < 0.76) else BASE
    if pat in ("tuxedo",):
        return WHITE if (coat.socks and t > 0.82) or (not hind and t > 0.8 - 0.5 * wht) else BASE
    if pat == "bicolor":
        return WHITE if t > 0.75 - 0.75 * wht or (coat.socks and t > 0.8) else BASE
    if pat == "van":
        return WHITE
    if pat == "calico":
        if t > 0.7 - 0.6 * wht:
            return WHITE
        return PATCH if noise(t * 2.0, 7.0 + (3 if hind else 0), seed) > 0.55 else BASE
    if pat == "tortie":
        return PATCH if noise(t * 2.0, 7.0 + (3 if hind else 0), seed) > 0.55 else BASE
    if pat == "point":
        return POINT if t > 0.35 else BASE
    return BASE


def _tail_mat(coat, pat, s, seed, wht):
    if pat == "tabby":
        k = (s * 14.0) % 3.0
        return STRIPE if (k < 1.0 and s > 0.15) else BASE
    if pat == "spotted":
        return STRIPE if s > 0.8 else BASE
    if pat == "van":
        return BASE if s > 0.15 else WHITE
    if pat in ("calico", "tortie"):
        return PATCH if noise(s * 3.0, 11.0, seed) > 0.5 else BASE
    if pat == "point":
        return POINT if s > 0.25 else BASE
    if pat in ("tuxedo", "bicolor"):
        return WHITE if (coat.blaze and s > 0.88) else BASE
    return BASE


def _ear_mat(coat, pat):
    """Ear flaps: dark on a pointed coat, else the base."""
    return POINT if pat == "point" else BASE


def _head_front_mat(coat, pat, hx, hy, info, seed, wht):
    """The head seen from the front (looking at you, mid-turn): the same
    markings as the side view, but mirrored about the nose."""
    hp = info["hp"]
    c, eye_y = hp.nose[0], hp.eye_far[1]
    d = abs(hx - c)
    if pat == "tabby":
        if (hy == 0 and d == 1) or (hy == 1 and d in (0, 2)):
            return STRIPE                                  # the forehead "M"
        return BASE
    if pat in ("tuxedo", "bicolor", "calico"):
        if coat.blaze and 0 <= hy <= eye_y + 1 and d == 0:
            return WHITE
        if hy >= eye_y + 2 and d <= (1 if wht <= 0.5 else 2) + (hy - eye_y - 2):
            return WHITE                                   # muzzle and chin, widening down
        if pat == "calico" and hy >= 0 and noise(d / 3.0, hy / 3.0 + 20.0, seed) > 0.62:
            return PATCH
        return BASE
    if pat == "van":
        if hy < eye_y:
            return BASE
        if coat.blaze and hy <= eye_y + 1 and d <= 1:
            return WHITE
        return WHITE if hy >= eye_y + 1 else BASE
    if pat == "tortie":
        return PATCH if noise(hx / 3.0, hy / 3.0 + 20.0, seed) > 0.55 else BASE
    if pat == "point":
        if hy < 0:
            return POINT
        dx = (hx - c) / (info["anat"].head.width * 0.45)
        dy = (hy - (eye_y + 2.0)) / 3.2
        return POINT if dx * dx + dy * dy < 1.0 else BASE
    return BASE


def _head_mat(coat, pat, hx, hy, info, seed, wht):
    if info.get("front"):
        return _head_front_mat(coat, pat, hx, hy, info, seed, wht)
    spec = info["anat"].head
    eye_y = spec.skull
    nx = spec.eye_x + spec.eye_gap
    if pat == "tabby":
        # forehead "M" marks and a cheek line
        if hy == 0 and hx in (spec.eye_x + 1, nx - 1):
            return STRIPE
        if hy == 1 and hx in (spec.eye_x + 1, (spec.eye_x + nx) // 2, nx - 1):
            return STRIPE
        if hy == eye_y + 2 and hx == 1:
            return STRIPE
        return BASE
    if pat in ("tuxedo", "bicolor", "calico"):
        if coat.blaze and hy <= eye_y + 1 and spec.eye_x + 1 < hx < nx - 1 and hy >= 0:
            return WHITE
        lower = eye_y + 2 if pat != "tuxedo" else eye_y + 2
        if hy >= lower and hx >= spec.eye_x - (1 if wht > 0.5 else 0):
            return WHITE
        if pat == "calico" and hy >= 0 and noise(hx / 3.0, hy / 3.0 + 20.0, seed) > 0.62:
            return PATCH
        return BASE
    if pat == "van":
        if hy < eye_y:
            return BASE
        if coat.blaze and hy <= eye_y + 1 and spec.eye_x < hx < nx:
            return WHITE
        return WHITE if hy >= eye_y + 1 or hx < 2 else BASE
    if pat == "tortie":
        return PATCH if noise(hx / 3.0, hy / 3.0 + 20.0, seed) > 0.55 else BASE
    if pat == "point":
        if hy < 0:                         # ears
            return POINT
        cx = (spec.eye_x + nx) / 2.0
        dx = (hx - cx) / (spec.width * 0.45)
        dy = (hy - (eye_y + 2.0)) / 3.2
        return POINT if dx * dx + dy * dy < 1.0 else BASE
    return BASE
