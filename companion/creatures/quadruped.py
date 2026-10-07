"""The quadruped body plan: torso + 4 IK legs + tail chain + ¾ head.

Shared by every four-legged family (cats, dogs, foxes, …): families only
differ in parameter ranges, head spec and motion personality. The plan turns
an anatomy and a pose into render layers; it never knows about states.

Leg naming: ``nh`` near hind, ``fh`` far hind, ``nf`` near fore, ``ff`` far
fore. "Near" is the side facing the viewer; far legs are drawn behind the
body in the shade tone. In the ¾ view the far
legs are the *inner* pair: the far hind stands in front of the near hind,
the far fore behind the near fore.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import raster
from .heads import HeadPixels, HeadSpec, build_head, build_head_front
from .render import FILL, SHADE, Layer
from .shapes import add, chain, sub, torso_polygon, two_bone

Pixel = tuple[int, int]
LEGS = ("nh", "fh", "nf", "ff")


@dataclass(frozen=True)
class LegSpec:
    root: tuple[float, float]  # offset from hip (hind) or shoulder (fore)
    ankle_dx: float            # rest ankle x relative to the hip/shoulder
    l1: float                  # upper bone
    l2: float                  # lower bone
    bend: int                  # +1 knee forward, -1 elbow back
    r_top: float               # radius at the root (thigh / upper arm mass)
    r: float = 1.0             # 1.0 -> 2px column (near), 0.5 -> 1px (far)
    seam_side: int = 0         # which side of the root shows a contour
    paw: int = 3               # paw length in px
    near: bool = True


def make_leg(root, ankle_dx, ground_drop, bend, r_top, r=1.0, seam_side=0,
             paw=3, near=True, split=0.52, slack=0.25) -> LegSpec:
    """Leg whose bones exactly span the rest stance (plus a little slack so
    the knee shows a hint of bend), split between upper and lower bone."""
    dx = ankle_dx - root[0]
    dy = ground_drop
    dist = (dx * dx + dy * dy) ** 0.5 + slack
    return LegSpec(root, ankle_dx, dist * split, dist * (1 - split), bend,
                   r_top, r, seam_side, paw, near)


@dataclass(frozen=True)
class QuadAnatomy:
    w: int
    h: int
    ground: float                     # ankle y when standing (paw below)
    hip: tuple[float, float]
    shoulder: tuple[float, float]
    back: float
    top: float
    belly: float
    front: float
    chest: float
    sag: float
    legs: dict                        # leg name -> LegSpec
    tail_base: tuple[float, float]    # offset from hip
    tail_ang: float                   # radians, rest
    tail_seg: float
    tail_bends: tuple[float, ...]
    tail_radii: tuple[float, ...]
    head: HeadSpec
    head_rel: tuple[int, int]         # head origin offset from shoulder
    neck_r: float = 1.6
    leap: float = 1.0                 # scales jump/pounce height (fit step)


@dataclass
class QuadPose:
    hip: tuple[float, float]
    shoulder: tuple[float, float]
    feet: dict[str, tuple[float, float]]        # ankle targets
    foot_rot: dict[str, float] = field(default_factory=dict)  # radians
    tail_ang: float = 0.0
    tail_bends: tuple[float, ...] = ()
    head_dx: int = 0
    head_dy: int = 0
    eyes: str = "open"
    mouth: str = "closed"
    ears: str = "up"
    look: int = 0
    hidden: tuple[str, ...] = ()        # legs not drawn (tucked under body)
    fx: list[tuple[int, int, int]] = field(default_factory=list)
    torso_scale: float = 1.0            # foreshortening during a turn
    head_hidden: bool = False
    head_view: str = "34"               # "34" | "front"
    paw_only: tuple[str, ...] = ()      # legs folded away: only the paw shows
    paw_len: dict[str, int] = field(default_factory=dict)
    root_d: dict[str, tuple[float, float]] = field(default_factory=dict)
    haunch: tuple[float, float, float, float] | None = None  # cx, cy, rx, ry
    tail_base: tuple[float, float] | None = None  # absolute override
    tail_z: int = 0                     # 0 behind the body, 6 in front
    tail_group: int = 1                 # 0: behind the far legs too
    top_d: float = 0.0                  # torso puff (loaf)
    belly_d: float = 0.0
    back_d: float = 0.0                 # rump extent (sitting tucks it in)
    rump: float = 1.0                   # rump corner chamfer (loaf rounds it)
    noseam: tuple[str, ...] = ()        # legs whose root contour is hidden
    rtop: dict[str, float] = field(default_factory=dict)  # root radius override
    neck: bool = True
    flash: bool = False                 # hit flash frame
    flip: bool = False                  # drawn facing the other way (turn)
    dome: tuple[float, float, float, float] | None = None  # curled body: cx, floor, rx, ry
    fore_over_head: bool = False        # near front leg drawn over the head (paw raised before the face)


def rest_feet(a: QuadAnatomy, hip=None, shoulder=None) -> dict:
    hip = hip or a.hip
    shoulder = shoulder or a.shoulder
    out = {}
    for leg, spec in a.legs.items():
        base = hip if leg[1] == "h" else shoulder
        out[leg] = (base[0] + spec.ankle_dx, a.ground - (0 if spec.near else 0.6))
    return out


def rest_pose(a: QuadAnatomy) -> QuadPose:
    return QuadPose(hip=a.hip, shoulder=a.shoulder, feet=rest_feet(a),
                    tail_ang=a.tail_ang, tail_bends=a.tail_bends)


def leg_root(a: QuadAnatomy, p: QuadPose, leg: str):
    base = p.hip if leg[1] == "h" else p.shoulder
    r = add(base, a.legs[leg].root)
    d = p.root_d.get(leg)
    return add(r, d) if d else r


def leg_points(a: QuadAnatomy, p: QuadPose, leg: str):
    spec = a.legs[leg]
    root = leg_root(a, p, leg)
    knee, ankle = two_bone(root, p.feet[leg], spec.l1, spec.l2, spec.bend)
    return root, knee, ankle


def paw_shape(rot: float) -> str:
    """Pick a hand-drawable paw shape from the foot angle: rotating a 3px
    paw polygon gives broken pixels, so poses choose between shapes."""
    if rot > 0.9:
        return "hang"
    if rot > 0.25:
        return "curl"
    if rot < -0.25:
        return "reach"
    return "flat"


# (dx, dy) offsets from the column's left pixel; near columns are 2px
NEAR_PAWS = {
    "flat": lambda L: [(x, 0) for x in range(0, L)] +
                      [(x, y) for y in (1, 2) for x in range(1, L + 1)],
    "curl": lambda L: [(0, 0), (1, 0), (0, 1), (1, 1), (-1, 2), (0, 2)],
    "reach": lambda L: [(0, 0), (1, 0), (2, 0), (1, 1), (2, 1), (3, 1)],
    "hang": lambda L: [(0, 0), (1, 0), (0, 1), (1, 1), (1, 2)],
}
FAR_PAWS = {
    "flat": lambda s: [(s - 1, 0), (s, 1), (s, 2)],
    "curl": lambda s: [(0, 0), (-1, 1)],
    "reach": lambda s: [(0, 0), (1, 0), (2, 1)],
    "hang": lambda s: [(0, 0), (0, 1)],
}


def paw_pixels(ankle, near: bool, rot: float, length: int = 3) -> set[Pixel]:
    """Paw under the leg column, rows ankle.y .. +2 (flat on the ground).
    Near paw: 3 wide on the first row, then one pixel forward for the pads.
    Far paw (1px leg): steps forward by ``length`` px so it peeks out past
    the near leg's contour."""
    ax, ay = ankle
    shape = paw_shape(rot)
    if near:
        cx = int((ax - 1.0) // 1)            # 2px column covers cx, cx+1
        cy = int(ay // 1)
        offs = NEAR_PAWS[shape](length)
    else:
        cx = int(ax // 1)
        cy = int((ay + 0.6) // 1)
        offs = FAR_PAWS[shape](length)
    return {(cx + dx, cy + dy) for dx, dy in offs}


def resample_bends(bends, n: int) -> list[float]:
    """Map a pose's tail bends onto an anatomy with ``n`` segments, keeping
    the total curl (poses are written for any tail length)."""
    m = len(bends)
    if m == n or m == 0:
        return list(bends)
    out = []
    for k in range(n):
        lo, hi = k * m / n, (k + 1) * m / n
        acc = 0.0
        for j in range(int(lo), min(m, int(hi) + 1)):
            ov = min(hi, j + 1) - max(lo, j)
            if ov > 0:
                acc += bends[j] * ov
        out.append(acc)
    return out


def tail_points(a: QuadAnatomy, p: QuadPose):
    base = p.tail_base or add(p.hip, a.tail_base)
    bends = resample_bends(p.tail_bends or a.tail_bends, len(a.tail_bends))
    return chain(base, p.tail_ang, a.tail_seg, bends)


def torso_joints(p: QuadPose) -> tuple[tuple[float, float], tuple[float, float]]:
    """Hip and shoulder as drawn (foreshortened during a turn)."""
    hip, sh = p.hip, p.shoulder
    ts = p.torso_scale
    if ts != 1.0:
        mid = ((hip[0] + sh[0]) / 2, (hip[1] + sh[1]) / 2)
        hip = (mid[0] + (hip[0] - mid[0]) * ts, hip[1])
        sh = (mid[0] + (sh[0] - mid[0]) * ts, sh[1])
    return hip, sh


def head_origin(a: QuadAnatomy, p: QuadPose) -> tuple[int, int]:
    """Top-left of the head's skull core, in whole pixels."""
    _hip, sh = torso_joints(p)
    return (int(round(sh[0])) + a.head_rel[0] + p.head_dx,
            int(round(sh[1])) + a.head_rel[1] + p.head_dy)


def head_pixels(a: QuadAnatomy, p: QuadPose, head_cache=None) -> HeadPixels:
    key = (p.head_view, p.eyes, p.mouth, p.ears, p.look)
    hp = head_cache.get(key) if head_cache is not None else None
    if hp is None:
        if p.head_view == "front":
            hp = build_head_front(a.head, p.eyes, p.mouth, p.ears)
        else:
            hp = build_head(a.head, p.eyes, p.mouth, p.ears, p.look)
        if head_cache is not None:
            head_cache[key] = hp
    return hp


def paw_point(a: QuadAnatomy, p: QuadPose, leg: str) -> Pixel:
    """The pixel at the middle of a paw (where it touches what it holds)."""
    if leg in p.paw_only:
        ax, ay = p.feet[leg]
    else:
        _root, _knee, (ax, ay) = leg_points(a, p, leg)
    if a.legs[leg].near:
        return int((ax - 1.0) // 1) + 1, int(ay // 1) + 1
    return int(ax // 1), int((ay + 0.6) // 1) + 1


def anchors(a: QuadAnatomy, p: QuadPose, head_cache=None) -> dict:
    """Where things are in this pose, in frame pixels facing right: the
    mouth (where a carried toy hangs from), the top of the head, each
    visible paw, and the floor row the pet stands on."""
    out: dict = {"ground": int(a.ground) + 3, "paws": {}, "mouth": None, "head_top": None}
    if not p.head_hidden:
        hp = head_pixels(a, p, head_cache)
        ox, oy = head_origin(a, p)
        nx, ny = hp.nose
        out["mouth"] = (ox + nx, oy + ny + 1)
        out["head_top"] = (ox + a.head.width // 2, oy)
    for leg in LEGS:
        if leg not in p.hidden:
            out["paws"][leg] = paw_point(a, p, leg)
    return out


def build_layers(a: QuadAnatomy, p: QuadPose, mat, head_cache=None,
                 side: str = "L") -> tuple[list[Layer], dict[Pixel, int]]:
    """``mat(region, x, y, info)`` -> material id for coat patterns.
    ``side`` is the flank facing the viewer (for asymmetric markings).
    Returns the layers plus post-compose tone strokes (chin, inner ear)."""
    w, h = a.w, a.h
    layers: list[Layer] = []
    tones: dict[Pixel, int] = {}
    info = {"pose": p, "anat": a, "side": side}

    def mf(region, extra=None):
        d = info if extra is None else {**info, **extra}

        def f(x, y):
            return mat(region, x, y, d)
        return f

    # ---- far legs (group 0, shade tone)
    for leg in ("fh", "ff"):
        if leg in p.hidden:
            continue
        spec = a.legs[leg]
        root, knee, ankle = leg_points(a, p, leg)
        if leg in p.paw_only:
            ankle = p.feet[leg]
            px = set()
        elif spec.r <= 0.5:
            px = raster.thin_line([root, knee, ankle], w, h)
        else:
            px = raster.polyline([root, knee, ankle], [spec.r_top, spec.r, spec.r], w, h)
        px |= paw_pixels(ankle, False, p.foot_rot.get(leg, 0.0), spec.paw)
        layers.append(Layer(leg, px, z=0, group=0, tone=SHADE,
                            material=mf("leg", {"leg": leg, "root": root, "ankle": ankle})))

    # ---- main group
    hip, sh = torso_joints(p)
    torso = raster.polygon(torso_polygon(hip, sh, a.back + p.back_d, a.top + p.top_d,
                                         a.belly + p.belly_d, a.front, a.chest,
                                         rump_round=p.rump, sag=a.sag), w, h)
    tmat = mf("torso", {"hip": hip, "sh": sh})
    layers.append(Layer("torso", torso, z=1, material=tmat))

    if p.dome:
        # a curled-up body: the top half of an ellipse standing on the floor
        cx, fy, rx, ry = p.dome
        dpx = {q for q in raster.ellipse((cx, fy), rx, ry, w, h) if q[1] <= fy}
        layers.append(Layer("dome", dpx, z=1.5, material=tmat))

    tp = tail_points(a, p)
    radii = list(a.tail_radii[:len(tp)])
    radii += [radii[-1]] * (len(tp) - len(radii))
    tail = raster.polyline(tp, radii, w, h)
    layers.append(Layer("tail", tail, z=p.tail_z if p.tail_group else -1,
                        group=p.tail_group, material=mf("tail", {"tail": tp}),
                        seam_from=tp[0] if p.tail_z else None, seam_min=2.5))

    if p.haunch:
        cx, cy, rx, ry = p.haunch
        # a "D": rounded front, flat back (one straight rump edge down to
        # the paw, like the artist draws it)
        hpx = raster.ellipse((cx, cy), rx, ry, w, h)
        hpx |= raster.polygon([(cx - rx + 0.2, cy - ry + 1.2), (cx, cy - ry + 1.2),
                               (cx, cy + ry + 1.0), (cx - rx + 0.2, cy + ry + 1.0)], w, h)
        layers.append(Layer("haunch", hpx, z=3.5, material=tmat,
                            seam_from=(cx, cy), seam_min=0.0, seam_side=1,
                            seam_dy=-ry + 0.5))

    # head (whole pixels only)
    ox, oy = head_origin(a, p)
    if not p.head_hidden:
        hp = head_pixels(a, p, head_cache)
        if p.neck:
            neck_a = (sh[0] - 0.5, sh[1] - a.top + 0.5)
            neck_b = (ox + 0.5, oy + 3.5)
            neck = raster.capsule(neck_a, neck_b, a.neck_r, a.neck_r, w, h)
            layers.append(Layer("neck", neck, z=1, material=tmat))
        head_core = {(ox + x, oy + y) for x, y in hp.core | hp.ears}
        ov = {(ox + x, oy + y): r for (x, y), r in hp.overrides.items()}
        hmat = mf("head", {"origin": (ox, oy), "hp": hp, "front": p.head_view == "front"})
        layers.append(Layer("head", head_core, z=4, material=hmat, overrides=ov))
        if hp.flap:
            fl = {(ox + x, oy + y) for x, y in hp.flap}
            fx_, fy_ = min(fl)
            layers.append(Layer("ear_flap", fl, z=4.5,
                                material=mf("ear", {"origin": (ox, oy), "hp": hp}),
                                seam_from=(fx_ - 50.0, fy_), seam_min=0.0))
        tones.update({(ox + x, oy + y): r for (x, y), r in hp.tones.items()})
        info["head_origin"] = (ox, oy)
        info["head"] = hp

    # near legs
    for leg in ("nh", "nf"):
        if leg in p.hidden:
            continue
        spec = a.legs[leg]
        root, knee, ankle = leg_points(a, p, leg)
        if leg in p.paw_only:
            ankle = p.feet[leg]
            px = set()
        else:
            px = raster.polyline([root, knee, ankle],
                                 [p.rtop.get(leg, spec.r_top), spec.r, spec.r], w, h)
        px |= paw_pixels(ankle, True, p.foot_rot.get(leg, 0.0),
                         p.paw_len.get(leg, spec.paw))
        layers.append(Layer(leg, px, z=5 if (leg == "nf" and p.fore_over_head) else 3,
                            material=mf("leg", {"leg": leg, "root": root, "ankle": ankle}),
                            seam_from=None if leg in p.noseam else root,
                            seam_min=spec.r_top - 0.4, seam_side=spec.seam_side))
    for x, y, r in p.fx:
        layers.append(Layer("fx", set(), z=9, group=9, overrides={(x, y): r}))
    return layers, tones


def apply_tones(frame, strokes: dict) -> None:
    """Shade strokes (chin, inner ear) only re-tone plain coat pixels."""
    w = frame.w
    for (x, y), t in strokes.items():
        if 0 <= x < w and 0 <= y < frame.h:
            i = y * w + x
            if frame.role[i] == FILL:
                frame.role[i] = t


_ = sub
