"""Rig anchors (mouth, head top, paws) and the review panel: the things a
held toy, a bed or a scratching post will be placed by, checked on cats of
every shape."""
import pytest

from companion.creatures import api, panel

STATES = ("sit", "idle", "walk", "run", "eat", "sleep", "stretch", "pounce")


def _alpha(pet, state, i, facing, x, y):
    w, h = pet.size
    if not (0 <= x < w and 0 <= y < h):
        return 0
    return pet.frame(state, i, facing)[(y * w + x) * 4 + 3]


def _near_cat(pet, state, i, facing, pt, r=1):
    """The anchor is on the cat (or right at its edge: the mouth line can sit
    on the chin's outline pixel)."""
    x, y = pt
    return any(_alpha(pet, state, i, facing, x + dx, y + dy)
               for dx in range(-r, r + 1) for dy in range(-r, r + 1))


def test_panel_is_fixed_and_covers_the_extremes():
    cats = panel.panel()
    labels = [lbl for lbl, _ in cats]
    assert len(labels) == len(set(labels)) >= 50
    assert labels[0] == "canon"
    assert {"long+tall", "short+stubby", "big-head", "stub-tail"} <= set(labels)
    assert any("PISI" in lbl for lbl in labels)          # an owner's real cat
    assert [g.key() for _, g in panel.panel()] == [g.key() for _, g in cats]


@pytest.mark.parametrize("label,genome", panel.panel(("owners", "extremes")),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_anchors_sit_on_the_cat(label, genome):
    pet = api.Creature(genome)
    for state in STATES:
        n = pet.states()[state].frames
        for i in range(n):
            an = pet.anchors(state, i, 1)
            assert an["mouth"] and _near_cat(pet, state, i, 1, an["mouth"]), (state, i)
            assert an["head_top"] and _near_cat(pet, state, i, 1, an["head_top"]), (state, i)
            for leg, pt in an["paws"].items():
                assert _near_cat(pet, state, i, 1, pt), (state, i, leg)


def test_mirrored_anchors_match_the_mirrored_frame():
    pet = api.Creature(api.canon_genome())
    w = pet.size[0]
    for state in ("walk", "eat", "turn"):
        for i in range(pet.states()[state].frames):
            r, l = pet.anchors(state, i, 1), pet.anchors(state, i, -1)
            assert l["ground"] == r["ground"]
            for key in ("mouth", "head_top"):
                if state != "turn":   # a turn draws the two flanks differently
                    assert l[key] == (w - 1 - r[key][0], r[key][1])
                assert _near_cat(pet, state, i, -1, l[key])


def test_bake_carries_anchors_for_every_frame():
    pet = api.Creature(api.canon_genome())
    b = pet.bake(["walk", "sit"])
    for fc in (1, -1):
        for state in ("walk", "sit"):
            assert len(b.anchors[fc][state]) == len(b.frames[fc][state])
    assert b.anchors[1]["walk"][3] == pet.anchors("walk", 3, 1)


# ---- the new "things" animations: contacts land where the thing will be ----
from companion.creatures import quadmotion as QM  # noqa: E402

THINGS = ("curl", "curldown", "curlup", "carrywalk", "carrytrot", "carrysit",
          "pickup", "drop", "bat", "scratch", "knead", "stalk", "watch", "watchup",
          "curlrim", "rimdown", "rimup")
PANEL = panel.panel(("owners", "extremes", "samples"))


@pytest.mark.parametrize("label,genome", PANEL, ids=[lbl for lbl, _ in PANEL])
def test_things_animations_stay_in_frame(label, genome):
    pet = api.Creature(genome)
    for st in THINGS:
        for i in range(pet.states()[st].frames):
            for fc in (1, -1):
                fr, _ = pet.frame_grid(st, i, fc)
                assert not fr.clipped, (st, i, fc)


@pytest.mark.parametrize("label,genome", PANEL, ids=[lbl for lbl, _ in PANEL])
def test_contacts_land_on_the_thing(label, genome):
    pet = api.Creature(genome)
    a = pet.built.anat

    def frames(st):
        return range(pet.states()[st].frames)

    def dist(p, q):
        return abs(p[0] - q[0]) + abs(p[1] - q[1])

    # a held toy never jumps: the mouth moves at most a pixel per frame
    for st in ("carrywalk", "carrytrot", "carrysit"):
        ms = [pet.anchors(st, i)["mouth"] for i in frames(st)]
        for m0, m1 in zip(ms, ms[1:] + ms[:1]):
            assert abs(m1[0] - m0[0]) <= 1 and abs(m1[1] - m0[1]) <= 1, st
    # picking up: the mouth reaches the toy on the floor
    spot = QM.toy_spot(a)
    assert min(dist(pet.anchors("pickup", i)["mouth"], spot) for i in frames("pickup")) <= 1
    assert min(dist(pet.anchors("drop", i)["mouth"], spot) for i in frames("drop")) <= 1
    # batting: the swipe touches the toy
    tgt = QM.bat_target(a)
    assert min(dist(pet.anchors("bat", i)["paws"]["nf"], tgt) for i in frames("bat")) <= 1
    # scratching: front paw on the post, hind paws planted, a real stroke
    g = QM.scratch_geometry(a)
    ys = []
    for i in frames("scratch"):
        an = pet.anchors("scratch", i)
        assert abs(an["paws"]["nf"][0] - (g["post_x"] - 1)) <= 1, i
        assert an["paws"]["nh"][1] == int(a.ground) + 1, i
        ys.append(an["paws"]["nf"][1])
    assert max(ys) - min(ys) >= 3
