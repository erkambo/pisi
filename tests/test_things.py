"""Things (beds, bowls, posts, toys) and the judge that gates them."""
import pytest

from companion.creatures import api, panel
from companion.creatures.render import FILL
from companion.things import fit as F, judge, scene
from companion.things.kinds import KINDS
from companion.things.palette import MATERIALS, delta_e, luminance

PANEL = panel.panel(("owners", "extremes", "samples"))


def _bed(style="donut", label="canon"):
    g = dict(panel.panel())[label]
    pet = api.Creature(g)
    ft = F.measure(pet)
    return KINDS["bed"].render({"style": style}, ft), pet, ft


def test_every_material_has_the_house_ramp():
    for name, (f, s, o) in MATERIALS.items():
        assert luminance(o) < luminance(s) < luminance(f), name


def test_perceptual_difference_sees_hue_not_just_brightness():
    ginger, sage = (220, 138, 58), (150, 178, 138)
    assert delta_e(ginger, sage) > 30            # clearly different colours
    assert delta_e((236, 232, 224), (226, 212, 186)) < 22     # white cat, oatmeal bed


@pytest.mark.parametrize("style", KINDS["bed"].STYLES)
def test_every_bed_style_passes_on_the_panel(style):
    rep = judge.judge("bed", {"style": style, "fabric": "sage"}, PANEL)
    assert rep.passed, [(f.cat, f.message) for f in rep.fails()][:5]
    assert rep.cats == len(PANEL)


def test_beds_are_sized_to_the_cat():
    cats = dict(panel.panel(("extremes",)))
    long_ = KINDS["bed"].render({}, F.measure(api.Creature(cats["long+tall"])))
    small = KINDS["bed"].render({}, F.measure(api.Creature(cats["short+stubby"])))
    assert long_.w > small.w + 3


# ---- the judge must catch what's wrong (mutation tests) ---------------------------
def test_judge_catches_a_floating_cat():
    r, pet, ft = _bed()
    r.cat_at = (r.cat_at[0], r.cat_at[1] - 1)
    assert any("floats" in m for lvl, m in KINDS["bed"].check(r, pet, ft) if lvl == "fail")


def test_judge_catches_a_covered_face():
    r, pet, ft = _bed()
    r.front = bytes([90, 90, 90, 255]) * (r.w * r.h)          # a wall over everything
    assert any("face" in m for lvl, m in KINDS["bed"].check(r, pet, ft) if lvl == "fail")


def test_judge_catches_a_cat_sticking_out():
    r, pet, ft = _bed()
    r.cat_at = (r.cat_at[0] + 12, r.cat_at[1])
    assert any("sticks out" in m for lvl, m in KINDS["bed"].check(r, pet, ft) if lvl == "fail")


def test_judge_catches_stray_pixels_and_open_outlines():
    r, pet, ft = _bed()
    fr = r.back_frame
    stray = r
    # a lone pixel in the empty corner
    fr.role[0] = FILL
    found = []
    judge.pixel_gate(stray, "canon", found)
    assert any("stray" in f.message for f in found)
    fr.role[0] = 0
    # an edge pixel that isn't outline
    edge = next(i for i, ro in enumerate(fr.role) if ro == 3)
    fr.role[edge] = FILL
    found = []
    judge.pixel_gate(r, "canon", found)
    assert any("open outline" in f.message for f in found)


def test_scene_draws_back_cat_front_in_order():
    r, pet, _ft = _bed("box")
    rgba, w, h, at = scene.compose(r, pet)
    assert at is not None and w >= r.w and h >= r.h
    # the box's front wall is drawn over the cat: its pixels win
    tx, ty = at[0] - r.cat_at[0], at[1] - r.cat_at[1]       # the thing in the scene
    fx, fy = r.w // 2, r.h - 3
    k = ((fy + ty) * w + fx + tx) * 4
    assert rgba[k:k + 4] == r.front[(fy * r.w + fx) * 4:(fy * r.w + fx) * 4 + 4]


@pytest.mark.parametrize("kind,style", [(k, st) for k in ("bowl", "post", "toy", "basket")
                                        for st in KINDS[k].STYLES])
def test_every_item_style_passes_on_the_panel(kind, style):
    rep = judge.judge(kind, {"style": style}, PANEL)
    assert rep.passed, [(f.cat, f.message) for f in rep.fails()][:5]


def test_toys_keep_their_grip_at_the_reach_height():
    from companion.creatures import quadmotion as QM
    ft = F.measure(api.Creature(api.canon_genome()))
    for style in KINDS["toy"].STYLES:
        r = KINDS["toy"].render({"style": style}, ft)
        assert r.floor - r.spots["grip"][1] == QM.TOY_GRIP


def test_judge_catches_a_bowl_out_of_reach_and_a_post_too_far():
    pet = api.Creature(api.canon_genome())
    ft = F.measure(pet)
    bowl = KINDS["bowl"].render({}, ft)
    bowl.cat_at = (bowl.cat_at[0] - 9, bowl.cat_at[1])
    assert any("misses" in m for lvl, m in KINDS["bowl"].check(bowl, pet, ft) if lvl == "fail")
    post = KINDS["post"].render({}, ft)
    post.cat_at = (post.cat_at[0] - 3, post.cat_at[1])
    assert any("off the post" in m for lvl, m in KINDS["post"].check(post, pet, ft) if lvl == "fail")


# ---- the catalog -------------------------------------------------------------------
def test_the_catalog_is_a_curated_list_of_thirty_to_forty():
    from companion.things import catalog
    items = catalog.ITEMS
    assert 30 <= len(items) <= 40
    assert len({it.id for it in items}) == len(items)
    assert len({it.name for it in items}) == len(items)
    for it in items:
        assert it.kind in KINDS and it.id.startswith(it.kind + ".")
        assert it.blurb and len(it.blurb) <= 48, it.id          # fits two lines on a card
        assert it.design.get("style", KINDS[it.kind].DEFAULT["style"]) in KINDS[it.kind].STYLES
    for kind in KINDS:
        assert len(catalog.of_kind(kind)) >= 6, kind
    assert all(it.price <= 10 for it in catalog.of_kind("toy"))   # toys are small treats


def test_every_catalog_item_looks_different_from_the_rest_of_its_kind():
    from companion.things import catalog
    ft = F.measure(api.Creature(api.canon_genome()))
    rendered = [(it.id, KINDS[it.kind].render(it.design, ft)) for it in catalog.ITEMS]
    assert judge.variety_gate(rendered) == []
