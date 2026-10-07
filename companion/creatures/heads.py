"""Parametric ¾-view heads (facing right) built from per-row spans.

One builder serves cats, dogs and foxes: skull width/height, cheek, jaw
taper, muzzle length, ear specs and eye layout are all parameters. The head
is returned as pixel sets *relative to its origin* (top-left of the skull
core) so families can place it in whole pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .render import (EYE_FAR, EYE_FAR_SHADE, EYE_NEAR, EYE_NEAR_SHADE, GLINT,
                     LID, MOUTH, MOUTH_DARK, NOSE, OUTLINE, SHADE, TEETH, TONGUE,
                     FILL)
from .shapes import EarSpec, ear_inner, ear_spans

Pixel = tuple[int, int]


@dataclass(frozen=True)
class HeadSpec:
    width: int = 10          # core width at the cheeks
    skull: int = 2           # rows above the eyes
    face: int = 5            # rows from the eye line to the chin
    jaw: int = 2             # how many px the jaw tapers at the bottom
    muzzle: int = 0          # extra px of snout in front of the cheek (dogs)
    muzzle_rows: int = 3
    eye_gap: int = 4         # columns between far and near eye
    eye_x: int = 4           # far eye column
    eye_h: int = 2           # 2 = iris + iris shade, 3 = big eyes
    ear: EarSpec = field(default_factory=EarSpec)
    ear_far_x: int = 2       # far ear tip column
    ear_near_x: int = 8      # near ear tip column
    nose_dx: int = -1        # nose column relative to the near eye
    cheek_fluff: int = 0     # 1 = a fur tuft on the cheek contour


@dataclass
class HeadPixels:
    core: set[Pixel]                 # skull + face core
    ears: set[Pixel]                 # ear cores (part of the silhouette)
    overrides: dict[Pixel, int]      # feature roles
    tones: dict[Pixel, int]          # shade strokes that keep coat material
    eye_far: Pixel
    eye_near: Pixel
    nose: Pixel
    height: int
    mouth_box: tuple[int, int, int, int]
    flap: set = None                 # near drop-ear flap (drawn over the head)

    def __post_init__(self):
        if self.flap is None:
            self.flap = set()


def drop_ears(spec: HeadSpec, ears: str, core: set) -> tuple[set, set, set]:
    """Soft ears. ``EarSpec.drop`` picks the style:

    * 2 = **fold**: rises from the skull top and folds *forward*, the tip
      ending above the eye (labs, terriers);
    * 1 = **hang**: hangs at the back of the head, always behind the far
      eye's column so it never covers an eye (hounds, lop rabbits).

    The far ear peeks over the skull in shade. Returns (far core, far shade,
    near flap — drawn over the head with its own contour)."""
    wdt = max(2, min(4, spec.ear.width))
    back = 1 if ears in ("back", "flat") else 0
    lift = -1 if ears == "flick" else 0
    ex = spec.eye_x
    far = {(x, -1) for x in range(1, 1 + max(2, wdt - 1))}
    far -= core
    far_shade = set(far)
    flap = set()
    if int(spec.ear.drop) == 2:
        bx = max(1, ex - 1) - back
        rows = {-2: (1, 2), -1: (0, 3), 0: (2, 4), 1: (3, 4)}
        if spec.ear.height >= 5:
            rows[-3] = (1, 1)
        for r, (a, b) in rows.items():
            flap.update((bx + x, r + lift) for x in range(a, b + 1))
    else:
        h = max(3, spec.ear.height)
        right = max(1, ex - 2) - back            # stays behind the far eye
        left = max(0, right - wdt + 1)
        bottom = min(spec.skull + spec.face - 2, -1 + h)
        for r in range(-1 + lift, bottom + 1):
            a = left + (1 if r == -1 + lift else 0)
            b = right - (1 if r == bottom else 0)
            flap.update((x, r) for x in range(min(a, b), b + 1))
    return far, far_shade, flap


def build_head(spec: HeadSpec, eyes: str = "open", mouth: str = "closed",
               ears: str = "up", look: int = 0) -> HeadPixels:
    """eyes: open | half | closed | squint ; mouth: closed | open | wide |
    hiss ; ears: up | back | flat | flick ; look: -1/0/+1 shifts the irises."""
    w = spec.width
    rows: dict[int, tuple[int, int]] = {}
    sk = spec.skull
    # skull: rounded top
    if sk >= 2:
        rows[0] = (w * 2 // 5, w - 3)
        rows[1] = (w * 3 // 10, w - 2)
        for r in range(2, sk):
            rows[r] = (1, w - 1)
    else:
        rows[0] = (w * 3 // 10, w - 2)
    top_face = sk
    for i in range(spec.face):
        r = top_face + i
        right = w - 1
        from_bottom = spec.face - 1 - i
        if from_bottom < spec.jaw:
            right = w - 1 - (spec.jaw - from_bottom)
        left = 0
        if spec.muzzle and 1 <= i <= spec.muzzle_rows:
            right += spec.muzzle
        rows[r] = (left, right)
    core = {(x, r) for r, (a, b) in rows.items() for x in range(a, b + 1)}
    if spec.cheek_fluff:
        r = top_face + spec.face - 2
        core.add((rows[r][1] + 1, r))

    ov: dict[Pixel, int] = {}
    tones: dict[Pixel, int] = {}

    # ---- ears
    ear_px: set[Pixel] = set()
    espec = spec.ear
    if ears in ("back", "flat"):
        espec = EarSpec(max(2, espec.height - (2 if ears == "flat" else 1)),
                        espec.width, espec.fold, -1)
    pairs = () if spec.ear.drop else ((False, spec.ear_far_x), (True, spec.ear_near_x))
    flap: set = set()
    if spec.ear.drop:
        far, far_shade, flap = drop_ears(spec, ears, core)
        ear_px |= far
        for p_ in far_shade:
            tones[p_] = SHADE
    for near, tipx in pairs:
        es = espec
        if ears == "flick" and near:
            es = EarSpec(max(2, espec.height - 1), espec.width, espec.fold, 1)
        sp = ear_spans(es, near)
        h = len(sp)
        # far ear: base row level with the skull top; near ear: one higher
        shift_y = (1 - h) if not near else -h
        pts = {(tipx + x, shift_y + r) for r, (a, b) in sp.items()
               for x in range(a, b + 1)}
        ear_px |= pts
        for (x, r) in ear_inner(sp, near):
            tones[(tipx + x, shift_y + r)] = SHADE
    # (the far ear's base row is one pixel short of the skull, so the
    # outline ring separates them: it reads as the ear's own base seam)
    ear_px -= core
    # ---- eyes
    ey = top_face
    fx = spec.eye_x
    nx = spec.eye_x + spec.eye_gap
    if spec.muzzle:
        nx = min(nx, w - 2)
    ef, en = (fx, ey), (nx, ey)
    if eyes == "open":
        for (x, y), (top_role, low_role) in (
                ((fx, ey), (EYE_FAR, EYE_FAR_SHADE)),
                ((nx, ey), (EYE_NEAR, EYE_NEAR_SHADE))):
            xx = x + look
            if spec.eye_h >= 3:
                ov[(xx, y - 1)] = top_role
            ov[(xx, y)] = top_role
            ov[(xx, y + 1)] = low_role
    elif eyes == "half":
        for (x, y), low_role in (((fx, ey), EYE_FAR_SHADE), ((nx, ey), EYE_NEAR_SHADE)):
            ov[(x, y)] = LID
            ov[(x, y + 1)] = low_role
    elif eyes == "squint":                       # happy ^ ^
        for x, y in ((fx, ey), (nx, ey)):
            ov[(x, y)] = OUTLINE
            ov[(x - 1, y + 1)] = OUTLINE
    else:                                        # closed: lower-lid line
        # (perspective: the far lid reaches back, the near one forward)
        for x, y, d in ((fx, ey, -1), (nx, ey, 1)):
            ov[(x, y + 1)] = OUTLINE
            ov[(x + d, y + 1)] = OUTLINE
    # ---- nose & mouth
    nose = (nx + spec.nose_dx + spec.muzzle, ey + 2)
    if spec.muzzle:
        nose = (w - 1 + spec.muzzle, ey + 1)          # at the snout tip
    bottom = top_face + spec.face - 1
    mouth_box = (nose[0] - 3, nose[1] + 1, nose[0] + 1, bottom + 1)
    if mouth == "closed":
        ov[nose] = NOSE
        if spec.muzzle >= 2:
            ov[(nose[0], nose[1] + 1)] = NOSE          # a proper snout nose
            for xx in range(w - 2, nose[0]):           # mouth line
                ov[(xx, ey + spec.muzzle_rows)] = LID
    else:
        # open mouth: a dark cavity under the nose with tongue/teeth;
        # the jaw drops so the chin row moves down
        depth = 2 if mouth == "open" else 4
        wdt = 3 if mouth == "open" else 5
        x1 = min(w - 1 + spec.muzzle, nose[0] + 1)
        x0 = x1 - wdt + 1
        y0 = nose[1]
        for yy in range(y0, y0 + depth):
            for xx in range(x0, x1 + 1):
                core.add((xx, yy))
                ov[(xx, yy)] = MOUTH
        for xx in range(x0 + 1, x1):
            ov[(xx, y0 + depth - 1)] = TONGUE
        for xx in range(x0, x1 + 1):
            ov[(xx, y0)] = MOUTH_DARK
        if mouth in ("wide", "hiss"):
            ov[(x0, y0)] = TEETH
            ov[(x1, y0)] = TEETH
        # lower jaw below the cavity
        for xx in range(x0 - 1, x1):
            core.add((xx, y0 + depth))
        ov[(nose[0], nose[1] - 1)] = NOSE
    # chin shade + neck shade (house style)
    chin_y = bottom + 1
    for xx in range(2, 5):
        tones[(xx, chin_y)] = SHADE
    tones[(1, bottom)] = SHADE
    return HeadPixels(core=core, ears=ear_px, overrides=ov, tones=tones,
                      eye_far=ef, eye_near=en, nose=nose,
                      height=top_face + spec.face, mouth_box=mouth_box,
                      flap=flap)


def build_head_front(spec: HeadSpec, eyes: str = "open", mouth: str = "closed",
                     ears: str = "up") -> HeadPixels:
    """Symmetric front view (used mid-turn and when looking at the user).
    Same origin convention as the ¾ head; slightly narrower."""
    w = max(7, spec.width - 1)
    if w % 2 == 0:
        w -= 1                       # odd width -> a centre column for the nose
    c = w // 2
    rows: dict[int, tuple[int, int]] = {}
    sk = spec.skull
    rows[0] = (2, w - 3)
    if sk >= 2:
        rows[1] = (1, w - 2)
        for r in range(2, sk):
            rows[r] = (0, w - 1)
    for i in range(spec.face):
        r = sk + i
        from_bottom = spec.face - 1 - i
        t = max(0, spec.jaw - from_bottom)
        rows[r] = (t, w - 1 - t)
    core = {(x, r) for r, (a, b) in rows.items() for x in range(a, b + 1)}
    ov: dict[Pixel, int] = {}
    tones: dict[Pixel, int] = {}
    ear_px: set[Pixel] = set()
    es = spec.ear
    if ears in ("back", "flat"):
        es = EarSpec(max(2, es.height - (2 if ears == "flat" else 1)), es.width, es.fold)
    sp = ear_spans(es, False)
    h = len(sp)
    for tipx in (1, w - 2):
        for r, (a, b) in sp.items():
            for x in range(a, b + 1):
                ear_px.add((tipx + x, 1 - h + r))
        for (x, r) in ear_inner(sp, False):
            tones[(tipx + x, 1 - h + r)] = SHADE
    ear_px -= core
    ey = sk
    fx, nx = c - 2, c + 2
    if eyes == "open":
        ov[(fx, ey)] = EYE_FAR
        ov[(fx, ey + 1)] = EYE_FAR_SHADE
        ov[(nx, ey)] = EYE_NEAR
        ov[(nx, ey + 1)] = EYE_NEAR_SHADE
    elif eyes == "squint":
        for x in (fx, nx):
            ov[(x, ey)] = OUTLINE
            ov[(x - 1, ey + 1)] = OUTLINE
            ov[(x + 1, ey + 1)] = OUTLINE
    else:
        for x in (fx, nx):
            ov[(x, ey + 1)] = OUTLINE
            ov[(x + (1 if x > c else -1), ey + 1)] = OUTLINE
    nose = (c, ey + 2)
    if mouth == "closed":
        ov[nose] = NOSE
        if spec.muzzle >= 2:
            ov[(nose[0], nose[1] + 1)] = NOSE          # a proper snout nose
            for xx in range(w - 2, nose[0]):           # mouth line
                ov[(xx, ey + spec.muzzle_rows)] = LID
    else:
        ov[nose] = NOSE
        ov[(c, ey + 3)] = MOUTH_DARK
        if mouth != "open":
            ov[(c - 1, ey + 3)] = MOUTH
            ov[(c + 1, ey + 3)] = MOUTH
    bottom = sk + spec.face - 1
    for xx in range(c - 1, c + 2):
        tones[(xx, bottom + 1)] = SHADE
    return HeadPixels(core=core, ears=ear_px, overrides=ov, tones=tones,
                      eye_far=(fx, ey), eye_near=(nx, ey), nose=nose,
                      height=sk + spec.face, mouth_box=(c - 1, ey + 2, c + 1, ey + 4))


_ = (GLINT, FILL, TEETH, TONGUE, MOUTH)  # roles re-exported for families
