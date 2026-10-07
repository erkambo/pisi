"""PISI's corner: the strip of things and the cat using them (headless Qt)."""
import pytest
from PyQt6.QtCore import QPoint

from companion.creatures import api, panel
from companion.things import catalog, fit as F, layout as L
from companion.things.kinds import KINDS

ALL = {"bed": "bed.rose_donut", "post": "post.tower", "bowl": "bowl.blue",
       "basket": "basket.wicker"}


@pytest.fixture(scope="module")
def baked():
    g = dict(panel.panel(("owners",)))
    genome = [v for k, v in g.items() if k != "canon"][0]
    return genome, api.Creature(genome).bake()


def _setup(qapp, baked, placed=ALL, side="left", offset=0):
    from companion.creatures import qt as cq
    from companion.home import HomeCorner
    from companion.sprite import CatSprite
    genome, b = baked
    sp = CatSprite()
    sp.set_sheet(cq.sheet_from_baked(b), {})
    sp.place_start()
    home = HomeCorner()
    scr = qapp.primaryScreen()
    assert home.build(genome, {"home": {"placed": dict(placed), "side": side, "offset": offset}},
                      sp.pixel_scale(), sp.floor_line(scr), scr)
    sp.home = lambda k: home.spots.get(k)
    return sp, home, scr


def _run_until(sp, cond, n=4000):
    for _ in range(n):
        sp._tick()
        if cond():
            return True
    return False


def _frame_pos(sp):
    x, y, _w, _h = sp._sprite_box()
    return sp.pos() + QPoint(x, y)


def test_layout_leaves_room_for_the_cat_and_keeps_order():
    pet = api.Creature(api.canon_genome())
    ft = F.measure(pet)
    things = {k: (v, KINDS[k].render(catalog.BY_ID[v].design, ft)) for k, v in ALL.items()}
    placed, width, height = L.layout(things, pet)
    assert [p.kind for p in placed] == list(L.ORDER)
    for a, b in zip(placed, placed[1:]):
        assert b.x >= a.x + a.r.w + L.GAP + L.cat_room(b.r, pet)
    assert width >= placed[-1].x + placed[-1].r.w and height == max(p.r.h for p in placed)


@pytest.mark.parametrize("kind", ["bed", "post", "bowl"])
def test_the_cat_walks_over_and_uses_a_thing_exactly_in_place(qapp, baked, kind):
    sp, home, scr = _setup(qapp, baked)
    sp.move(scr.availableGeometry().center().x(), sp._floor_y())
    sp._sync_fpos()
    assert sp.go_use(kind, 2.0)
    assert _run_until(sp, lambda: sp.state == "use")
    spot = home.spots[kind]
    assert _frame_pos(sp) == spot.cat_frame_pos(sp.sheet.frame_w)
    assert sp.facing == spot.facing and sp._thing["anim"] == spot.r.cat_state
    # after its time it gets out and goes about its day
    assert _run_until(sp, lambda: sp._thing is None and sp.state != "hop", 600)
    assert sp.using() is None


def test_focus_naps_in_the_bed_and_wakes_out_of_it(qapp, baked):
    sp, home, scr = _setup(qapp, baked)
    sp.move(scr.availableGeometry().center().x(), sp._floor_y())
    sp._sync_fpos()
    sp.begin_focus()
    assert _run_until(sp, lambda: sp.state == "use")
    assert sp.using() == "bed" and sp._thing["until"] is None
    for d in (0.2, 0.5, 0.9):                  # the block running down doesn't wake it
        sp.focus_pose(d)
        sp._tick()
        assert sp.state == "use"
    sp.wake_stretch(celebrate=True)
    assert _run_until(sp, lambda: sp._thing is None and sp.state not in ("hop", "sit"), 400)
    assert sp.state in ("celebrate", "stretch", "yawn", "meow")


def test_dragging_takes_it_out_of_the_thing(qapp, baked):
    sp, home, _scr = _setup(qapp, baked)
    assert sp.go_use("bed", 30)
    assert _run_until(sp, lambda: sp.state == "use")
    sp._drop_thing()
    assert sp.using() is None and sp.state == "sit" and not sp._exact


def test_no_corner_without_a_procedural_cat_or_when_off(qapp, baked):
    from companion.home import HomeCorner
    home = HomeCorner()
    scr = qapp.primaryScreen()
    assert not home.build(None, {}, 3, 700, scr) and not home.spots
    assert not home.build(baked[0], {"home": {"enabled": False}}, 3, 700, scr)


def test_a_right_hand_corner_is_the_mirror_image(qapp, baked):
    sp, home, scr = _setup(qapp, baked, side="right")
    g = scr.availableGeometry()
    assert home.geometry().right() == g.right()
    bed = home.spots["bed"]
    assert bed.facing == -1 and bed.pos.x() > home.spots["post"].pos.x()
    sp.move(g.center().x(), sp._floor_y())
    sp._sync_fpos()
    assert sp.go_use("post", 2.0)
    assert _run_until(sp, lambda: sp.state == "use")
    assert sp.facing == -1 and _frame_pos(sp) == home.spots["post"].cat_frame_pos(sp.sheet.frame_w)


def test_every_thing_fits_in_the_cat_window_for_every_cat():
    """While in use a thing is drawn inside the cat's own window: it must fit."""
    from companion import sprite as S
    s = 3
    bx, by = (S.W - 48 * s) // 2, S.BASELINE - 48 * s + 8
    for _label, g in panel.panel(("owners", "extremes", "samples")):
        ft = F.measure(api.Creature(g))
        for it in catalog.ITEMS:
            if it.kind == "toy":
                continue
            r = KINDS[it.kind].render(it.design, ft)
            for fc in (1, -1):
                cx, cy = r.cat_at_facing(fc, 48)
                lx, ly = bx - cx * s, by - cy * s
                assert lx >= 0 and ly >= 0 and lx + r.w * s <= S.W and ly + r.h * s <= S.H, it.id


def test_x11_panels_are_kept_off_the_floor(qapp, monkeypatch):
    """Multi-monitor X11: Qt says the whole screen is usable; the work area
    (one rectangle for all monitors) knows about the panel."""
    from PyQt6.QtCore import QRect
    from companion import screens, xwin

    class Scr:
        def __init__(self, geo, avail, dpr):
            self._g, self._a, self._d = geo, avail, dpr

        def geometry(self):
            return self._g

        def availableGeometry(self):
            return self._a

        def devicePixelRatio(self):
            return self._d
    monkeypatch.setattr(screens.QApplication, "platformName", staticmethod(lambda: "xcb"))
    monkeypatch.setattr(xwin, "workarea", lambda max_age=5.0: (0, 0, 6912, 2070))
    big = QRect(3072, 0, 1920, 1080)          # 3840x2160 real pixels at 2x, panel 90 px
    assert screens.usable(Scr(big, big, 2.0)) == QRect(3072, 0, 1920, 1035)
    small = QRect(0, 0, 1536, 960)            # 3072x1920 at 2x: above the panel's reach
    assert screens.usable(Scr(small, small, 2.0)) == small
    known = QRect(0, 0, 1536, 920)            # Qt already knows: trust it
    assert screens.usable(Scr(small, known, 2.0)) == known


def test_corner_modes_full_bed_off():
    from companion.home import STARTER, home_config
    assert home_config({})["placed"] == STARTER and home_config({})["enabled"]
    assert list(home_config({"home": {"mode": "bed"}})["placed"]) == ["bed"]
    assert not home_config({"home": {"mode": "off"}})["enabled"]
    assert not home_config({"home": {"enabled": False}})["enabled"]
    assert home_config({"home": {"mode": "nonsense"}})["mode"] == "full"



def test_the_corner_stands_in_the_taskbar_strip_and_the_cat_hops_down(qapp, baked):
    sp, home, scr = _setup(qapp, baked)
    geo = scr.geometry()
    assert home.geometry().bottom() == geo.bottom()          # on the screen's bottom edge
    bed = home.spots["bed"]
    assert bed.pos.y() + bed.r.h * bed.scale == geo.bottom() + 1
    sp.move(geo.center().x(), sp._floor_y())
    sp._sync_fpos()
    floor_y = sp.y()
    assert sp.go_use("bowl", 1.0)
    assert _run_until(sp, lambda: sp.state == "hop")         # walks on its floor, then hops
    assert _run_until(sp, lambda: sp.state == "use")
    assert _frame_pos(sp) == home.spots["bowl"].cat_frame_pos(sp.sheet.frame_w)
    assert _run_until(sp, lambda: sp._thing is None and sp.state not in ("hop",), 600)
    assert sp.y() == floor_y                                  # back up on its usual floor


def test_default_offset_and_dragging_along_the_bottom(qapp, baked):
    from companion.home import HomeCorner, default_offset
    from PyQt6.QtCore import QPointF, QEvent
    from PyQt6.QtGui import QMouseEvent
    genome, _b = baked
    scr = qapp.primaryScreen()
    g = scr.geometry()
    home = HomeCorner()
    assert home.build(genome, {"home": {"side": "right"}}, 3, g.bottom() - 40, scr)
    assert home.offset() == default_offset(g.width())
    moved, started = [], []
    home.moved.connect(moved.append)
    home.drag_started.connect(lambda: started.append(1))

    ox, oy = home.x(), home.y()

    def ev(kind, x):
        gp = QPointF(ox + 5 + x, oy + home.height() - 3)
        return QMouseEvent(kind, QPointF(5 + x, home.height() - 3), gp,
                           __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.MouseButton.LeftButton,
                           __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.MouseButton.LeftButton,
                           __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.KeyboardModifier.NoModifier)
    x0 = home.x()
    home.mousePressEvent(ev(QEvent.Type.MouseButtonPress, 0))
    home.mouseMoveEvent(ev(QEvent.Type.MouseMove, -10))
    home.mouseMoveEvent(ev(QEvent.Type.MouseMove, -60))
    home.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, -60))
    assert started and home.x() == x0 - 60 and moved == [home.offset()]
    assert home.offset() == default_offset(g.width()) + 60


def test_set_offset_slides_the_strip_and_its_spots(qapp, baked):
    sp, home, scr = _setup(qapp, baked, side="right", offset=50)
    assert home.offset() == 50
    bed0 = home.spots["bed"].pos
    home.set_offset(130)
    assert home.offset() == 130 and home.spots["bed"].pos == bed0 - QPoint(80, 0)
    home.set_offset(10 ** 6)
    assert home.offset() == home.max_offset() and home.x() == scr.geometry().left()


def test_an_idle_cat_animates_but_does_not_redraw_or_glide_needlessly(qapp, baked):
    """A sleeping cat changes frame 2.5 times a second: it must keep doing that
    (a stuck tick once froze it), repaint only then, and leave the 60 fps
    glide timer off while it isn't moving."""
    from companion.creatures import qt as cq
    from companion.sprite import CatSprite
    sp = CatSprite()
    sp.set_sheet(cq.sheet_from_baked(baked[1]), {})
    sp.place_start()
    sp.show()
    sp.set_wander(False)
    sp.state, sp._next_decision = "sleep", 10 ** 9
    shown, repaints = set(), 0
    orig = sp.update

    def counted():
        nonlocal repaints
        repaints += 1
        orig()
    sp.update = counted
    for _ in range(60):                       # ~4 s of ticks
        sp._tick()
        shown.add(sp._shown())
    assert len(shown) > 3                      # it animates
    assert repaints < 30                       # but doesn't redraw every tick
    assert not sp._glide_timer.isActive()      # nothing to glide
    sp.move(sp.x() + 40, sp.y())
    assert sp._glide_timer.isActive()          # a move glides...
    for _ in range(40):
        sp._glide()
        if not sp._glide_timer.isActive():
            break


def test_the_corner_can_be_arranged_in_any_order(qapp, baked):
    from companion.arrange import ArrangeDialog
    from companion.things.layout import order_of
    sp, home, scr = _setup(qapp, baked, side="left")
    xs = lambda: {k: s.pos.x() for k, s in home.spots.items()}      # noqa: E731
    before = xs()
    assert before["bed"] < before["post"] < before["bowl"] < before["basket"]
    genome = baked[0]
    saved = []

    def apply(order):
        saved.append(order)
        cfg = {"home": {"placed": dict(ALL), "side": "left", "offset": 0, "order": order}}
        home.build(genome, cfg, sp.pixel_scale(), sp.floor_line(scr), scr)
    dlg = ArrangeDialog(home, "left", order_of(None), apply)
    assert dlg.order() == ["bed", "post", "bowl", "basket"]
    item = dlg.list.takeItem(0)                       # the bed to the far end
    dlg.list.addItem(item)
    dlg._changed()
    assert saved[-1] == ["post", "bowl", "basket", "bed"]
    after = xs()
    assert after["post"] < after["bowl"] < after["basket"] < after["bed"]
    # the right-hand corner shows them mirrored, as they stand on screen
    sp2, home2, _ = _setup(qapp, baked, side="right")
    dlg2 = ArrangeDialog(home2, "right", ["bowl", "bed", "post", "basket"], lambda o: None)
    names = [dlg2.list.item(i).data(0x0100) for i in range(dlg2.list.count())]
    assert names == ["basket", "post", "bed", "bowl"] and dlg2.order() == ["bowl", "bed", "post", "basket"]
    dlg._reset()
    assert saved[-1] is None and dlg.order() == ["bed", "post", "bowl", "basket"]


@pytest.mark.parametrize("bowl,contents", [("bowl.blue", "food"), ("bowl.steel_water", "water")])
def test_eating_at_the_bowl_flicks_crumbs_or_splashes(qapp, baked, bowl, contents):
    sp, home, scr = _setup(qapp, baked, placed={**ALL, "bowl": bowl})
    sp.move(scr.availableGeometry().center().x(), sp._floor_y())
    sp._sync_fpos()
    bites = []
    sp.bite.connect(lambda kind, x, y: bites.append((kind, x, y)))
    assert sp.go_use("bowl", 4.0)
    assert _run_until(sp, lambda: len(bites) >= 2, 900)      # a bite per bob of the head
    assert {k for k, _x, _y in bites} == {contents}
    _k, x, y = bites[0]
    m = sp.mouth_global()
    assert abs(x - m.x()) < 40 * sp.pixel_scale() and abs(y - m.y()) < 40 * sp.pixel_scale()


def test_the_crumbs_and_droplets_fall_and_go(qapp, monkeypatch):
    import companion.playground as PG

    class Clock:
        t = 50.0

        @staticmethod
        def monotonic():
            return Clock.t
    monkeypatch.setattr(PG, "time", Clock)
    PG.splash(400, 300, 3, "water")
    s = next(p for p in PG._PUFFS if isinstance(p, PG.Splash))
    assert 5 <= len(s._bits) <= 7
    y0 = [b[1] for b in s._bits]
    for _ in range(20):
        Clock.t += 0.016
        s._step()
    assert max(b[1] for b in s._bits) > min(y0)                # they come back down
    Clock.t += PG.Splash.LIFE
    s._step()
    assert s not in PG._PUFFS                                  # and go
    PG.splash(400, 300, 3, "empty")                            # an empty bowl: nothing
    assert not any(isinstance(p, PG.Splash) for p in PG._PUFFS)


def test_clicking_the_toy_basket_starts_play():
    from types import SimpleNamespace
    from companion.app import Companion
    calls = []
    fake = SimpleNamespace(
        focus=SimpleNamespace(active=lambda: False, phase="idle"),
        sprite=SimpleNamespace(can_play=lambda: True, go_use=lambda *a: calls.append(("use", a))),
        _fetch_from_basket=lambda: calls.append("fetch"))
    Companion._home_clicked(fake, "basket")
    assert calls == ["fetch"]
    Companion._home_clicked(fake, "bowl")
    assert calls[-1][0] == "use"
