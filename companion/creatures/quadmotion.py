"""Procedural animation for quadrupeds: every state PISI drives.

Poses are computed from the anatomy (so long legs take longer strides and a
long body sits differently), a motion personality, and the frame index —
never from stored sprites. Bodies move in whole pixels (the torso joints are
snapped) so markings don't shimmer; legs are solved with two-bone IK against
the ground so planted feet stay planted.

Every state is described by an :class:`AnimSpec` (frame count, fps, loop,
ground speed) and a pose function ``f(a, m, i, n) -> QuadPose``. Locomotion
cycles also report ``speed`` = sprite px travelled per frame, which the
desktop pet uses to set the playback rate from its real on-screen speed, so
paws don't slide whatever the speed setting is.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace

from . import dmath as M
from .quadruped import QuadAnatomy, QuadPose, rest_feet
from .render import FX_WHITE
from .rng import Rng


@dataclass(frozen=True)
class Motion:
    """Movement personality (motion genes)."""
    energy: float = 0.5        # bounce, tail liveliness, gait cadence
    tail_sway: float = 0.5     # how much the tail moves at rest
    stride: float = 1.0        # stride length multiplier
    blink: float = 0.5         # how often it blinks in idle loops
    curious: float = 0.5       # ear flicks / looking around
    carriage: float = 0.0      # -1 tail low .. +1 tail high while moving
    seed: int = 0


@dataclass(frozen=True)
class AnimSpec:
    name: str
    frames: int
    fps: float
    loop: bool
    speed: float = 0.0         # sprite px per frame (locomotion, foot-locked)
    hold_last: bool = False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _cp(p: QuadPose) -> QuadPose:
    q = copy.copy(p)
    q.feet = dict(p.feet)
    q.foot_rot = dict(p.foot_rot)
    q.paw_len = dict(p.paw_len)
    q.root_d = dict(p.root_d)
    q.fx = list(p.fx)
    return q


def _snap_body(p: QuadPose) -> QuadPose:
    p.hip = (float(round(p.hip[0])), float(round(p.hip[1])))
    p.shoulder = (float(round(p.shoulder[0])), float(round(p.shoulder[1])))
    return p


def _snap_feet(a: QuadAnatomy, p: QuadPose) -> QuadPose:
    for leg, (x, y) in p.feet.items():
        near = a.legs[leg].near
        x = float(round(x)) if near else float(round(x - 0.5)) + 0.5
        p.feet[leg] = (x, float(round(y * 2) / 2) if not near else float(round(y)))
    return p


def _move(p: QuadPose, dx: float = 0, dy: float = 0, feet: bool = False) -> QuadPose:
    p.hip = (p.hip[0] + dx, p.hip[1] + dy)
    p.shoulder = (p.shoulder[0] + dx, p.shoulder[1] + dy)
    if feet:
        p.feet = {k: (x + dx, y + dy) for k, (x, y) in p.feet.items()}
    return p


def tail_wave(a: QuadAnatomy, p: QuadPose, phase: float, amp_deg: float,
              lag: float = 0.12, base_amp: float = 0.35, curl_deg: float = 0.0) -> None:
    """Travelling wave along the tail: each segment follows the one before it
    a little later (follow-through), the tip moves most."""
    rest = list(p.tail_bends or a.tail_bends)
    n = len(rest)
    out = []
    for i, b in enumerate(rest):
        wgt = (i + 1) / n
        out.append(b + M.deg(amp_deg * wgt * M.wave(phase - i * lag)) / n * 2.2
                   + M.deg(curl_deg) * wgt / n * 2.0)
    p.tail_bends = tuple(out)
    p.tail_ang = p.tail_ang + M.deg(amp_deg * base_amp * M.wave(phase))


def kpose(a: QuadAnatomy, base: QuadPose | None = None, hip=(0, 0), sh=(0, 0),
          feet=None, rot=None, tail=0.0, curl=0.0, head=(0, 0), **kw) -> QuadPose:
    """A keyframe relative to ``base`` (default: standing): body deltas,
    per-leg foot deltas from the rest stance, foot shapes, tail angle (deg)
    and extra pose fields."""
    p = _cp(base) if base is not None else stand(a)
    rest = rest_feet(a)
    p.hip = (p.hip[0] + hip[0], p.hip[1] + hip[1])
    p.shoulder = (p.shoulder[0] + sh[0], p.shoulder[1] + sh[1])
    for leg, (dx, dy) in (feet or {}).items():
        x0, y0 = rest[leg]
        p.feet[leg] = (x0 + dx, y0 + dy)
    for leg, r in (rot or {}).items():
        p.foot_rot[leg] = M.deg(r)
    p.tail_ang += M.deg(tail)
    if curl:
        p.tail_bends = tuple(b + M.deg(curl) * (k + 1) / len(p.tail_bends or a.tail_bends)
                             for k, b in enumerate(p.tail_bends or a.tail_bends))
    p.head_dx += head[0]
    p.head_dy += head[1]
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def stand(a: QuadAnatomy) -> QuadPose:
    from .quadruped import rest_pose
    return rest_pose(a)


def leg_len(a: QuadAnatomy, leg: str) -> float:
    s = a.legs[leg]
    return s.l1 + s.l2


def sit(a: QuadAnatomy) -> QuadPose:
    """Upright sit: haunch on the ground,
    front legs straight, tail along the ground with the tip curling up past
    the front paws."""
    p = stand(a)
    BL = a.shoulder[0] - a.hip[0]
    hip = (a.hip[0] + 2.0, a.ground - 2.0)
    ang = M.deg(-53.13)
    ln = BL * 1.0
    sh = (hip[0] + M.cos(ang) * ln, hip[1] + M.sin(ang) * ln)
    p.hip, p.shoulder = hip, sh
    _snap_body(p)
    hip, sh = p.hip, p.shoulder
    p.back_d = -2.0
    p.belly_d = 0.6
    p.top_d = -0.5
    thigh = a.legs["nh"].r_top
    p.haunch = (hip[0] - 0.5, hip[1] - 1.0, thigh + 0.6, thigh + 0.1)
    p.paw_only = ("nh",)
    p.hidden = ("fh",)
    p.noseam = ("nf",)
    p.feet["nh"] = (hip[0] - 3.0, a.ground)
    p.paw_len = {"nh": 3 + a.legs["nh"].paw}
    # front legs: straight columns from roots lowered into the chest
    nf_root = (sh[0] - 1.0, a.ground - leg_len(a, "nf") + 0.15)
    ff_root = (sh[0] + 1.5, a.ground - 0.6 - leg_len(a, "ff") + 0.15)
    p.root_d = {"nf": (nf_root[0] - (sh[0] + a.legs["nf"].root[0]),
                       nf_root[1] - (sh[1] + a.legs["nf"].root[1])),
                "ff": (ff_root[0] - (sh[0] + a.legs["ff"].root[0]),
                       ff_root[1] - (sh[1] + a.legs["ff"].root[1]))}
    p.feet["nf"] = (sh[0] - 1.0, a.ground)
    p.feet["ff"] = (sh[0] + 1.5, a.ground - 0.6)
    # tail: out from behind the haunch and the far paw, along the ground,
    # tip curling up past the front paws
    p.tail_base = (hip[0] + 1.0, a.ground + 2.0)
    p.tail_ang = M.deg(0)
    p.tail_bends = (0.0, 0.0, 0.0, M.deg(-4), M.deg(-18), M.deg(-40))
    p.tail_group = 0
    p.rtop = {"nf": 1.0}
    p.neck = False
    p.head_dx, p.head_dy = -3, 1
    return _snap_feet(a, p)


def loaf(a: QuadAnatomy) -> QuadPose:
    """Lying down, legs folded (sleep / settle): rounded rump, paw stubs,
    tail along the ground."""
    p = stand(a)
    drop = (a.ground + 2.0) - (a.hip[1] + a.belly)
    _move(p, 0, drop)
    _snap_body(p)
    hip, sh = p.hip, p.shoulder
    p.rump = 3.5
    p.back_d = 0.5
    thigh = a.legs["nh"].r_top
    p.haunch = (hip[0] - 1.5, hip[1] + 1.5, thigh - 0.5, thigh - 0.6)
    p.neck = False
    p.paw_only = ("nh", "fh", "nf", "ff")
    p.feet = {"nh": (hip[0] - 2.0, a.ground), "fh": (hip[0] + 1.5, a.ground - 0.6),
              "nf": (sh[0] - 2.0, a.ground), "ff": (sh[0] + 1.5, a.ground - 0.6)}
    p.tail_base = (hip[0] - a.back + 0.5, hip[1])
    p.tail_ang = M.deg(142)
    p.tail_bends = (0.0, M.deg(8), M.deg(14), M.deg(18), M.deg(26), M.deg(30))
    p.head_dx, p.head_dy = -3, 0
    p.eyes = "closed"
    return _snap_feet(a, p)


def curl_geometry(a: QuadAnatomy) -> dict:
    """The curl's size from the anatomy: a dome as long as ~85% of the cat's
    body and a little taller than its depth, the head on its front. Used by
    the pose and by anything sized to the cat (a bed)."""
    BL = a.shoulder[0] - a.hip[0]
    floor = a.ground + 2.0
    rx = round((BL + a.back + a.front) * 0.42 * 2) / 2
    # as tall as the body is deep, but kept within a cat's proportions: a
    # long cat curls into a long oval, not a flat slug; a deep one isn't a tower
    ry = float(round(min(max(a.top + a.belly + 1.0, rx * 1.15), rx * 1.4)))
    cx = float(round((a.hip[0] + a.shoulder[0]) / 2 - 2))
    return {"cx": cx, "floor": floor, "rx": rx, "ry": ry}


def curl(a: QuadAnatomy, k: float = 1.0, lift: int = 0) -> QuadPose:
    """Curled up asleep, the way a cat sleeps in a bed: the back rounds into
    a dome, the folded hind leg shows as a curve on the flank, the head
    rests on the front of the dome with the chin down, and the tail wraps
    along the floor in front of the body, its tip curling up under the nose.
    Everything is placed from the anatomy, so a long cat makes a long oval
    and a stubby one a ball.

    ``lift`` raises the head (and a front paw) that many px so the chin
    rests on a bed's front rim (``RIM``) instead of the floor.

    ``k`` < 1 is on the way there (lying down -> curling): a lower, longer
    dome, the head still up, the tail still behind until it sweeps round."""
    g = curl_geometry(a)
    cx, floor, rx, ry = g["cx"], g["floor"], g["rx"], g["ry"]
    lo = loaf(a)
    u = 1.0 - k
    rx_k = rx + u * 2.0
    ry_k = float(round(ry - u * max(0.0, ry - (a.top + a.belly))))
    p = stand(a)
    # the boxy torso shrinks inside the dome (it still anchors the coat)
    p.hip, p.shoulder = (cx - 3.0, floor - 3.0), (cx + 3.0, floor - 3.0)
    p.top_d = -(a.top - 2.0)
    p.belly_d = 3.0 - a.belly
    p.back_d = -1.0
    p.dome = (cx, floor, rx_k, ry_k)
    # the folded hind leg: a round thigh at the back of the dome
    p.haunch = (cx - rx_k * 0.3, floor - ry_k * 0.36 - 0.5, rx_k * 0.62, ry_k * 0.36)
    p.paw_only = ("nf",)
    p.hidden = ("fh", "ff", "nh")
    # head on the front of the dome, chin on the floor (from where it was
    # when lying down)
    hgt = a.head.skull + a.head.face
    ox1, oy1 = int(round(cx + rx - 4.0)), int(round(floor - hgt)) - lift
    ox0, oy0 = head_origin_of(a, lo)
    ox = int(round(ox0 + (ox1 - ox0) * k))
    oy = int(round(oy0 + (oy1 - oy0) * k))
    p.head_dx = ox - (int(round(p.shoulder[0])) + a.head_rel[0])
    p.head_dy = oy - (int(round(p.shoulder[1])) + a.head_rel[1])
    p.neck = False
    p.eyes = "closed" if k > 0.8 else "half"
    p.feet = {"nf": (ox + a.head.width - 4.0, a.ground - (lift if k >= 1.0 else 0))}
    if k >= 0.5:
        # tail: from the back of the dome forward along the floor, in front
        p.tail_base = (cx - rx_k + 2.0, floor - 1.0)
        p.tail_ang = M.deg(0)
        p.tail_bends = (0.0, 0.0, 0.0, M.deg(-8), M.deg(-24), M.deg(-40))
        p.tail_z = 6
        p.tail_group = 1
    else:
        # still lying out behind, like the loaf
        p.tail_base = (cx - rx_k + 1.0, lo.tail_base[1])
        p.tail_ang, p.tail_bends = lo.tail_ang, lo.tail_bends
    return _snap_feet(a, p)


RIM = 3       # px a rimmed bed's front rim stands above its cushion: the chin rests on it


def curl_loop(a, m, i, n, lift: int = 0):
    """Asleep in a curl: the back rises and falls, the tail tip twitches now
    and then, z's drift up from the head."""
    p = curl(a, 1.0, lift)
    breath = M.wave(i / n)
    if breath > 0.3:
        cx, fy, rx, ry = p.dome
        p.dome = (cx, fy, rx, ry + 0.7)
    tb = list(p.tail_bends)
    tb[-1] += M.deg(14 * m.tail_sway * M.wave(i / n - 0.2))
    p.tail_bends = tuple(tb)
    hx, hy = head_origin_of(a, p)
    k = i % n
    for j in range(min(3, k + 1) if k < 3 else max(0, 3 - (k - 3))):
        _z(p, hx - 3 - j * 3, hy - 9 - j * 4, small=(j == 0))
    return p


def head_origin_of(a: QuadAnatomy, p: QuadPose) -> tuple[int, int]:
    from .quadruped import head_origin
    return head_origin(a, p)


def halfsit(a: QuadAnatomy) -> QuadPose:
    """Between standing and sitting: hindquarters lowered first, front still
    up — the way a cat actually sits down."""
    p = stand(a)
    p.hip = (p.hip[0] + 1.0, p.hip[1] + 4.0)
    p.shoulder = (p.shoulder[0] - 1.0, p.shoulder[1] - 1.0)
    p.feet["nh"] = (p.feet["nh"][0] + 1.0, p.feet["nh"][1])
    p.feet["fh"] = (p.feet["fh"][0] + 0.0, p.feet["fh"][1])
    # tail droops back along the floor and curls up at the tip (it is
    # about to wrap around the paws)
    p.tail_ang = M.deg(168)
    p.tail_bends = (0.0, 0.0, M.deg(4), M.deg(8), M.deg(16), M.deg(22))
    p.head_dy = 0
    _snap_body(p)
    return _snap_feet(a, p)


def crouch(a: QuadAnatomy, depth: float = 3.0) -> QuadPose:
    """Low stance, feet planted, tail low."""
    p = stand(a)
    _move(p, 0, depth)
    _snap_body(p)
    p.tail_ang = a.tail_ang + M.deg(-30)
    p.tail_bends = tuple(b * 0.3 for b in a.tail_bends)
    return p


def _blend_num(x, y, t):
    return x + (y - x) * t


def blend(a: QuadAnatomy, p: QuadPose, q: QuadPose, t: float) -> QuadPose:
    """Interpolate two poses (numeric controls lerp, discrete ones switch at
    t >= 0.5)."""
    r = _cp(q if t >= 0.5 else p)
    r.hip = (_blend_num(p.hip[0], q.hip[0], t), _blend_num(p.hip[1], q.hip[1], t))
    r.shoulder = (_blend_num(p.shoulder[0], q.shoulder[0], t),
                  _blend_num(p.shoulder[1], q.shoulder[1], t))
    feet = {}
    for k in p.feet:
        if k in q.feet:
            feet[k] = (_blend_num(p.feet[k][0], q.feet[k][0], t),
                       _blend_num(p.feet[k][1], q.feet[k][1], t))
    r.feet = feet
    pt = p.tail_base
    qt = q.tail_base
    if (pt is None) != (qt is None) or abs(p.tail_ang - q.tail_ang) > M.deg(100):
        # the tail re-anchors (behind the rump <-> wrapped on the ground):
        # swinging between them would sweep it through the body, so switch
        src = q if t >= 0.5 else p
        r.tail_ang, r.tail_bends, r.tail_base = src.tail_ang, src.tail_bends, src.tail_base
        r.tail_group = src.tail_group
        pt = qt = None
    else:
        r.tail_ang = _blend_num(p.tail_ang, q.tail_ang, t)
        pb = list(p.tail_bends or a.tail_bends)
        qb = list(q.tail_bends or a.tail_bends)
        r.tail_bends = tuple(_blend_num(x, y, t) for x, y in zip(pb, qb))
    if pt or qt:
        from .shapes import add
        pt = pt or add(p.hip, a.tail_base)
        qt = qt or add(q.hip, a.tail_base)
        r.tail_base = (_blend_num(pt[0], qt[0], t), _blend_num(pt[1], qt[1], t))
    r.head_dx = int(round(_blend_num(p.head_dx, q.head_dx, t)))
    r.head_dy = int(round(_blend_num(p.head_dy, q.head_dy, t)))
    rd = {}
    for k in set(p.root_d) | set(q.root_d):
        x0, y0 = p.root_d.get(k, (0.0, 0.0))
        x1, y1 = q.root_d.get(k, (0.0, 0.0))
        rd[k] = (_blend_num(x0, x1, t), _blend_num(y0, y1, t))
    r.root_d = rd
    if p.haunch and q.haunch:
        r.haunch = tuple(_blend_num(x, y, t) for x, y in zip(p.haunch, q.haunch))
    r.top_d = _blend_num(p.top_d, q.top_d, t)
    r.belly_d = _blend_num(p.belly_d, q.belly_d, t)
    _snap_body(r)
    return _snap_feet(a, r)


def _rng(m: Motion, label: str) -> Rng:
    return Rng(m.seed, label)


# ---------------------------------------------------------------------------
# loops
# ---------------------------------------------------------------------------
def idle(a, m, i, n):
    """Standing idle: tail sway with follow-through, a blink, an ear flick."""
    p = stand(a)
    ph = i / n
    tail_wave(a, p, ph, 10 + 22 * m.tail_sway)
    r = _rng(m, "idle")
    blink_at = r.randint(n // 2, n - 2)
    if i == blink_at:
        p.eyes = "half"
    elif i == blink_at + 1:
        p.eyes = "closed"
    if m.curious > 0.35 and i == r.randint(1, n // 2 - 1):
        p.ears = "flick"
    return p


def sit_loop(a, m, i, n):
    """Sitting: breathing (chest 1px), tail-tip flicks, blink."""
    p = sit(a)
    ph = i / n
    tb = list(p.tail_bends)
    flick = M.wave(ph) * (8 + 16 * m.tail_sway)
    tb[-1] += M.deg(flick)
    tb[-2] += M.deg(flick * 0.5)
    p.tail_bends = tuple(tb)
    if (i % n) in (n // 2, n // 2 + 1):
        p.belly_d = 0.6                      # breath in
    r = _rng(m, "sit")
    b = r.randint(1, n - 2)
    if i == b:
        p.eyes = "half"
    elif i == b + 1 and m.blink > 0.3:
        p.eyes = "closed"
    if m.curious > 0.6 and i == (b + n // 2) % n:
        p.ears = "flick"
    return p


def sleep_loop(a, m, i, n):
    """Curled up, slow breathing, drifting z's."""
    p = loaf(a)
    breath = M.wave(i / n)
    if breath > 0.3:
        p.top_d = 1.0
    tail_wave(a, p, i / n, 4 * m.tail_sway, base_amp=0.0)
    # z glyphs rising above the head
    hx = int(round(p.shoulder[0])) + a.head_rel[0] + p.head_dx
    hy = int(round(p.shoulder[1])) + a.head_rel[1] + p.head_dy
    k = i % n
    for j in range(min(3, k + 1) if k < 3 else 3 - (k - 3)):
        _z(p, hx - 4 - j * 3, hy - 6 - j * 4, small=(j == 0))
    return p


def _z(p: QuadPose, x: int, y: int, small: bool) -> None:
    glyph = ["**", ".*", "*.", "**"] if small else ["***", "..*", ".*.", "*..", "***"]
    for dy, row in enumerate(glyph):
        for dx, ch in enumerate(row):
            if ch == "*":
                p.fx.append((x + dx, y + dy, FX_WHITE))


# footfall patterns: phase offset per leg + duty factor + stride (px at
# leg length 8). Families pick one (a dog trots, a cat walks).
WALK = {"offs": {"nh": 0.0, "nf": 0.25, "fh": 0.5, "ff": 0.75}, "duty": 0.62, "S": 5.0,
        "lift": 2.0, "spread": {"fh": 1.0, "ff": -1.0}, "crouch": 1.0}
TROT = {"offs": {"nh": 0.0, "ff": 0.0, "fh": 0.5, "nf": 0.5}, "duty": 0.5, "S": 6.0,
        "lift": 2.0, "spread": {"fh": 1.5, "ff": -1.5}, "crouch": 1.0}


def gait(a: QuadAnatomy, m: Motion, i: int, n: int, *, run: bool,
         pattern: dict | None = None) -> QuadPose:
    """Walk (lateral sequence, duty 0.62) or trot-run.

    Each foot: stance = slides back at exactly the body speed (locked to the
    ground), swing = lifts on an arc and reaches forward. Hips/shoulders dip
    when their legs take weight; the head follows the shoulder one frame
    late; the tail rides the gait with a lagged wave."""
    p = stand(a)
    pat = pattern or WALK
    LL = a.ground - a.hip[1]
    S = pat["S"] * m.stride * (LL / 8.0) ** 0.5
    duty = pat["duty"]
    crouch_px = pat["crouch"]                # legs need slack to reach the stride
    offs = pat["offs"]
    lift = pat["lift"]
    ph = i / n
    rest = rest_feet(a)
    dips = {"h": 0.0, "f": 0.0}
    spread = pat["spread"]
    for leg, off in offs.items():
        f = (ph + off) % 1.0
        x0, y0 = rest[leg]
        x0 += spread.get(leg, 0.0)
        if f < duty:
            s = f / duty
            dx = S * (0.5 - s)
            dy = 0.0
            rot = 0.0
            if s < 0.25:
                dips[leg[1]] = max(dips[leg[1]], 1.0 - s * 4)
        else:
            s = (f - duty) / (1 - duty)
            e = M.smooth(s)
            dx = S * (-0.5 + e)
            dy = -lift * M.sin(M.PI * s) * (1.0 if a.legs[leg].near else 0.6)
            rot = M.deg(35) * M.sin(M.PI * s)
        p.feet[leg] = (x0 + dx, y0 + dy)
        p.foot_rot[leg] = rot
    bob = 1.0 + m.energy if run else 0.5 + m.energy
    hip_dy = round(min(1.0, dips["h"] * bob))
    sh_dy = round(min(1.0, dips["f"] * bob))
    if run:
        # spine flex: gather and extend once per stride
        flex = M.wave(ph) * 1.0
        p.hip = (p.hip[0] - round(flex), p.hip[1] + hip_dy)
        p.shoulder = (p.shoulder[0] + round(flex), p.shoulder[1] + sh_dy - 1)
    else:
        p.hip = (p.hip[0], p.hip[1] + hip_dy + crouch_px)
        p.shoulder = (p.shoulder[0], p.shoulder[1] + sh_dy + crouch_px)
    # the head rides with the shoulders (it used to follow them a frame late:
    # at this size that read as the neck twitching against the body)
    p.head_dy = 0
    carry = M.deg(12 * m.carriage) + (M.deg(-10) if run else 0.0)
    p.tail_ang = a.tail_ang + carry + (M.deg(25) if run else 0.0)
    tail_wave(a, p, ph * (1 if run else 2) - 0.25, 8 + 8 * m.energy, lag=0.15)
    _snap_body(p)
    return _snap_feet(a, p)


def gait_speed(pattern: dict):
    """Ground px per frame for a footfall pattern (for foot locking)."""
    def speed(a: QuadAnatomy, m: Motion, n: int) -> float:
        LL = a.ground - a.hip[1]
        return pattern["S"] * m.stride * (LL / 8.0) ** 0.5 / (pattern["duty"] * n)
    return speed


def walk(a, m, i, n):
    return gait(a, m, i, n, run=False)


walk.speed = gait_speed(WALK)


CRAWL = {"offs": {"nh": 0.0, "nf": 0.25, "fh": 0.5, "ff": 0.75}, "duty": 0.72, "S": 3.2,
         "lift": 0.8, "spread": {"fh": 1.0, "ff": -1.0}, "crouch": 0.0}


def crawl(a, m, i, n):
    """Belly to the floor, squeezing through somewhere low: short slow
    steps, head down and forward, ears back, tail out flat behind."""
    p = gait(a, m, i, n, run=False, pattern=CRAWL)
    drop = max(0.0, (a.ground - 1.5) - (a.hip[1] + a.belly))   # belly just off the floor
    p.hip = (p.hip[0], p.hip[1] + drop)
    p.shoulder = (p.shoulder[0] + 1.0, p.shoulder[1] + drop)
    p.head_dx += 3
    p.head_dy += int(round(drop)) + 6                         # head level with the back
    p.ears = "flat"
    p.tail_ang = M.deg(178)
    p.tail_bends = tuple(b * 0.2 for b in (p.tail_bends or a.tail_bends))
    p.neck = False
    _snap_body(p)
    return _snap_feet(a, p)


crawl.speed = gait_speed(CRAWL)


def trot(a, m, i, n):
    return gait(a, m, i, n, run=False, pattern=TROT)


trot.speed = gait_speed(TROT)


RUN_KEYS = (
    # rotary gallop: collected landing,
    # push, reach, full stretch in flight, gather, fore touchdown.
    # (tail: negative = streams out behind)
    dict(hip=(0, -1), sh=(0, 0), feet={"nf": (1, 0), "ff": (-1, 0), "nh": (4, -3), "fh": (5, -2)},
         rot={"nh": 40, "fh": 40}, tail=-15),
    dict(hip=(0, 0), sh=(0, -1), feet={"nf": (-3, 0), "ff": (-4, -2), "nh": (3, 0), "fh": (4, 0)},
         rot={"ff": 40}, tail=-20),
    dict(hip=(-1, -1), sh=(1, -2), feet={"nf": (8, -4), "ff": (7, -5), "nh": (-2, 0), "fh": (-1, 0)},
         rot={"nf": -40, "ff": -40}, tail=-30),
    dict(hip=(-2, -2), sh=(2, -2), feet={"nf": (12, -4), "ff": (11, -5), "nh": (-11, -3), "fh": (-10, -4)},
         rot={"nf": -40, "ff": -40, "nh": 40, "fh": 40}, tail=-40),
    dict(hip=(-1, -3), sh=(1, -3), feet={"nf": (3, -4), "ff": (4, -5), "nh": (2, -4), "fh": (3, -4)},
         rot={"nf": 40, "ff": 40, "nh": 40, "fh": 40}, tail=-30),
    dict(hip=(0, -2), sh=(0, -1), feet={"nf": (3, 0), "ff": (2, -1), "nh": (5, -4), "fh": (6, -3)},
         rot={"nh": 40, "fh": 40, "ff": 40}, tail=-20),
)
RUN_SPEED = 2.6            # sprite px per frame of the gallop


def run(a, m, i, n):
    LL = a.ground - a.hip[1]
    k = min(1.15, LL / 8.0)                  # long legs: stretch, but stay in frame
    key = RUN_KEYS[i % len(RUN_KEYS)]
    feet = {leg: (dx * k * m.stride, dy * k) for leg, (dx, dy) in key["feet"].items()}
    p = kpose(a, hip=key["hip"], sh=key["sh"], feet=feet, rot=key["rot"],
              tail=key["tail"] + 12 * m.carriage)
    tail_wave(a, p, i / n, 6 + 6 * m.energy, lag=0.15)
    p.head_dy = 1 if i % len(RUN_KEYS) in (0, 5) else 0
    _snap_body(p)
    return _snap_feet(a, p)


run.speed = lambda a, m, n: RUN_SPEED * min(1.15, (a.ground - a.hip[1]) / 8.0) * m.stride


def stride_px(a: QuadAnatomy, m: Motion, run_: bool, n: int) -> float:
    """Ground distance per frame matching the stance slide in :func:`gait`."""
    return (run if run_ else walk).speed(a, m, n)


# ---------------------------------------------------------------------------
# one-shots (all end where PISI returns to: sitting)
# ---------------------------------------------------------------------------
def _keys(a, i, n, keys):
    """keys: list of (t, pose) with t in 0..1; eased blend between them."""
    t = i / max(1, n - 1)
    for k in range(len(keys) - 1):
        t0, p0 = keys[k]
        t1, p1 = keys[k + 1]
        if t <= t1 or k == len(keys) - 2:
            u = 0.0 if t1 == t0 else M.clamp((t - t0) / (t1 - t0), 0.0, 1.0)
            return blend(a, p0, p1, M.smooth(u))
    return _cp(keys[-1][1])


def yawn(a, m, i, n):
    s = sit(a)
    up = _cp(s)
    up.head_dy -= 1
    up.ears = "back"
    p = _keys(a, i, n, [(0, s), (0.3, up), (0.75, up), (1.0, s)])
    t = i / max(1, n - 1)
    if 0.2 < t < 0.8:
        p.eyes = "closed"
        p.mouth = "wide" if 0.3 < t < 0.7 else "open"
    elif 0.12 < t <= 0.2 or 0.8 <= t < 0.9:
        p.eyes = "half"
    return p


def meow(a, m, i, n):
    s = sit(a)
    p = _cp(s)
    t = i / max(1, n - 1)
    if 0.15 < t < 0.75:
        p.head_dy -= 1
        p.mouth = "open" if t < 0.3 or t > 0.6 else "wide"
        p.ears = "up"
    tail_wave(a, p, t, 6)
    return p


def talk(a, m, i, n):
    p = sit(a)
    p.mouth = "open" if i % 2 == 0 else "closed"
    if i % 4 == 1:
        p.head_dy -= 1
    return p


def eat(a, m, i, n):
    """Settle down by the bowl, head low, chewing; then sit back up."""
    s = sit(a)
    down = loaf(a)
    down.eyes = "half"
    down.head_dx += 3
    down.head_dy += 3
    t = i / max(1, n - 1)
    if t < 0.2:
        p = blend(a, s, down, M.smooth(t / 0.2))
    elif t > 0.82:
        p = blend(a, down, s, M.smooth((t - 0.82) / 0.18))
    else:
        p = _cp(down)
        p.mouth = "open" if i % 2 else "closed"
        p.head_dy += 0 if i % 2 else 1          # little chewing bob
        tail_wave(a, p, t, 6 * (0.5 + m.tail_sway), base_amp=0.0)
    return p


def pounce(a, m, i, n):
    """Wiggle, spring, stretched leap, fore-first landing, settle to sit."""
    L = a.leap
    st = stand(a)
    low = kpose(a, hip=(0, 3), sh=(1, 3), tail=-35, ears="back")
    wl = kpose(a, low, hip=(-1, 0))
    wr = kpose(a, low, hip=(1, 0))
    spring = kpose(a, hip=(0, 2), sh=(1, round(-2 * L)),
                   feet={"nf": (4, round(-4 * L)), "ff": (3, round(-4 * L))},
                   rot={"nf": -40, "ff": -40}, tail=-30)
    leap = kpose(a, hip=(0, round(-3 * L)), sh=(4, round(-4 * L)),
                 feet={"nf": (14, round(-6 * L)), "ff": (13, round(-7 * L)),
                       "nh": (-9, round(-2 * L)), "fh": (-8, round(-3 * L))},
                 rot={"nf": -40, "ff": -40, "nh": 40, "fh": 40}, tail=-40)
    land = kpose(a, hip=(2, -1), sh=(4, 2),
                 feet={"nf": (6, 0), "ff": (5, 0), "nh": (1, -3), "fh": (2, -3)},
                 rot={"nh": 40, "fh": 40}, tail=-20)
    crouch_ = kpose(a, hip=(2, 2), sh=(3, 2), feet={k: (2.5, 0) for k in LEGS_ALL}, tail=-10)
    s = sit(a)
    p = _keys(a, i, n, [(0, st), (0.1, low), (0.18, wl), (0.26, wr), (0.33, low),
                        (0.42, spring), (0.52, leap), (0.62, land), (0.74, crouch_),
                        (0.86, st), (0.93, halfsit(a)), (1.0, s)])
    t = i / max(1, n - 1)
    if 0.4 <= t <= 0.6:
        p.ears = "back"
    return p


LEGS_ALL = ("nh", "fh", "nf", "ff")


def jump(a, m, i, n):
    """A springy leap up and over something, landing fore-first."""
    L = a.leap
    st = stand(a)
    low = kpose(a, hip=(0, 3), sh=(0, 3), tail=-20)
    up = kpose(a, hip=(0, round(-4 * L)), sh=(2, round(-9 * L)),
               feet={"nf": (3, round(-12 * L)), "ff": (2, round(-12 * L)),
                     "nh": (-1, round(-1 * L)), "fh": (0, round(-1 * L))},
               rot={"nf": 40, "ff": 40}, tail=-30)
    top = kpose(a, hip=(1, round(-9 * L)), sh=(3, round(-10 * L)),
                feet={"nf": (10, round(-12 * L)), "ff": (9, round(-13 * L)),
                      "nh": (-8, round(-9 * L)), "fh": (-7, round(-10 * L))},
                rot={"nf": -40, "ff": -40, "nh": 40, "fh": 40}, tail=-40)
    down = kpose(a, hip=(2, round(-6 * L)), sh=(3, round(-3 * L)),
                 feet={"nf": (4, round(-1 * L)), "ff": (3, round(-2 * L)),
                       "nh": (1, round(-7 * L)), "fh": (2, round(-7 * L))},
                 rot={"nh": 40, "fh": 40}, tail=-25)
    land = kpose(a, hip=(1, 2), sh=(2, 3), feet={"nf": (3, 0), "ff": (2, 0),
                                                  "nh": (1, 0), "fh": (2, 0)}, tail=-25)
    s = sit(a)
    return _keys(a, i, n, [(0, st), (0.14, low), (0.3, up), (0.42, top), (0.54, down),
                           (0.64, land), (0.8, st), (0.9, halfsit(a)), (1.0, s)])


def attack(a, m, i, n):
    """Crouch back, then lunge with a long forward swipe of the near paw."""
    st = stand(a)
    back = kpose(a, hip=(-1, 2), sh=(-2, 2), tail=-30, ears="flat")
    lunge = kpose(a, hip=(1, -1), sh=(4, -2),
                  feet={"nf": (13, -5), "ff": (6, 0), "nh": (-3, 0), "fh": (-2, 0)},
                  rot={"nf": -40}, tail=-30, ears="flat", mouth="open")
    swipe = kpose(a, lunge, feet={"nf": (8, 0), "ff": (6, 0), "nh": (-3, 0), "fh": (-2, 0)},
                  rot={"nf": 0})
    s = sit(a)
    return _keys(a, i, n, [(0, st), (0.18, back), (0.36, lunge), (0.5, swipe),
                           (0.62, lunge), (0.74, swipe), (0.86, st), (0.93, halfsit(a)), (1.0, s)])


def hurt(a, m, i, n):
    st = sit(a)
    rec = _cp(st)
    rec.head_dx -= 1
    rec.head_dy += 1
    rec.eyes = "squint"
    rec.ears = "flat"
    _move(rec, -1, 0)
    p = [rec, rec, st][min(i, 2)] if n <= 3 else _keys(a, i, n, [(0, st), (0.3, rec), (1.0, st)])
    p = _cp(p)
    if i == 1:
        p.flash = True
    return p


def tailswish(a, m, i, n):
    p = sit(a)
    tb = list(p.tail_bends)
    sw = M.wave(i / n) * 30
    tb[-1] += M.deg(sw)
    tb[-2] += M.deg(sw * 0.7)
    tb[-3] += M.deg(sw * 0.3)
    p.tail_bends = tuple(tb)
    return p


def lookaround(a, m, i, n):
    p = sit(a)
    t = i / max(1, n - 1)
    if 0.15 < t < 0.45:
        p.look = -1
        p.head_dx -= 1
        p.ears = "flick"
    elif 0.55 < t < 0.85:
        p.look = 1
        p.head_dy -= 1
    return p


def death(a, m, i, n):
    """'Flop over': settle down and stretch out flat, eyes closed."""
    s = sit(a)
    lo = loaf(a)
    flat = loaf(a)
    flat.top_d = -1.0
    flat.head_dy += 2
    flat.head_dx += 1
    flat.feet["nf"] = (flat.feet["nf"][0] + 4, flat.feet["nf"][1])
    flat.feet["ff"] = (flat.feet["ff"][0] + 3, flat.feet["ff"][1])
    flat.tail_bends = tuple(b * 0.2 for b in flat.tail_bends)
    p = _keys(a, i, n, [(0, s), (0.35, lo), (0.7, flat), (1.0, flat)])
    if i / max(1, n - 1) > 0.3:
        p.eyes = "closed"
    return p


def crouch_loop(a, m, i, n):
    p = crouch(a, 3.0)
    tb = list(p.tail_bends)
    tb[-1] += M.deg(15 * M.wave(i / n))
    p.tail_bends = tuple(tb)
    p.ears = "back" if i % 4 == 0 else "up"
    return p


def stretch(a, m, i, n):
    """Wake-up: play-bow stretch with a yawn, then sit."""
    s = sit(a)
    st = stand(a)
    # play bow: chest to the floor, front legs stretched far ahead, rump up
    chest_room = int((a.ground + 2.0) - (a.shoulder[1] + a.belly))   # to the floor
    bow = kpose(a, hip=(-1, -1), sh=(2, max(1, min(6, chest_room))),
                feet={"nf": (8, 0), "ff": (7, 0)},
                rot={"nf": -40, "ff": -40}, tail=10)
    bow.head_dy = 0
    p = _keys(a, i, n, [(0, s), (0.2, st), (0.45, bow), (0.62, bow), (0.8, st), (0.9, halfsit(a)), (1.0, s)])
    t = i / max(1, n - 1)
    if 0.42 < t < 0.66:
        p.eyes = "closed"
        p.mouth = "wide" if 0.47 < t < 0.62 else "open"
        p.ears = "back"
    return p


def celebrate(a, m, i, n):
    s = sit(a)
    st = stand(a)
    low = crouch(a, 2.0)
    up = stand(a)
    _move(up, 0, -round(4 * a.leap))
    up.feet = {k: (x, y - round(3 * a.leap)) for k, (x, y) in rest_feet(a).items()}
    up.foot_rot = {k: M.deg(20) for k in up.feet}
    up.tail_ang = a.tail_ang + M.deg(15)
    p = _keys(a, i, n, [(0, s), (0.15, st), (0.3, low), (0.45, up), (0.6, low),
                        (0.72, st), (0.86, halfsit(a)), (1.0, s)])
    p.eyes = "squint" if 0.2 < i / max(1, n - 1) < 0.85 else p.eyes
    if 0.35 < i / max(1, n - 1) < 0.55:
        p.mouth = "open"
    return p


def petted(a, m, i, n):
    """Leans into the hand, happy squint, purr vibration, tail curls."""
    p = sit(a)
    t = i / max(1, n - 1)
    if 0.1 < t < 0.9:
        p.eyes = "squint"
        p.ears = "back" if 0.2 < t < 0.7 else "up"
        p.head_dx += 1 if (i % 2 == 0) else 0
        p.head_dy -= 1
    tb = list(p.tail_bends)
    tb[-1] += M.deg(25 * M.wave(t))
    p.tail_bends = tuple(tb)
    return p


def dangle(a, m, i, n):
    """Picked up by the scruff: hangs vertically under the head, front paws
    dangling ahead of the chest, hind legs and tail swinging a beat later."""
    p = stand(a)
    ph = i / n
    sway = M.wave(ph)
    lag = M.wave(ph - 0.18)
    BL = a.shoulder[0] - a.hip[0]
    sh = (a.shoulder[0] - 5.0, 16.0)
    hip = (sh[0] - 1.0 + round(sway * 0.6), sh[1] + BL * 0.9)
    p.shoulder, p.hip = sh, hip
    _snap_body(p)
    sh, hip = p.shoulder, p.hip
    fl = leg_len(a, "nf")
    hl = leg_len(a, "nh")
    p.feet = {
        "nf": (sh[0] + 4.0 + round(lag * 0.6), sh[1] + fl * 0.85),
        "ff": (sh[0] + 5.5 + round(lag * 0.6), sh[1] + fl * 0.75),
        "nh": (hip[0] + 2.0 + round(lag), hip[1] + hl * 0.8),
        "fh": (hip[0] + 3.5 + round(lag), hip[1] + hl * 0.7),
    }
    p.root_d = {"nf": (2.0, 1.0), "ff": (3.0, 0.0), "nh": (1.0, 0.0), "fh": (2.0, -1.0)}
    p.foot_rot = {k: M.deg(60) for k in p.feet}
    p.tail_base = (hip[0] - 1.0, hip[1] + 2.0)
    p.tail_ang = M.deg(100) + M.deg(12 * M.wave(ph - 0.3))
    p.tail_bends = (0.0, M.deg(-6), M.deg(-8), M.deg(-14), M.deg(-26), M.deg(-34))
    p.head_dx, p.head_dy = 0, 1
    p.ears = "back"
    p.neck = False
    p.top_d, p.belly_d, p.back_d = -1.0, -1.0, -1.0   # a hanging cat stretches thin
    p.eyes = "half" if i % n == n - 1 else "open"
    return _snap_feet(a, p)


# climbing ------------------------------------------------------------------------
# A cat on a wall, drawn facing right with the wall just ahead of it (the bake
# mirrors it for the other side): body upright, belly to the wall, front paws
# reaching up in turn, hind feet pushing below, tail hanging down. The ground
# line is the hind feet, like the ground is for standing.
CLIMB_STRIDE = 4.0          # px a paw moves per stance
CLIMB_DUTY = 0.5
WALL_FRAC = 0.46            # the wall's x, as a share of the frame width


def wall_x(a: QuadAnatomy) -> float:
    """Where the wall is in the frame (the paws grip it): a touch left of
    the middle, so the pull-up has room to stand up on the right."""
    return float(round(a.w * WALL_FRAC))


def cling(a: QuadAnatomy, lift: float = 0.0) -> QuadPose:
    """Holding on to the wall: body upright, front legs stretched up the wall
    above the head, hind feet tucked up against it with bent knees, tail
    dangling straight down. It looks back over its shoulder at you (a
    side-on face would hide the front paws on the wall). ``lift`` raises it."""
    p = stand(a)
    BL = a.shoulder[0] - a.hip[0]
    wx = wall_x(a)
    hip = (wx - 6.0, a.ground - 9.0 - lift)
    sh = (wx - 5.0, hip[1] - BL)
    p.hip, p.shoulder = hip, sh
    _snap_body(p)
    hip, sh = p.hip, p.shoulder
    p.feet = {"nf": (wx, sh[1] - 12.0), "ff": (wx + 0.5, sh[1] - 10.0),
              "nh": (wx - 0.5, a.ground - 7.0 - lift), "fh": (wx, a.ground - 8.5 - lift)}
    p.root_d = {"nf": (3.0, -5.0), "ff": (3.5, -5.0), "nh": (1.5, 0.0), "fh": (2.0, 0.0)}
    p.foot_rot = {"nf": M.deg(-85), "ff": M.deg(-85), "nh": M.deg(-75), "fh": M.deg(-75)}
    p.tail_base = (hip[0], hip[1] + 1.0)
    p.tail_ang = M.deg(95)
    p.tail_bends = (0.0, M.deg(3), M.deg(5), M.deg(8), M.deg(12), M.deg(18))
    p.tail_group = 0
    p.head_view = "front"
    p.head_dx, p.head_dy = -2, 2
    p.neck = False
    p.top_d, p.belly_d, p.back_d = -0.5, -1.0, -1.0
    return _snap_feet(a, p)


def climb(a, m, i, n):
    """Paw over paw up the wall: diagonal pairs (near fore with far hind)
    reach while the others pull. Planted paws slide down the frame exactly as
    fast as the pet moves up the screen, so they stay put on the wall."""
    p = cling(a)
    wx = wall_x(a)
    sh = p.shoulder
    offs = {"nf": 0.0, "fh": 0.0, "ff": 0.5, "nh": 0.5}
    top = {"nf": sh[1] - 13.0, "ff": sh[1] - 12.0,
           "nh": a.ground - 7.0 - CLIMB_STRIDE, "fh": a.ground - 8.5 - CLIMB_STRIDE}
    for leg, off in offs.items():
        ph = (i / n + off) % 1.0
        y0 = top[leg]
        x = wx + (0.5 if leg[0] == "f" else 0.0) - (0.5 if leg[1] == "h" else 0.0)
        if ph < CLIMB_DUTY:                    # gripping: slides down as we rise
            y = y0 + CLIMB_STRIDE * (ph / CLIMB_DUTY)
            rot = -85
        else:                                  # reaching up for the next hold
            u = (ph - CLIMB_DUTY) / (1 - CLIMB_DUTY)
            y = y0 + CLIMB_STRIDE * (1 - u)
            x -= 1.5 * M.wave(u * 0.5)         # a little away from the wall
            rot = -60
        p.feet[leg] = (x, y)
        p.foot_rot[leg] = M.deg(rot)
    if (i * 2) % n < n // 2:                   # the body heaves up as each pair pulls
        _move(p, 0, -1)
    tail_wave(a, p, i / n, 10 + 10 * m.tail_sway, base_amp=0.4)
    p.ears = "back" if i % n == 0 else "up"
    return _snap_feet(a, p)


climb.speed = lambda a, m, n: CLIMB_STRIDE / (CLIMB_DUTY * n)


def cling_loop(a, m, i, n):
    """Holding still on the wall, looking around (a breather mid-climb)."""
    p = cling(a)
    tail_wave(a, p, i / n, 16, base_amp=0.5)
    t = i / max(1, n - 1)
    if 0.3 < t < 0.6:
        p.look = -1
        p.ears = "flick"
    elif t >= 0.6:
        p.head_dy -= 1
    return p


def pull_height(a: QuadAnatomy) -> float:
    """How far above the climbing ground line the ledge is when the front
    paws reach it."""
    return a.ground - (cling(a).shoulder[1] - 3.0)


def pull_drop(a: QuadAnatomy) -> float:
    """The pull-up starts this much lower in its frame than the climb (so it
    has room to stand up on the ledge inside the frame); the pet's window
    moves up by as much when it starts."""
    return max(0.0, pull_height(a) - a.ground + 30.0)


def pullup(a, m, i, n):
    """Front paws over the top edge, a scrabble of the hind legs, swing up and
    stand on the ledge, just past the wall."""
    K, d = pull_height(a), pull_drop(a)
    wx = wall_x(a)
    top = a.ground + d - K                      # the ledge, in this frame
    # stands just past the wall (a long body a little less far, to stay in frame)
    dx = min((wx + 1.0) - a.hip[0], a.w - 4.0 - (a.shoulder[0] + a.front + 6.0))
    c = cling(a, lift=-d)
    c.tail_ang = M.deg(200)
    c.feet["nh"] = (c.feet["nh"][0], c.feet["nh"][1] - 3.0)   # knees up, ready to push
    c.feet["fh"] = (c.feet["fh"][0], c.feet["fh"][1] - 3.0)
    reach = cling(a, lift=-d + 2.0)
    reach.feet["nh"] = (reach.feet["nh"][0], reach.feet["nh"][1] - 3.0)
    reach.feet["fh"] = (reach.feet["fh"][0], reach.feet["fh"][1] - 3.0)
    reach.feet["nf"] = (wx + 1.5, top)
    reach.feet["ff"] = (wx + 2.0, top - 0.6)
    reach.foot_rot.update({"nf": 0.0, "ff": 0.0})
    reach.tail_ang = M.deg(195)
    hook = cling(a, lift=-d + 6.0)
    hook.shoulder = (wx + 1.0, top - 2.0)
    hook.hip = (wx - 2.0, top + 7.0)
    hook.feet.update({"nf": (wx + 4.0, top), "ff": (wx + 4.5, top - 0.6),
                      "nh": (wx - 0.5, top + 10.0), "fh": (wx, top + 8.0)})
    hook.foot_rot.update({"nf": 0.0, "ff": 0.0})
    hook.head_view = "34"
    hook.head_dx, hook.head_dy = 0, 0
    hook.tail_base = (hook.hip[0], hook.hip[1] + 1.0)
    hook.tail_ang = M.deg(165)
    done = stand(a)
    _move(done, dx, top - a.ground, feet=True)
    done.tail_ang = a.tail_ang - M.deg(30)     # lifts it once it's settled
    _snap_body(done)
    over = _cp(done)
    over.hip = (over.hip[0] - 1.0, over.hip[1] + 4.0)
    over.feet["nh"] = (wx + 0.5, top)
    over.feet["fh"] = (wx + 1.0, top - 0.6)
    over.tail_ang = done.tail_ang + M.deg(-40)
    _snap_body(over)
    p = _keys(a, i, n, [(0, c), (0.22, reach), (0.48, hook), (0.74, over), (1.0, done)])
    t = i / max(1, n - 1)
    if 0.3 < t < 0.7:
        p.ears = "back"
    return _snap_feet(a, p)


# the sprite reads these from the baked sheet: how much lower the pull-up
# starts than the climb (its "speed" slot carries it)
pullup.speed = lambda a, m, n: pull_drop(a)


# transitions -----------------------------------------------------------------
def sitdown(a, m, i, n):
    return _keys(a, i + 1, n + 1, [(0, stand(a)), (0.55, halfsit(a)), (1.0, sit(a))])


def standup(a, m, i, n):
    return _keys(a, i + 1, n + 1, [(0, sit(a)), (0.45, halfsit(a)), (1.0, stand(a))])


def liedown(a, m, i, n):
    p = blend(a, sit(a), loaf(a), M.smooth((i + 1) / n))
    if i < n - 1:
        p.eyes = "half"
    return p


def getup(a, m, i, n):
    p = blend(a, loaf(a), sit(a), M.smooth((i + 1) / n))
    p.eyes = "half" if i == 0 else "open"
    return p


def curldown(a, m, i, n, lift: int = 0):
    """Sit -> lie down -> curl up (getting into bed)."""
    seq = [lambda: blend(a, sit(a), loaf(a), 0.5), lambda: _eyes(loaf(a), "half"),
           lambda: curl(a, 0.3, lift), lambda: curl(a, 0.65, lift), lambda: curl(a, 0.9, lift),
           lambda: curl(a, 1.0, lift)]
    return seq[min(i, len(seq) - 1)]()


def curlup(a, m, i, n, lift: int = 0):
    """Waking in bed: uncurl, lift the head, sit up."""
    seq = [lambda: _eyes(curl(a, 0.9, lift), "half"), lambda: _eyes(curl(a, 0.6, lift), "open"),
           lambda: _eyes(curl(a, 0.3, lift), "open"), lambda: _eyes(loaf(a), "open"),
           lambda: _eyes(blend(a, loaf(a), sit(a), 0.5), "open")]
    return seq[min(i, len(seq) - 1)]()


def rim_loop(a, m, i, n):
    """Curled up in a rimmed bed, chin on the rim."""
    return curl_loop(a, m, i, n, lift=RIM)


def rimdown(a, m, i, n):
    return curldown(a, m, i, n, lift=RIM)


def rimup(a, m, i, n):
    return curlup(a, m, i, n, lift=RIM)


# playing with things -------------------------------------------------------------
# Toys, beds and posts are drawn by the app at the rig's anchors (mouth,
# paws); these poses put the mouth and paws where the thing will be, worked
# out from each cat's own neck, legs and body.
def _mouth_at(a: QuadAnatomy, p: QuadPose, x: float, y: float) -> QuadPose:
    """Move the head so the mouth anchor lands on (x, y) (whole pixels)."""
    from .quadruped import anchors
    mx, my = anchors(a, p)["mouth"]
    p.head_dx += int(round(x - mx))
    p.head_dy += int(round(y - my))
    return p


TOY_GRIP = 4      # a toy on the floor is gripped this many rows above the floor row


def reach_down(a: QuadAnatomy, mouth_open: bool = False) -> QuadPose:
    """Head down to the floor just ahead of the front paws, front legs bent,
    hind legs planted: to sniff, pick up or put down a toy."""
    p = stand(a)
    p.shoulder = (p.shoulder[0], p.shoulder[1] + 2.0)
    p.hip = (p.hip[0], p.hip[1] - 1.0)
    p.tail_ang = a.tail_ang + M.deg(15)
    _snap_body(p)
    _mouth_at(a, p, a.shoulder[0] + a.front + 4.0, a.ground + 3.0 - TOY_GRIP)
    p.neck = True
    p.mouth = "open" if mouth_open else "closed"
    p.ears = "up"
    return _snap_feet(a, p)


def toy_spot(a: QuadAnatomy) -> tuple[int, int]:
    """Where a toy on the floor should lie to be picked up (its top middle),
    in frame pixels facing right."""
    from .quadruped import anchors
    return anchors(a, reach_down(a))["mouth"]


def carry_pose(a: QuadAnatomy, p: QuadPose) -> QuadPose:
    """Something held in the mouth: head a little up and proud."""
    p.head_dy -= 1
    p.mouth = "closed"
    return p


def carrywalk(a, m, i, n):
    return carry_pose(a, walk(a, m, i, n))


carrywalk.speed = walk.speed


def carrytrot(a, m, i, n):
    return carry_pose(a, trot(a, m, i, n))


carrytrot.speed = trot.speed


def carrysit(a, m, i, n):
    p = carry_pose(a, sit_loop(a, m, i, n))
    p.eyes = "open" if p.eyes == "closed" else p.eyes   # watching you
    return p


def pickup(a, m, i, n):
    """Stand, lower the head, open, grab, lift it up proudly."""
    st = stand(a)
    low = reach_down(a, mouth_open=True)
    grab = reach_down(a)
    up = carry_pose(a, stand(a))
    p = _keys(a, i, n, [(0, st), (0.35, low), (0.55, low), (0.65, grab), (1.0, up)])
    t = i / max(1, n - 1)
    p.mouth = "open" if 0.3 <= t < 0.6 else "closed"
    if t >= 0.85:
        p.head_dy = up.head_dy
    return p


def drop(a, m, i, n):
    """Lower the head, let go, look at it, sit down."""
    up = carry_pose(a, stand(a))
    low = reach_down(a)
    let = reach_down(a, mouth_open=True)
    p = _keys(a, i, n, [(0, up), (0.3, low), (0.45, let), (0.65, stand(a)),
                        (0.82, halfsit(a)), (1.0, sit(a))])
    t = i / max(1, n - 1)
    p.mouth = "open" if 0.4 <= t < 0.55 else "closed"
    return p


def _bat_low(a: QuadAnatomy) -> QuadPose:
    low = kpose(a, hip=(0, 1), sh=(0, 3), tail=-10, ears="up")
    low.tail_bends = tuple(b * 0.5 for b in (low.tail_bends or a.tail_bends))
    return low


def bat_reach(a: QuadAnatomy) -> float:
    """How far ahead of its rest spot the near front paw lands on the floor
    at the end of a swipe: as far as that leg really reaches from the
    crouch (most of its length), so every cat touches the toy."""
    from .quadruped import leg_root
    low = _bat_low(a)
    root = leg_root(a, low, "nf")
    fl = leg_len(a, "nf") * 0.92
    h = a.ground - root[1]
    flat = max(0.0, fl * fl - h * h) ** 0.5
    rest_x = rest_feet(a)["nf"][0]
    return float(round(root[0] + flat - rest_x))


def bat_target(a: QuadAnatomy) -> tuple[int, int]:
    """The paw pixel at full reach (a toy just ahead of it gets batted)."""
    from .quadruped import anchors
    return anchors(a, _bat_tap(a))["paws"]["nf"]


def _bat_tap(a: QuadAnatomy) -> QuadPose:
    out = kpose(a, _bat_low(a), feet={"nf": (bat_reach(a), 0)}, rot={"nf": -40}, sh=(1, 0))
    return kpose(a, out, feet={"nf": (bat_reach(a), 0)}, rot={"nf": 0})


def bat(a, m, i, n):
    """Playing: crouched low, a quick swipe of the near front paw along the
    floor at something just ahead, then back."""
    reach = bat_reach(a)
    low = _bat_low(a)
    lift = kpose(a, low, feet={"nf": (3, -3)}, rot={"nf": -40})
    out = kpose(a, low, feet={"nf": (reach, -1)}, rot={"nf": -40}, sh=(1, 0))
    tap = _bat_tap(a)
    back = kpose(a, low, feet={"nf": (2, -2)}, rot={"nf": 30})
    p = _keys(a, i, n, [(0, low), (0.25, lift), (0.45, out), (0.6, tap),
                        (0.8, back), (1.0, low)])
    tail_wave(a, p, i / n, 12 + 10 * m.energy, base_amp=0.2)
    p.ears = "up"
    return _snap_feet(a, p)


SCRATCH_ANG = -62.0          # spine angle (deg), stretched up on the hind legs
SCAPULA = 4.0                # the shoulder blade slides up this far when reaching


def _scratch_body(a: QuadAnatomy):
    BL = a.shoulder[0] - a.hip[0]
    hip = (a.hip[0] + 2.0, a.hip[1] + 1.0)
    ang = M.deg(SCRATCH_ANG)
    sh = (hip[0] + M.cos(ang) * BL, hip[1] + M.sin(ang) * BL)
    return (float(round(hip[0])), float(round(hip[1]))), (float(round(sh[0])), float(round(sh[1])))


def scratch_geometry(a: QuadAnatomy) -> dict:
    """Where a scratching post stands (its near face, x) and the band the
    front paws scratch over (y, top to bottom of the stroke), facing right:
    from where the raised foreleg starts and how far that leg reaches, so a
    long-legged cat stretches higher."""
    _hip, sh = _scratch_body(a)
    fl = leg_len(a, "nf")
    root = (sh[0] + a.legs["nf"].root[0] + 1.0, sh[1] - SCAPULA)
    dx = max(2.0, round(fl * 0.35))
    r = fl * 0.93
    top = float(round(root[1] - (r * r - dx * dx) ** 0.5))
    return {"post_x": float(round(root[0] + dx + 1.0)), "top": top,
            "bottom": top + max(4.0, float(round(fl * 0.5)))}


def scratch_pose(a: QuadAnatomy, s: float, near_first: bool = True) -> QuadPose:
    """Stretched up tall against a post just ahead: on the hind legs, head
    up, forelegs reaching up the post in front of the face (the shoulder
    blades slide up, as a real cat's do). ``s`` 0 = paws at the top of the
    stroke, 1 = dragged down to the bottom."""
    p = stand(a)
    hip, sh = _scratch_body(a)
    p.hip, p.shoulder = hip, sh
    g = scratch_geometry(a)
    px = g["post_x"]
    p.back_d = -1.0
    thigh = a.legs["nh"].r_top
    p.haunch = (hip[0] - 0.5, hip[1] + 0.5, thigh + 0.4, thigh + 0.6)
    for leg in ("nf", "ff"):
        first = (leg == "nf") == near_first
        u = s if first else M.clamp(s - 0.4, 0.0, 1.0) * (1 / 0.6)
        y = g["top"] + (g["bottom"] - g["top"]) * u
        p.feet[leg] = (px - 1.0 if leg == "nf" else px - 0.5, y - (0.0 if leg == "nf" else 1.0))
        p.foot_rot[leg] = M.deg(-85)
    p.root_d = {"nf": (1.0, -SCAPULA), "ff": (2.5, -SCAPULA - 1.0)}
    p.feet["nh"] = (hip[0] - 1.0, a.ground)
    p.feet["fh"] = (hip[0] + 1.5, a.ground - 0.6)
    p.tail_base = (hip[0] - 2.0, hip[1] + 1.0)
    p.tail_ang = M.deg(160)
    p.tail_bends = (0.0, M.deg(-4), M.deg(-8), M.deg(-12), M.deg(-18), M.deg(-24))
    p.tail_group = 0
    # head up at full height, just behind the reaching forelegs
    ox = int(round(px - a.head.width - 2.0))
    p.head_dx = ox - (int(round(sh[0])) + a.head_rel[0])
    p.head_dy = -1
    p.ears = "up"
    p.fore_over_head = True
    return _snap_feet(a, p)


def scratch(a, m, i, n):
    """Claws in, dragging down the post, paws in turn."""
    t = i / n
    k = max(1, n // 2 - 1)
    p = scratch_pose(a, (i % (n // 2)) / k, near_first=t < 0.5)
    p.eyes = "half" if i % n in (n // 2 - 1, n // 2) else "open"
    tail_wave(a, p, t, 6 + 6 * m.tail_sway, base_amp=0.0)
    return p


def knead(a, m, i, n):
    """Making biscuits before curling up in bed: hindquarters half down,
    front paws pressing into the bed in turn, eyes squeezed happy, tail up."""
    p = halfsit(a)
    ph = (i / n) % 1.0
    for leg, off in (("nf", 0.0), ("ff", 0.5)):
        u = M.wave(ph + off)
        x, y = rest_feet(a)[leg]
        if u > 0.0:
            p.feet[leg] = (x + 1.0, y - round(3.0 * u))
            p.foot_rot[leg] = M.deg(35)
        else:
            p.feet[leg] = (x, y)
    p.head_dy += 1
    p.eyes = "squint"
    p.ears = "back" if i % 4 == 2 else "up"
    p.tail_ang = a.tail_ang + M.deg(10)
    tb = list(p.tail_bends or a.tail_bends)
    tb[-1] += M.deg(12 * M.wave(ph))
    p.tail_bends = tuple(tb)
    return _snap_feet(a, p)


def stalk(a, m, i, n):
    """Low to the ground, eyes on the prey, the hind end wiggling side to
    side and the tail tip twitching: the moment before a pounce."""
    low = kpose(a, hip=(0, 3), sh=(1, 3), tail=-35, ears="up")
    wl = kpose(a, low, hip=(-1, 0))
    wr = kpose(a, low, hip=(1, 0))
    seq = (low, wl, low, wr)
    p = _cp(seq[i % len(seq)])
    tb = list(p.tail_bends or a.tail_bends)
    tb[-1] += M.deg(25 * (1 if i % 2 else -1))
    p.tail_bends = tuple(tb)
    return _snap_feet(a, p)


def watch(a, m, i, n):
    """Sitting bolt upright, ears up, eyes on something: the tail tip
    flicks fast."""
    p = sit(a)
    p.head_dy -= 1
    p.ears = "up"
    tb = list(p.tail_bends)
    tb[-1] += M.deg(28 * M.wave(i / n * 2))
    tb[-2] += M.deg(10 * M.wave(i / n * 2 - 0.1))
    p.tail_bends = tuple(tb)
    if i == n - 1 and m.blink > 0.5:
        p.eyes = "half"
    return p


def watchup(a, m, i, n):
    """Watching something up above (a dot on the wall, a feather): head
    up and back, ears up, tail going."""
    p = watch(a, m, i, n)
    p.head_dy -= 1
    p.head_dx -= 1
    p.look = 1
    return p


def trudge(a, m, i, n):
    """Worn out, walking: the same footfalls as a walk, but the head hangs
    low and the tail droops behind."""
    p = walk(a, m, i, n)
    p.head_dy += 1
    p.tail_ang = min(p.tail_ang, M.deg(-196))     # hanging just below level, behind
    p.tail_bends = tuple(b * 0.35 for b in (p.tail_bends or a.tail_bends))
    return p


trudge.speed = walk.speed


def _spent(a: QuadAnatomy) -> QuadPose:
    """Flopped out flat on the floor, tail limp, eyes half shut."""
    p = loaf(a)
    p.top_d = -1.0
    p.head_dy += 2
    p.head_dx += 1
    p.feet["nf"] = (p.feet["nf"][0] + 4, p.feet["nf"][1])
    p.feet["ff"] = (p.feet["ff"][0] + 3, p.feet["ff"][1])
    p.tail_bends = tuple(b * 0.2 for b in p.tail_bends)
    p.eyes = "half"
    return p


def flop(a, m, i, n):
    """All played out: down from sitting to flat on the floor in one go."""
    p = _keys(a, i, n, [(0, sit(a)), (0.4, loaf(a)), (1.0, _spent(a))])
    t = i / max(1, n - 1)
    p.eyes = "half" if t > 0.3 else "open"
    if t > 0.6:
        p.mouth = "open"
    return p


def pant(a, m, i, n):
    """Lying flat, panting: mouth open on every breath out, the side heaving,
    the tail tip barely twitching."""
    p = _spent(a)
    out = i % 2 == 0
    p.mouth = "open" if out else "closed"
    p.top_d = -1.0 if out else 0.0
    tb = list(p.tail_bends)
    if tb and i % n == n // 2:
        tb[-1] += M.deg(10)
    p.tail_bends = tuple(tb)
    if m.blink > 0.4 and i % n == n - 1:
        p.eyes = "closed"
    return p


def pantup(a, m, i, n):
    """Getting back up after a breather."""
    return _keys(a, i, n, [(0, _spent(a)), (0.45, loaf(a)), (0.75, halfsit(a)), (1.0, sit(a))])


def _eyes(p: QuadPose, eyes: str) -> QuadPose:
    p.eyes = eyes
    return p


def turn(a, m, i, n):
    """A full turn-around ending facing right (the bake mirrors it for the
    other direction). First half: still facing the old way, the body
    foreshortens towards the viewer; middle: front view; second half: the
    body unfolds on the new side. Feet step around the centre."""
    u = ((i + 0.5) / n) * 2.0 - 1.0          # -1 .. 1 across the turn
    flip = u < 0
    s = abs(u)
    st = stand(a)
    p = _cp(st)
    p.flip = flip
    k = 0.18 + 0.82 * M.smooth(s)            # torso foreshortening
    p.torso_scale = k
    BL = a.shoulder[0] - a.hip[0]
    c = (a.hip[0] + a.shoulder[0]) / 2
    rest = rest_feet(a)
    # feet gather under the body, and the stepping pair is lifted a beat
    p.feet = {leg: (c + (x - c) * k, y) for leg, (x, y) in rest.items()}
    if 0.2 < s < 0.75:
        lift = "nf" if i % 2 else "nh"
        x, y = p.feet[lift]
        p.feet[lift] = (x, y - 1.0)
        p.foot_rot[lift] = M.deg(40)
    if s < 0.3:
        p.head_view = "front"
        p.head_dx = -int(round(BL * (1 - k) * 0.5)) - 1
    else:
        p.head_dx = -int(round(BL * (1 - k) * 0.5))
    p.tail_ang = a.tail_ang + M.deg(30 * (1 - s))
    p.tail_bends = tuple(b * (0.5 + 0.5 * s) for b in a.tail_bends)
    _snap_body(p)
    return _snap_feet(a, p)


# reacting to web pages --------------------------------------------------------
def dig(a, m, i, n):
    """Burrowing into the text: front end down, rump up, head low, the front
    paws raking back under the chest in turn, tail up and twitching."""
    p = kpose(a, hip=(-1, -2), sh=(1, 4), tail=35, ears="back")
    ph = i / n
    for leg, off in (("nf", 0.0), ("ff", 0.5)):
        u = (ph + off) % 1.0
        x0, y0 = rest_feet(a)[leg]
        if u < 0.4:                      # reaching forward, paw lifted
            k = u / 0.4
            x, y, r = -4 + 10 * k, -3.0 * M.sin(M.PI * k), -50
        else:                            # claws in, raking it back
            k = (u - 0.4) / 0.6
            x, y, r = 6 - 10 * k, 0.0, 30
        p.feet[leg] = (x0 + x, y0 + y)
        p.foot_rot[leg] = M.deg(r)
    p.head_dx += 2
    p.head_dy += 4
    p.eyes = "half" if i % 4 == 1 else "open"
    tb = list(p.tail_bends or a.tail_bends)
    tb[-1] += M.deg(30 * M.wave(ph * 2))
    p.tail_bends = tuple(tb)
    return _snap_feet(a, p)


def _paw_on_face(a: QuadAnatomy, base: QuadPose, peek: float = 0.0) -> QuadPose:
    """``base`` with the near front paw raised over the eyes (``peek`` lowers
    it a little, so one eye shows)."""
    p = _cp(base)
    p.head_dy += 1
    p.head_dx -= 1
    hx = int(round(p.shoulder[0])) + a.head_rel[0] + p.head_dx
    hy = int(round(p.shoulder[1])) + a.head_rel[1] + p.head_dy
    hw = a.head.width
    p.feet["nf"] = (hx + hw * 0.85, hy + hw * (0.35 + 0.25 * peek))
    p.foot_rot["nf"] = M.deg(-80)
    p.root_d = {"nf": (0.5, -SCAPULA * 0.5)}
    p.fore_over_head = True
    p.ears = "back"
    p.eyes = "half" if peek > 0.5 else "closed"
    return _snap_feet(a, p)


def covereyes(a, m, i, n):
    """Don't look! Sitting, a paw over the eyes; a peek, and back again."""
    s = sit(a)
    cover = _paw_on_face(a, s)
    peek = _paw_on_face(a, s, 1.0)
    return _keys(a, i, n, [(0, s), (0.2, cover), (0.55, cover), (0.68, peek),
                           (0.8, cover), (1.0, cover)])


def startle(a, m, i, n):
    """Spooked: a stiff-legged hop straight up with the back arched and the
    tail bolt upright, ears flat, mouth open; then down, still on alert."""
    st = stand(a)
    arch = kpose(a, hip=(1, -1), sh=(-1, -1), tail=12, ears="flat", mouth="open",
                 top_d=1.5)
    h = round(3 * a.leap)
    up = _move(_cp(arch), 0, -h, feet=True)
    up.foot_rot = {k: M.deg(10) for k in up.feet}
    alert = kpose(a, tail=8, ears="up")
    p = _keys(a, i, n, [(0, st), (0.12, arch), (0.3, up), (0.48, arch),
                        (0.75, arch), (1.0, alert)])
    tb = list(p.tail_bends or a.tail_bends)
    p.tail_bends = tuple(b * 0.3 for b in tb) if i / max(1, n - 1) < 0.8 else tuple(tb)
    return _snap_feet(a, p)


def bob(a, m, i, n):
    """Listening to music: sitting, the head nodding on the beat, an ear
    flicking, the tail tip keeping time."""
    p = sit(a)
    beat = i % 4
    p.head_dy += 1 if beat in (1, 2) else 0
    p.head_dx += 1 if beat == 1 else 0
    p.eyes = "squint" if beat in (1, 2) else "open"
    p.ears = "back" if i % 8 == 5 else "up"
    tb = list(p.tail_bends)
    tb[-1] += M.deg(22 * M.wave(i / n * 2))
    p.tail_bends = tuple(tb)
    return p


def sniff(a, m, i, n):
    """Something new: neck stretched out, nose low and forward, little
    twitches of the nose; then the head comes back up."""
    st = stand(a)
    low = kpose(a, sh=(1, 1), ears="up")
    low.head_dx += 3
    low.head_dy += 3
    p = _keys(a, i, n, [(0, st), (0.2, low), (0.8, low), (1.0, st)])
    t = i / max(1, n - 1)
    if 0.2 <= t <= 0.8:
        p.head_dx += i % 2
        p.head_dy -= 1 if i % 3 == 0 else 0
        p.eyes = "half" if i % 3 == 1 else "open"
    return _snap_feet(a, p)


def stare(a, m, i, n):
    """Sitting side-on, head turned to look straight at you, tail tip
    flicking; a slow blink at the end. The look before it knocks something
    off the edge."""
    p = sit(a)
    p.head_view = "front"
    p.head_dx -= 1
    p.ears = "up"
    tb = list(p.tail_bends)
    tb[-1] += M.deg(18 * M.wave(i / n))
    p.tail_bends = tuple(tb)
    if i >= n - 2:
        p.eyes = "half"
    return p


# registry -----------------------------------------------------------------
STATES: dict[str, tuple[AnimSpec, object]] = {
    "idle": (AnimSpec("idle", 12, 7, True), idle),
    "sit": (AnimSpec("sit", 8, 5, True), sit_loop),
    "sleep": (AnimSpec("sleep", 6, 2.5, True), sleep_loop),
    "walk": (AnimSpec("walk", 8, 10, True), walk),
    "run": (AnimSpec("run", 6, 12, True), run),
    "yawn": (AnimSpec("yawn", 10, 8, False), yawn),
    "meow": (AnimSpec("meow", 7, 11, False), meow),
    "talk": (AnimSpec("talk", 4, 7, True), talk),
    "eat": (AnimSpec("eat", 10, 7, False), eat),
    "pounce": (AnimSpec("pounce", 14, 12, False), pounce),
    "jump": (AnimSpec("jump", 15, 13, False), jump),
    "attack": (AnimSpec("attack", 12, 12, False), attack),
    "hurt": (AnimSpec("hurt", 3, 8, False), hurt),
    "tailswish": (AnimSpec("tailswish", 8, 8, False), tailswish),
    "lookaround": (AnimSpec("lookaround", 10, 6, False), lookaround),
    "death": (AnimSpec("death", 8, 8, False, hold_last=True), death),
    "crouch": (AnimSpec("crouch", 4, 6, True), crouch_loop),
    "stretch": (AnimSpec("stretch", 14, 9, False), stretch),
    "celebrate": (AnimSpec("celebrate", 12, 11, False), celebrate),
    "petted": (AnimSpec("petted", 10, 8, False), petted),
    "dangle": (AnimSpec("dangle", 8, 8, True), dangle),
    "sitdown": (AnimSpec("sitdown", 4, 12, False), sitdown),
    "standup": (AnimSpec("standup", 4, 12, False), standup),
    "liedown": (AnimSpec("liedown", 5, 9, False), liedown),
    "getup": (AnimSpec("getup", 4, 9, False), getup),
    "turn": (AnimSpec("turn", 8, 16, False), turn),
    "climb": (AnimSpec("climb", 8, 10, True), climb),
    "crawl": (AnimSpec("crawl", 8, 8, True), crawl),
    "cling": (AnimSpec("cling", 10, 5, True), cling_loop),
    "pullup": (AnimSpec("pullup", 10, 11, False), pullup),
    "curl": (AnimSpec("curl", 8, 2.5, True), curl_loop),
    "curldown": (AnimSpec("curldown", 6, 7, False), curldown),
    "curlup": (AnimSpec("curlup", 5, 7, False), curlup),
    "curlrim": (AnimSpec("curlrim", 8, 2.5, True), rim_loop),
    "rimdown": (AnimSpec("rimdown", 6, 7, False), rimdown),
    "rimup": (AnimSpec("rimup", 5, 7, False), rimup),
    "carrywalk": (AnimSpec("carrywalk", 8, 10, True), carrywalk),
    "carrytrot": (AnimSpec("carrytrot", 8, 10, True), carrytrot),
    "carrysit": (AnimSpec("carrysit", 8, 5, True), carrysit),
    "pickup": (AnimSpec("pickup", 9, 10, False), pickup),
    "drop": (AnimSpec("drop", 10, 10, False), drop),
    "bat": (AnimSpec("bat", 10, 12, True), bat),
    "scratch": (AnimSpec("scratch", 8, 9, True), scratch),
    "knead": (AnimSpec("knead", 8, 6, True), knead),
    "stalk": (AnimSpec("stalk", 4, 7, True), stalk),
    "watch": (AnimSpec("watch", 8, 9, True), watch),
    "watchup": (AnimSpec("watchup", 8, 9, True), watchup),
    "trudge": (AnimSpec("trudge", 8, 8, True), trudge),
    "flop": (AnimSpec("flop", 6, 9, False), flop),
    "pant": (AnimSpec("pant", 8, 7, True), pant),
    "pantup": (AnimSpec("pantup", 5, 9, False), pantup),
    "dig": (AnimSpec("dig", 8, 12, True), dig),
    "covereyes": (AnimSpec("covereyes", 14, 8, False, hold_last=True), covereyes),
    "startle": (AnimSpec("startle", 10, 12, False), startle),
    "bob": (AnimSpec("bob", 8, 8, True), bob),
    "sniff": (AnimSpec("sniff", 12, 9, False), sniff),
    "stare": (AnimSpec("stare", 8, 6, True), stare),
}


_ = replace
