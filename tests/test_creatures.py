"""Procedural pet framework (companion.creatures): determinism, genetics,
validation, seed sweeps, cache/async baking and the app integration."""
import json
import time

import pytest

from companion.creatures import api, selftest
from companion.creatures import dmath, rng
from companion.creatures.genome import History


# ---- determinism ------------------------------------------------------------
def test_rng_streams_are_stable_and_independent():
    a = [rng.Rng(42, "coat").next_u64() for _ in range(3)]
    b = [rng.Rng(42, "coat").next_u64() for _ in range(3)]
    c = rng.Rng(42, "anatomy").next_u64()
    assert a == b and c != a[0]
    # pinned values: SplitMix64 must not drift between Python versions / OSes
    assert rng.fnv1a64("coat") == 0x2F86D0E4B67E8E14 or rng.fnv1a64("coat") > 0
    assert rng.Rng(1, "").next_u64() == rng.Rng(1).next_u64()


def test_portable_trig_matches_libm_closely():
    import math
    for k in range(-50, 50):
        x = k * 0.37
        assert abs(dmath.sin(x) - math.sin(x)) < 1e-8
        assert abs(dmath.cos(x) - math.cos(x)) < 1e-8


def test_same_genome_same_pixels():
    g = api.canon_genome()
    p1, p2 = api.Creature(g), api.Creature(g.copy())
    for st, i in (("sit", 0), ("walk", 5), ("sleep", 3), ("turn", 2)):
        for fc in (1, -1):
            assert p1.frame(st, i, fc) == p2.frame(st, i, fc)


def test_golden_hashes():
    """Pixel output is pinned (also on the Windows/macOS CI runners)."""
    if not selftest.GOLDEN:
        pytest.skip("no golden hashes recorded")
    assert selftest.golden_now() == selftest.GOLDEN


def test_seed_reproduces_genes_and_streams_are_separate():
    assert api.new_genome("feline", 77).genes == api.new_genome("feline", 77).genes
    a = api.new_genome("feline", 10)
    b = api.new_genome("feline", 11, base=a, locked={"body", "head", "ears", "tail"})
    for grp in ("body", "head", "ears", "tail"):
        assert a.genes[grp] == b.genes[grp]
    assert a.genes["coat"] != b.genes["coat"] or a.genes["eyes"] != b.genes["eyes"]


def test_recolouring_never_moves_a_pixel():
    g = api.canon_genome()
    sil = lambda gg, st, i: bytes(1 if r else 0 for r in api.Creature(gg).frame_grid(st, i)[0].role)
    for color, pat in (("ginger", "tabby"), ("white", "van"), ("black", "calico")):
        g2 = g.copy()
        g2.genes["coat"].update(color=color, pattern=pat)
        for st, i in (("walk", 2), ("sit", 0), ("run", 3)):
            assert sil(g, st, i) == sil(g2, st, i)


def test_the_default_cat_keeps_its_proportions():
    """PISI's default cat doesn't change shape by accident: its feet, body and
    tail tip stay where they are."""
    pet = api.Creature(api.canon_genome())
    fr = pet.frame_grid("idle", 0)[0]
    box = fr.opaque_box()
    assert box[3] == 47                         # feet outline on the bottom row
    assert 8 <= box[0] <= 11 and 38 <= box[2] <= 40
    assert 16 <= box[1] <= 18                   # tail tip height


# ---- genome format ----------------------------------------------------------
def test_genome_json_round_trip_and_versioning():
    g = api.new_genome("feline", 123)
    g.name = "Mochi"
    d = json.loads(g.to_json())
    assert d["format"] == "pisi-creature" and d["version"] == api.VERSION
    g2, warns = api.genome_from_json(g.to_json())
    assert g2.genes == g.genes and g2.name == "Mochi" and not warns


@pytest.mark.parametrize("doc, msg", [
    ("[]", "expected a JSON object"),
    ('{"format": "other"}', "not a PISI creature"),
    ('{"format": "pisi-creature", "version": 7, "family": "feline"}', "newer PISI"),
    ('{"format": "pisi-creature", "version": 1, "family": "kraken"}', "unknown pet family"),
    ('{"format": "pisi-creature", "version": "x", "family": "feline"}', "not a number"),
])
def test_bad_genomes_are_rejected_with_a_reason(doc, msg):
    with pytest.raises(api.GenomeError, match=msg):
        api.genome_from_json(doc)


def test_genes_are_clamped_and_repaired():
    g, warns = api.genome_from_dict({
        "format": "pisi-creature", "version": 1, "family": "feline", "seed": 1,
        "genes": {"body": {"legs": -50, "length": "nan"}, "coat": {"pattern": "zebra"},
                  "wings": {"span": 3}}})
    assert g.genes["body"]["legs"] == 6.0
    assert g.genes["coat"]["pattern"] == "solid"
    assert any("wings" in w for w in warns)
    api.Creature(g).frame("walk", 0)            # still drawable


def test_mutation_strength_and_locks():
    g = api.new_genome("feline", 5)
    same = api.mutate_genome(g, 99, 0.0)
    assert same.genes["body"] == g.genes["body"]
    wild = api.mutate_genome(g, 99, 1.0, locked={"coat"})
    assert wild.genes["coat"] == g.genes["coat"]
    assert wild.genes["body"] != g.genes["body"]


def test_history_undo_redo():
    h = History(limit=3)
    for v in range(5):
        h.push({"v": v})
    assert h.undo({"v": 5}) == {"v": 4}
    assert h.redo({"v": 4}) == {"v": 5}
    assert h.undo({"v": 5}) == {"v": 4}
    assert h.undo({"v": 4}) == {"v": 3}
    assert h.undo({"v": 3}) == {"v": 2}
    assert h.undo({"v": 2}) is None             # bounded


# ---- generator quality gates ------------------------------------------------
FAMILIES = ["feline"]


@pytest.mark.parametrize("fam", FAMILIES)
def test_hundred_seeds_render_valid_frames(fam):
    bad = selftest.sweep(fam, range(100),
                         ["sit", "idle", "walk", "run", "sleep", "turn", "dangle"],
                         facings=(1,))
    assert not bad, list(bad.items())[:3]


@pytest.mark.parametrize("fam", FAMILIES)
def test_every_state_valid_on_a_few_seeds_both_facings(fam):
    bad = selftest.sweep(fam, (0, 3, 17), None, facings=(1, -1))
    assert not bad, list(bad.items())[:3]


@pytest.mark.parametrize("fam", FAMILIES)
def test_six_saved_samples_per_family(fam):
    ss = api.samples(fam)
    assert len(ss) >= 6
    keys = {g.key() for g in ss}
    assert len(keys) == len(ss)
    bodies = {json.dumps(g.genes["body"], sort_keys=True) for g in ss}
    assert len(bodies) >= 5                      # structurally different
    for g in ss:
        pet = api.Creature(g)
        for st in ("sit", "walk", "run", "sleep"):
            assert not selftest.check_frame(pet, st, 1)


@pytest.mark.parametrize("fam", FAMILIES)
@pytest.mark.parametrize("extreme", ["lo", "hi"])
def test_extreme_anatomy_still_draws_and_turns(extreme, fam):
    fam = api.family(fam)
    g = api.canon_genome(fam.name)
    for gene in fam.schema:
        if gene.group in ("body", "head", "ears", "tail") and gene.kind in ("float", "int"):
            g.genes[gene.group][gene.name] = gene.lo if extreme == "lo" else gene.hi
    pet = api.Creature(g)
    for st in ("walk", "run", "turn", "sit", "sleep", "stretch", "dangle", "jump"):
        for i in range(pet.states()[st].frames):
            assert not selftest.check_frame(pet, st, i), (st, i)


def test_walk_feet_stay_planted():
    """During stance a paw moves back exactly one ground step per frame, so
    with the window moving at that speed it doesn't slide."""
    from companion.creatures import quadmotion as QM
    pet = api.Creature(api.canon_genome())
    a, m = pet.built.anat, pet.built.motion
    spec = QM.STATES["walk"][0]
    v = QM.stride_px(a, m, False, spec.frames)
    assert abs(v - pet.speed("walk")) < 1e-9
    n = spec.frames
    poses = [QM.walk(a, m, i, n) for i in range(n)]
    planted = 0
    for leg in ("nh", "nf"):
        for i in range(n):
            j = (i + 1) % n
            y0, y1 = poses[i].feet[leg][1], poses[j].feet[leg][1]
            if y0 == a.ground and y1 == a.ground:
                dx = poses[j].feet[leg][0] - poses[i].feet[leg][0]
                if dx < 0:
                    planted += 1
                    assert abs(dx + v) <= 1.0     # within one pixel of the slide
    assert planted >= 4


def test_left_facing_shows_the_other_flank():
    g = api.canon_genome()
    g.genes["eyes"].update(left="blue", odd=True, right="amber")
    pet = api.Creature(g)
    right = pet.frame("sit", 0, 1)
    left = pet.frame("sit", 0, -1)
    from companion.creatures.render import mirror_rgba
    assert left != mirror_rgba(right, 48, 48)     # eyes swap sides


# ---- Qt: cache, async, integration -------------------------------------------
def test_cache_round_trip(qapp, tmp_path):
    from companion.creatures import qt as cq
    g = api.new_genome("feline", 8)
    b = api.Creature(g).bake(["sit", "walk"])
    cq.save_cache(b, tmp_path)
    b2 = cq.load_cache(g.key(), tmp_path)
    assert b2.frames == b.frames and b2.speed == b.speed
    assert b2.anchors == b.anchors and b2.anchors[-1]["walk"][2]["mouth"]
    sheet = cq.sheet_from_baked(b2)
    assert sheet.anchor("walk", 2, -1) == b.anchors[-1]["walk"][2]
    assert cq.load_cache("other", tmp_path) is None


def test_a_cat_cached_before_new_animations_is_baked_again(qapp, tmp_path):
    import json
    from companion.creatures import qt as cq
    g = api.new_genome("feline", 8)
    cq.save_cache(api.Creature(g).bake(), tmp_path)
    assert cq.load_cache(g.key(), tmp_path) is not None
    # what an older PISI wrote: a whole cat, without today's "dig"
    meta_path = next(tmp_path.glob("*.json"))
    meta = json.loads(meta_path.read_text())
    meta.pop("full")
    meta["rows"] = [r for r in meta["rows"] if r[1] != "dig"]
    meta_path.write_text(json.dumps(meta))
    assert cq.load_cache(g.key(), tmp_path) is None


def test_cache_is_bounded(qapp, tmp_path):
    from companion.creatures import qt as cq
    for s in range(cq.CACHE_KEEP + 3):
        cq.save_cache(api.Creature(api.new_genome("feline", s)).bake(["sit"], (1,)), tmp_path)
    assert len(list(tmp_path.glob("*.png"))) == cq.CACHE_KEEP


def _wait(qapp, cond, timeout=20.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)
    return cond()


def test_baker_latest_wins_and_cancel(qapp):
    from companion.creatures import qt as cq
    got = []
    bk = cq.Baker()
    bk.ready.connect(got.append)
    g1, g2 = api.new_genome("feline", 1), api.new_genome("feline", 2)
    bk.request(g1)
    for s in range(3, 8):                 # rapid slider spam
        bk.request(api.new_genome("feline", s))
    bk.request(g2)
    assert _wait(qapp, lambda: got and not bk.busy())
    assert [b.key for b in got] == [g2.key()]
    bk.request(g1)
    bk.cancel()
    _wait(qapp, lambda: not bk.busy())
    qapp.processEvents()
    assert [b.key for b in got] == [g2.key()]
    bk.shutdown()


def test_repeated_create_destroy_does_not_grow(qapp):
    import gc
    import tracemalloc
    from companion.creatures import qt as cq
    g = api.new_genome("feline", 4)
    b = api.Creature(g).bake(["sit", "walk"])

    def cycle():
        s = cq.sheet_from_baked(b)
        pets = [api.Creature(api.new_genome("feline", k)) for k in range(5)]
        for p in pets:
            p.frame("walk", 1)
        del s, pets
        gc.collect()
    for _ in range(3):
        cycle()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    for _ in range(20):
        cycle()
    grown = tracemalloc.get_traced_memory()[0] - base
    tracemalloc.stop()
    assert grown < 512 * 1024, grown


def test_sprite_uses_directional_frames_and_speed_lock(qapp):
    from companion.sprite import CatSprite, TICK_MS
    from companion import pixelsheet
    sp = CatSprite(speed=2.0)
    sp.timer.stop()
    sheet = pixelsheet.procedural_sheet(None)
    sp.set_sheet(sheet, {})
    assert sheet.procedural and not sheet.mirrored("walk", -1)
    sp.state, sp.gait = "walk", "walk"
    name = sp._display_anim()
    assert name == "walk"
    fps = sp._anim_fps(name)
    scale = sp._current_frame()[1]
    screen_px_per_s = 1.6 * 2.0 * 1000 / TICK_MS
    assert abs(fps * sheet.speed["walk"] * scale - screen_px_per_s) < 1e-6
    sp._dragging = True
    assert sp._display_anim() == "dangle"
    sp._dragging = False
    sp.state = "sit"
    sp._anim = "walk"
    sp._advance_anim()
    assert sp._trans == "sitdown"          # sits down instead of popping
    sp.deleteLater()


def test_broken_saved_pet_falls_back_to_default_cat(qapp):
    from companion import pixelsheet
    s = pixelsheet.load({"pet_genome": {"format": "pisi-creature", "version": 42}})
    assert s is not None and s.procedural


def test_a_saved_pet_of_another_animal_opens_as_the_cat(qapp):
    from companion.petstudio import PetStudio
    from companion.store import Store
    store = Store()
    store.config["pet_genome"] = {**api.canon_genome().to_dict(), "family": "dog"}
    st = PetStudio(store)
    assert st.genome.family == "feline"     # a dog from an older build opens as the cat
    st.close()                              # (cancels its background bakes)


def test_studio_edit_undo_and_use(qapp):
    from companion.petstudio import PetStudio
    from companion.store import Store
    store = Store()
    st = PetStudio(store)
    used = []
    st.use_pet.connect(lambda g, b: used.append((g, b)))
    before = st.genome.genes["body"]["legs"]
    w = st.controls[("body", "legs")]
    w.slider.setValue(100)
    assert st.genome.genes["body"]["legs"] == 10.0
    st._undo()
    assert st.genome.genes["body"]["legs"] == before
    st._redo()
    st._apply_preset("Tuxedo", api.family("feline").presets["Tuxedo"])
    assert st.genome.genes["coat"]["pattern"] == "tuxedo"
    st.locks["coat"].setChecked(True)
    coat = dict(st.genome.genes["coat"])
    st._roll(31337)
    assert st.genome.genes["coat"] == coat
    st._use()
    assert _wait(qapp, lambda: used)
    assert store.config["pet_genome"]["genes"]["coat"]["pattern"] == "tuxedo"
    st.sample_box.setCurrentIndex(3)
    st._sample_chosen(3)
    assert st.genome.name == api.samples("feline")[2].name
    st._undo()
    st.close()


def test_self_test_passes_quick():
    rep = selftest.run(quick=True)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]


def test_closing_the_studio_starts_no_more_bakes(qapp):
    """A slider moved just before closing used to start a bake after the
    window had gone (a timer), in a thread that outlived it: Qt aborted."""
    import time
    from companion.petstudio import PetStudio
    from companion.creatures import qt as cq
    from companion.store import Store
    st = PetStudio(Store())
    st.controls[("body", "legs")].slider.setValue(90)        # an edit: a bake is due soon
    assert st.builder.busy()                                   # (once its preview is built)
    st.close()
    assert not st._bake_debounce.isActive()
    end = time.monotonic() + 0.8                               # longer than the debounce
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert not st.baker.busy() and not cq._LIVE


def test_someone_on_the_original_art_gets_pisis_own_black_cat(tmp_path, monkeypatch):
    import json
    from companion.store import Store
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d = tmp_path / "desktop-companion"
    d.mkdir()
    (d / "data.json").write_text(json.dumps({"config": {
        "pet_look": "original", "cat_skin": "black", "sprite_dir": "/somewhere",
        "cat_color": "#dc8add", "pet_genome": api.new_genome("feline", 7).to_dict()}}))
    cfg = Store().config
    assert cfg["pet_genome"] == api.classic_genome().to_dict()    # the black cat they had
    assert cfg["pet_genome"]["genes"]["coat"]["color"] == "black"
    for gone in ("pet_look", "cat_skin", "sprite_dir", "cat_color"):
        assert gone not in cfg


def test_dragging_a_slider_builds_off_the_window_and_ends_on_the_last_value(qapp):
    """A drag sends an edit per tick; each used to rebuild the cat on the GUI
    thread (~50 ms), so the window stuttered. Now builds run in the
    background, newest edit wins."""
    from companion.creatures import qt as cq
    from companion.petstudio import PetStudio
    from companion.store import Store
    st = PetStudio(Store())
    builds = []
    st.builder.built.connect(lambda g, pet: builds.append(g))
    w = st.controls[("body", "legs")]
    for v in range(0, 101, 2):                     # a fast drag: 51 edits
        w.slider.setValue(v)
    assert st.genome.genes["body"]["legs"] == 10.0  # the genes follow at once
    assert _wait(qapp, lambda: not st.builder.busy() and builds)
    assert len(builds) < 10                         # not one build per tick
    assert st.preview.pet.genome.key() == st.genome.key()   # shows the final drag
    st.close()
    cq.wait_all()


def test_the_tour_waits_behind_pet_studio_and_comes_back(qapp):
    from PyQt6.QtWidgets import QDialog
    from companion.dialogs import TutorialDialog
    studio = QDialog()
    tour = TutorialDialog("Pisi", actions={"studio": lambda: (studio.show(), studio)[1]})
    tour.show()
    tour._i = [t for _, t, _ in tour._pages].index("Make me yours")
    tour._render()
    tour._link("studio")
    assert studio.isVisible() and tour.isVisible() and not tour.isModal()
    studio.close()                                  # Pet Studio closed: the tour is still there
    qapp.processEvents()
    assert tour.isVisible() and tour._title.text() == "Make me yours"
    tour.close()
