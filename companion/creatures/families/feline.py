"""Feline family: house cats in PISI's pixel style.

The default genes make PISI's tuxedo cat; every gene value stays inside
the same pixel language: 1px outline ring, flat fill, far legs in shade,
2px near legs, ¾ head with 2px eyes.
"""
from __future__ import annotations

from ..genome import Gene
from ..heads import HeadSpec
from ..quadruped import QuadAnatomy, make_leg
from ..shapes import EarSpec
from .. import dmath as M
from .base import QuadFamily

G = Gene

SCHEMA = [
    # body
    G("body", "length", "float", 10.0, 8.0, 13.0, label="Body length",
      doc="Spine length hip→shoulder (px)"),
    G("body", "depth", "float", 9.0, 7.0, 11.0, label="Body depth"),
    G("body", "legs", "float", 8.0, 6.0, 10.0, label="Leg length"),
    G("body", "thigh", "float", 3.0, 2.4, 3.6, label="Haunch"),
    G("body", "chest", "float", 3.0, 1.5, 4.0, label="Chest slope"),
    G("body", "belly", "float", 0.0, 0.0, 1.5, spread=0.6, label="Belly"),
    G("body", "paw", "int", 3, 2, 4, spread=0.4, label="Paw size"),
    # head
    G("head", "width", "int", 10, 8, 12, spread=0.6, label="Head width"),
    G("head", "face", "int", 5, 4, 6, spread=0.5, label="Face height"),
    G("head", "jaw", "int", 2, 1, 3, spread=0.5, label="Jaw taper"),
    G("head", "neck", "int", 9, 8, 10, spread=0.5, label="Neck height"),
    G("head", "cheeks", "bool", False, weights=(0.25,), label="Cheek fluff"),
    G("head", "eye_gap", "int", 4, 3, 5, spread=0.3, label="Eye spacing"),
    G("head", "big_eyes", "bool", False, weights=(0.2,), label="Big eyes"),
    # ears
    G("ears", "height", "int", 4, 3, 6, spread=0.6, label="Ear height"),
    G("ears", "width", "int", 3, 3, 5, spread=0.5, label="Ear width"),
    G("ears", "fold", "bool", False, weights=(0.08,), label="Folded ears"),
    # tail
    G("tail", "length", "float", 1.0, 0.45, 1.3, label="Tail length"),
    G("tail", "fluff", "float", 1.0, 0.8, 1.6, spread=0.6, label="Tail fluff"),
    G("tail", "carry", "float", 0.0, -1.0, 1.0, label="Tail carriage"),
    G("tail", "hook", "float", 1.0, 0.0, 1.6, label="Tail hook"),
    # coat
    G("coat", "color", "choice", "black",
      choices=("black", "charcoal", "grey", "silver", "lilac", "chocolate",
               "cinnamon", "brown", "ginger", "apricot", "cream", "white"),
      weights=(3, 1, 2, 1, 0.7, 1, 0.7, 1.5, 2.5, 1, 1.2, 1.5), label="Coat colour"),
    G("coat", "pattern", "choice", "solid",
      choices=("solid", "tabby", "spotted", "tuxedo", "bicolor", "van",
               "calico", "tortie", "point"),
      weights=(2.5, 3, 0.8, 1.8, 1.5, 0.8, 1.2, 1, 1), label="Pattern"),
    G("coat", "second", "choice", "",
      choices=("", "black", "charcoal", "grey", "chocolate", "red", "ginger", "sable"),
      weights=(6, 1, 1, 1, 1, 1, 1, 1), label="Marking colour"),
    G("coat", "white", "float", 0.5, 0.0, 1.0, label="White amount"),
    G("coat", "stripes", "float", 4.0, 3.0, 6.0, spread=0.6, label="Stripe spacing"),
    G("coat", "patches", "float", 5.0, 3.0, 8.0, label="Patch size"),
    G("coat", "socks", "bool", True, weights=(0.7,), label="White socks"),
    G("coat", "blaze", "bool", False, weights=(0.25,), label="Face blaze"),
    G("coat", "seed", "seed", 0, 0, 999999, label="Marking seed"),
    # eyes
    G("eyes", "left", "choice", "amber",
      choices=("amber", "gold", "green", "hazel", "copper", "blue"),
      weights=(3, 1.5, 2, 1, 1, 1), label="Left eye"),
    G("eyes", "odd", "bool", False, weights=(0.07,), label="Odd eyes"),
    G("eyes", "right", "choice", "blue",
      choices=("amber", "gold", "green", "hazel", "copper", "blue"),
      label="Right eye (odd)"),
    G("eyes", "nose", "choice", "plum",
      choices=("plum", "pink", "brick", "dusky", "black"),
      weights=(2, 2, 1, 1, 0.5), label="Nose"),
    # motion
    G("motion", "energy", "float", 0.5, 0.0, 1.0, label="Energy"),
    G("motion", "tail_sway", "float", 0.5, 0.0, 1.0, label="Tail sway"),
    G("motion", "stride", "float", 1.0, 0.8, 1.25, spread=0.6, label="Stride"),
    G("motion", "blink", "float", 0.5, 0.0, 1.0, label="Blinking"),
    G("motion", "curious", "float", 0.5, 0.0, 1.0, label="Curiosity"),
]

# PISI's own cat: a chunky tuxedo with white socks, cheeks and green eyes
CANON = {"coat": {"color": "black", "pattern": "tuxedo", "socks": True, "blaze": False},
         "body": {"length": 10.5, "depth": 10.5, "legs": 7.0, "belly": 1.0, "thigh": 3.4},
         "head": {"width": 11, "cheeks": True},
         "ears": {"height": 4, "width": 4},
         "tail": {"length": 0.9, "fluff": 1.1},
         "eyes": {"left": "green", "odd": False, "nose": "pink"}}


def anatomy(genes: dict) -> QuadAnatomy:
    b, h, e, t = genes["body"], genes["head"], genes["ears"], genes["tail"]
    BL = float(b["length"])
    depth = float(b["depth"])
    LL = float(b["legs"])
    top = round(depth * 5.0 / 9.0 * 2) / 2
    belly = depth - top
    ground = 44.0
    hip_y = ground - LL
    # keep the silhouette centred in the 48px frame as the body grows
    hip_x = 19.0 - round((BL - 10.0) / 2.0)
    hip = (hip_x, hip_y)
    sh = (hip_x + round(BL), hip_y)
    thigh = float(b["thigh"])
    paw = int(b["paw"])
    G0 = ground
    legs = {
        "nh": make_leg((-0.5, 0.0), -2.0, G0 - hip_y, -1, thigh, seam_side=1,
                       slack=0.13, split=0.516, paw=paw),
        "fh": make_leg((0.5, 1.0), 0.5, G0 - 0.6 - hip_y - 1.0, 1, 0.6, r=0.5,
                       near=False, slack=0.02, paw=2),
        "nf": make_leg((-0.5, 0.0), 0.0, G0 - hip_y, -1, 2.0, seam_side=-1,
                       slack=0.05, paw=paw),
        "ff": make_leg((-2.5, 1.0), -2.5, G0 - 0.6 - hip_y - 1.0, 1, 0.6, r=0.5,
                       near=False, slack=0.02, paw=1),
    }
    tl = float(t["length"])
    fluff = float(t["fluff"])
    hook = float(t["hook"])
    carry = float(t["carry"])
    nseg = 6
    seg = 2.2 * tl
    bends = (0.0, 0.0, 0.0, 0.0, M.deg(31 * hook), 0.0)
    radii = tuple(r * fluff for r in (1.8, 1.5, 1.3, 1.1, 1.0, 1.0, 1.0))
    if fluff > 1.25:   # fluffy tails stay fat to the tip
        radii = tuple(max(r, 1.0 * fluff * 0.9) for r in radii)
    ear = EarSpec(int(e["height"]), int(e["width"]), 1 if e["fold"] else 0)
    hw = int(h["width"])
    gap = int(h["eye_gap"])
    eye_x = max(2, round(hw * 0.4))
    if eye_x + gap > hw - 2:
        gap = hw - 2 - eye_x
    head = HeadSpec(width=hw, skull=2, face=int(h["face"]), jaw=int(h["jaw"]),
                    eye_gap=gap, eye_x=eye_x, eye_h=3 if h["big_eyes"] else 2,
                    ear=ear, ear_far_x=max(1, round(hw * 0.2)),
                    ear_near_x=hw - 2, cheek_fluff=1 if h["cheeks"] else 0)
    return QuadAnatomy(
        w=48, h=48, ground=ground, hip=hip, shoulder=sh, back=3.0, top=top,
        belly=belly, front=5.0, chest=float(b["chest"]), sag=float(b["belly"]),
        legs=legs, tail_base=(-3.5, -top), tail_ang=M.deg(-120.5 + 30 * carry),
        tail_seg=seg, tail_bends=bends[:nseg], tail_radii=radii[:nseg + 1],
        head=head, head_rel=(0, -int(h["neck"])), neck_r=1.2)


WHITE_SPOTTING = ("tuxedo", "bicolor", "van", "calico")
LIGHT = ("white", "cream", "apricot", "silver")


def repair(genes: dict) -> list[str]:
    """Generation rules that steer random rolls away from combinations that
    read badly (they only run when rolling/mutating — a value the user picks
    in the editor is respected). Each repair is logged as a note."""
    notes = []
    c = genes["coat"]
    pick = int(c.get("seed", 0))
    if c["pattern"] in WHITE_SPOTTING and c["color"] == "white":
        c["color"] = ("black", "grey", "brown", "ginger")[pick % 4]
        notes.append(f"white-spotting on a white coat -> {c['color']}")
    if c["pattern"] == "point" and c["color"] in LIGHT + ("ginger",):
        c["color"] = ("chocolate", "grey", "black")[pick % 3]
        notes.append(f"colourpoint needs dark points -> {c['color']}")
    if c["pattern"] in ("tabby", "spotted") and c["color"] in ("black", "white"):
        c["color"] = ("brown", "grey", "ginger", "silver")[pick % 4]
        notes.append(f"stripes would be invisible -> {c['color']}")
    if c["pattern"] in ("tortie", "calico") and c["color"] in ("ginger", "apricot", "cream", "white"):
        c["color"] = ("black", "chocolate", "grey")[pick % 3]
        notes.append(f"tortie/calico base -> {c['color']}")
    e = genes["eyes"]
    if e.get("odd") and e.get("right") == e.get("left"):
        e["right"] = "blue" if e.get("left") != "blue" else "amber"
        notes.append("odd eyes need two colours")
    b = genes["body"]
    # very short legs under a very deep body read as a sausage: keep a
    # minimum leg-to-depth ratio
    if b["legs"] < b["depth"] * 0.72:
        b["legs"] = round(b["depth"] * 0.72, 2)
        notes.append("legs lengthened to carry the body")
    return notes


# coat presets shown in the editor (the old Settings → Coat skins live on)
PRESETS = {
    "Black": {"coat": {"color": "black", "pattern": "solid"},
              "eyes": {"left": "amber", "odd": False, "nose": "plum"}},
    "White": {"coat": {"color": "white", "pattern": "solid"},
              "eyes": {"left": "blue", "odd": False, "nose": "pink"}},
    "Van kedisi": {"coat": {"color": "white", "pattern": "solid"},
                   "eyes": {"left": "blue", "odd": True, "right": "amber", "nose": "pink"}},
    "Grey": {"coat": {"color": "grey", "pattern": "solid"},
             "eyes": {"left": "green", "odd": False, "nose": "dusky"}},
    "Ginger": {"coat": {"color": "ginger", "pattern": "tabby"},
               "eyes": {"left": "green", "odd": False, "nose": "brick"}},
    "Cream": {"coat": {"color": "cream", "pattern": "solid"},
              "eyes": {"left": "green", "odd": False, "nose": "pink"}},
    "Tuxedo": {"coat": {"color": "black", "pattern": "tuxedo", "socks": True},
               "eyes": {"left": "green", "odd": False, "nose": "pink"}},
    "Calico": {"coat": {"color": "black", "pattern": "calico", "white": 0.55},
               "eyes": {"left": "amber", "odd": False, "nose": "pink"}},
    "Siamese": {"coat": {"color": "chocolate", "pattern": "point"},
                "eyes": {"left": "blue", "odd": False, "nose": "dusky"}},
}

FAMILY = QuadFamily(
    name="feline", label="Cat", schema=SCHEMA, anatomy_fn=anatomy, canon=CANON,
    vocal="meow", repair_fn=repair, presets=PRESETS)
