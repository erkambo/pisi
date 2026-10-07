"""The treat shop: buying, owning, the corner, and the unboxing (headless
Qt, on a simulated clock)."""
import collections

import pytest

from companion import shop
from companion.creatures import api, panel
from companion.things import catalog, fit as F, judge, parcel
from companion.things.kinds import KINDS
from companion.store import Store


class Clock:
    t = 5000.0

    @staticmethod
    def monotonic():
        return Clock.t


@pytest.fixture
def store(tmp_path):
    return Store()


def test_buying_costs_treats_and_keeps_it(store):
    sisal = catalog.BY_ID["post.sisal"]
    assert not shop.owns(store, sisal.id) and shop.short_by(store, sisal) == sisal.price
    assert not shop.buy(store, sisal.id)                     # can't afford it: nothing changes
    store.add_treats(sisal.price + 2)
    assert shop.buy(store, sisal.id)
    assert shop.owns(store, sisal.id) and store.treats() == 2
    assert not shop.buy(store, sisal.id)                     # never twice
    assert store.treats() == 2
    assert all(shop.owns(store, it.id) for it in catalog.starter())   # the starter set stays


def test_the_corner_takes_what_you_own(store):
    store.add_treats(100)
    shop.place(store, "bed", "bed.box")                      # not owned: ignored
    assert shop.placed(store)["bed"] == "bed.rose_donut"
    assert shop.buy(store, "bed.box") and shop.buy(store, "post.sisal")
    shop.place(store, "bed", "bed.box")
    shop.place(store, "post", "post.sisal")
    assert shop.placed(store)["bed"] == "bed.box" and shop.placed(store)["post"] == "post.sisal"
    shop.place(store, "post", None)                          # a post is optional
    shop.place(store, "bed", None)                           # a bed isn't
    assert "post" not in shop.placed(store) and shop.placed(store)["bed"] == "bed.box"


def test_what_the_treats_are_going_towards(store):
    goal = shop.next_goal(store)
    assert goal is not None and goal.price == min(it.price for it in catalog.ITEMS if it.price)
    store.add_treats(3)
    crossed = shop.just_affordable(store, 2)
    assert crossed is not None and crossed.price == 3
    assert shop.just_affordable(store, 3) is None


def test_the_parcel_passes_the_judge_for_every_cat():
    for label, g in panel.panel(("owners", "extremes", "samples")):
        ft = F.measure(api.Creature(g))
        for opened in (False, True):
            r = parcel.render(ft, opened)
            out = []
            judge.pixel_gate(r, label, out)
            judge.wallpaper_gate(r, label, out)
            assert not [f for f in out if f.level == "fail"], (label, opened, out)


# ---- the unboxing ------------------------------------------------------------------
@pytest.fixture(scope="module")
def cat():
    g = [v for k, v in panel.panel(("owners",)) if k != "canon"][0]
    pet = api.Creature(g)
    return g, pet, pet.bake(), F.measure(pet)


@pytest.fixture
def unbox(qapp, cat, monkeypatch, tmp_path):
    import random
    random.seed(3)
    import companion.playground as PG
    import companion.playtime as PTM
    import companion.unboxing as U
    from companion.creatures import qt as cq
    from companion.home import HomeCorner
    from companion.sprite import CatSprite
    for m in (PG, PTM, U):
        monkeypatch.setattr(m, "time", Clock)
    g, _pet, baked, ft = cat
    sp = CatSprite()
    sp.set_sheet(cq.sheet_from_baked(baked), {})
    sp.place_start()
    sp.show()
    st = Store()
    home = HomeCorner()
    scr = qapp.primaryScreen()

    def build():
        home.build(g, st.config, sp.pixel_scale(), sp.floor_line(scr), scr)
    build()
    sp.home = lambda k: home.spots.get(k)
    pt = PTM.PlayTime(sp, lambda: ft, lambda i: KINDS["toy"].render(catalog.BY_ID[i].design, ft))
    said = []

    def place(it):
        shop.place(st, it.kind, it.id)
        build()
    ub = U.Unboxing(sp, pt, lambda: ft, lambda it: KINDS[it.kind].render(it.design, ft),
                    place, lambda text, s: said.append(text))
    yield sp, pt, ub, st, home, said
    pt.stop(quiet=True)


def _run(sp, pt, ub, n, watch=None):
    seen = collections.Counter()
    for _ in range(n):
        for _sub in range(4):
            Clock.t += 0.0175
            if ub.parcel is not None and ub.parcel.isVisible():
                ub.parcel._step()
            if pt.toy:
                pt.toy._step()
        sp._tick()
        ub._tick()
        pt._tick()
        seen[sp._shown()[0]] += 1
        seen["phase:" + str(ub.phase)] += 1
        if watch:
            watch()
    return seen


def test_a_new_bed_arrives_in_a_parcel_and_gets_tried_out(unbox):
    sp, pt, ub, st, home, said = unbox
    st.add_treats(30)
    assert shop.buy(st, "bed.lavender_cup")
    it = catalog.BY_ID["bed.lavender_cup"]
    done, using = [], []
    ub.finished.connect(done.append)
    ub.finished.connect(lambda _i: using.append(sp.using()))
    assert ub.start(it)
    opened_near = []

    def watch():
        p = ub.parcel
        if p is not None and p.is_open and not opened_near:
            from companion.sprite import W
            opened_near.append(abs(sp.x() + W / 2 - p.x_mid))
    seen = _run(sp, pt, ub, 900, watch)
    assert done == [it.id], (seen, said)
    assert seen["eat"] and seen["bat"], seen            # sniffed it, pawed at it
    assert "a parcel! \U0001F4E6" in said and any(it.name in s for s in said)
    assert opened_near and opened_near[0] < sp._body().w * 1.6     # right by it when it opened
    assert shop.placed(st)["bed"] == it.id and home.spots["bed"].item_id == it.id
    assert using == ["bed"]                             # off to try it out
    assert not sp.in_play


def test_a_new_toy_jumps_out_and_playtime_starts(unbox):
    sp, pt, ub, st, home, said = unbox
    st.add_treats(5)
    assert shop.buy(st, "toy.ball_gold")
    done = []
    ub.finished.connect(done.append)
    assert ub.start(catalog.BY_ID["toy.ball_gold"])
    _run(sp, pt, ub, 900, lambda: None if not done else None)
    assert done == ["toy.ball_gold"]
    assert pt.mode == "toy" and pt.toy is not None and pt.toy.toy.design["style"] == "ball"


def test_picking_the_cat_up_just_opens_it(unbox):
    sp, pt, ub, st, home, said = unbox
    st.add_treats(30)
    assert shop.buy(st, "bed.box")
    done = []
    ub.finished.connect(done.append)
    assert ub.start(catalog.BY_ID["bed.box"])
    _run(sp, pt, ub, 40)
    sp._dragging = True
    _run(sp, pt, ub, 3)
    sp._dragging = False
    assert done == ["bed.box"] and shop.placed(st)["bed"] == "bed.box" and not sp.in_play


# ---- in the app --------------------------------------------------------------------
def _fake_app(store, phase=None):
    from types import SimpleNamespace
    from companion import species
    said, unboxed, anims, uses = [], [], [], []
    fake = SimpleNamespace(
        store=store, _species=lambda: species.CAT,
        say=lambda text, seconds=0: said.append(text),
        focus=SimpleNamespace(active=lambda: phase is not None, phase=phase),
        playtime=SimpleNamespace(active=lambda: False),
        unboxing=SimpleNamespace(active=lambda: False),
        sprite=SimpleNamespace(play_emote=lambda *_: None,
                               do_anim=lambda a, **k: anims.append(a) or True,
                               go_use=lambda k, s=None, anim=None: uses.append(k) or True),
        _home_spot=lambda k: object(),
        _unbox_queue=[], _unbox=unboxed.append)
    return fake, said, unboxed, anims, uses


def test_giving_a_treat_is_free_and_it_goes_to_its_bowl(store):
    from companion.app import Companion
    store.add_treats(5)
    fake, said, _u, anims, uses = _fake_app(store)
    Companion.give_treat(fake)
    assert store.treats() == 5 and uses == ["bowl"]           # free; off to the bowl
    Companion.give_treat(fake)                                 # again straight away: full
    assert store.treats() == 5 and uses == ["bowl"] and "full" in said[-1]


def test_bought_during_a_focus_block_it_arrives_in_the_break(store):
    from companion.app import Companion
    store.add_treats(10)
    fake, said, unboxed, _a, _u = _fake_app(store, phase="focus")
    it = catalog.BY_ID["bed.box"]
    assert Companion._shop_buy(fake, it) and store.treats() == 0
    assert unboxed == [] and fake._unbox_queue == [it]         # the cat is napping: later
    Companion._next_unbox(fake)
    assert unboxed == []
    fake.focus.phase = "break"
    Companion._next_unbox(fake)
    assert unboxed == [it] and fake._unbox_queue == []
    assert not Companion._shop_buy(fake, it)                   # already have it


def test_the_menu_offers_the_shop_and_a_free_treat():
    """(The full menu needs the whole app; its code is checked instead.)"""
    import inspect
    from companion.app import Companion
    src = inspect.getsource(Companion._populate_menu)
    assert "self.open_shop" in src and "_home_genome() is not None" in src
    assert "Give a treat" in src and "setEnabled(n > 0)" not in src     # never greyed out


def test_the_shop_window_buys_with_two_clicks(qapp, store, cat, monkeypatch):
    import companion.shopwindow as SW
    from companion.creatures import qt as cq
    monkeypatch.setattr(SW, "time", Clock)
    _g, _pet, baked, ft = cat
    store.add_treats(12)
    bought, placed = [], []

    def on_buy(it):
        ok = shop.buy(store, it.id)
        bought.append(it.id)
        return ok
    w = SW.ShopWindow(store, cq.sheet_from_baked(baked), ft, "\U0001F36A", on_buy,
                      lambda k, i: (shop.place(store, k, i), placed.append((k, i))))
    card = {c.item.id: c for c in w.cards}
    box = card["bed.box"]
    assert box.button.isVisibleTo(box) and box.button.text() == "Buy"
    box.button.click()                                        # one click: just asks
    assert bought == [] and box.button.text().startswith("Sure?")
    Clock.t += SW.CONFIRM_S + 0.1                             # ... and forgets
    box.refresh()
    assert box.button.text() == "Buy"
    box.button.click()
    box.button.click()                                        # two clicks: bought
    assert bought == ["bed.box"] and store.treats() == 2
    assert box.status.text().startswith("\U0001F4E6") and not box.button.isVisibleTo(box)
    w.arrived("bed.box")                                      # unboxed (and put in the corner)
    assert box.button.text() == "Put in the corner"
    box.button.click()
    assert placed == [("bed", "bed.box")] and box.status.text().startswith("In the corner")
    pillow = card["bed.navy_pillow"]
    assert not pillow.button.isVisibleTo(pillow) and "13 more blocks" in pillow.status.text()
    assert "\U0001F36A 2" in w.pill.text()


def test_the_shop_has_a_chip_for_every_section_that_scrolls_to_it(qapp, store, cat):
    import companion.shopwindow as SW
    from PyQt6.QtWidgets import QPushButton
    from companion.creatures import qt as cq
    _g, _pet, baked, ft = cat
    w = SW.ShopWindow(store, cq.sheet_from_baked(baked), ft, "\U0001F36A",
                      lambda it: False, lambda k, i: None)
    w.resize(w.width(), 600)
    w.show()
    qapp.processEvents()
    chips = [b for b in w.findChildren(QPushButton) if b.objectName() == "chip"]
    assert [c.text() for c in chips] == [shop.KIND_TITLES[k] for k in shop.KINDS]
    bar = w.scroll.verticalScrollBar()
    assert bar.maximum() > 0                                  # 40 things don't fit on one screen
    w._glide.setDuration(0)
    chips[-1].click()                                         # the last section: the baskets
    w._glide.setCurrentTime(w._glide.duration())
    qapp.processEvents()
    sec = w.sections["basket"]
    top = sec.mapTo(w.scroll.viewport(), sec.rect().topLeft()).y()
    assert bar.value() > 0 and (top < 40 or bar.value() == bar.maximum())
    w.close()
