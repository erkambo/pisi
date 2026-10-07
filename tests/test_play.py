"""Playing: toys on the floor, the laser and the wind-up mouse (headless Qt,
on a simulated clock)."""
import collections
import math

import pytest
from PyQt6.QtCore import QPoint

from companion.creatures import api, panel
from companion.things import catalog, fit as F
from companion.things.kinds import KINDS
import companion.playtime as PTM


class Clock:
    t = 1000.0

    @staticmethod
    def monotonic():
        return Clock.t


@pytest.fixture(scope="module")
def cat():
    g = [v for k, v in panel.panel(("owners",)) if k != "canon"][0]
    pet = api.Creature(g)
    return g, pet, pet.bake(), F.measure(pet)


SEED = int(__import__("os").environ.get("PLAY_SEED", "7"))


@pytest.fixture
def play(qapp, cat, monkeypatch):
    import random
    random.seed(SEED)
    from companion.creatures import qt as cq
    from companion.sprite import CatSprite
    monkeypatch.setattr(PTM, "time", Clock)
    import companion.playground as PG
    monkeypatch.setattr(PG, "time", Clock)
    _g, _pet, baked, ft = cat
    sp = CatSprite()
    sp.set_sheet(cq.sheet_from_baked(baked), {})
    sp.place_start()
    sp.show()
    pt = PTM.PlayTime(sp, lambda: ft, lambda i: KINDS["toy"].render(catalog.BY_ID[i].design, ft))
    yield sp, pt
    pt.stop(quiet=True)


def run(sp, pt, n, watch=None):
    seen = collections.Counter()
    for _ in range(n):
        for _sub in range(4):                 # toys move at ~60 fps
            Clock.t += 0.0175
            if pt.toy:
                pt.toy._step()
        sp._tick()
        pt._tick()
        seen[sp._shown()[0]] += 1
        seen["plan:" + str(pt._plan)] += 1
        if watch:
            watch()
    return seen


def test_a_thrown_toy_gets_chased_batted_and_pounced(play):
    sp, pt = play
    assert pt.start_toy("toy.yarn_red")
    pt.toy.vx, pt.toy.vy = 730.0, -330.0
    pt._thrown()
    floor = sp._floor_y()

    def grounded():                      # it never flies after the toy
        if sp.state not in ("hop", "fall"):
            assert sp.y() == floor
    seen = run(sp, pt, 900, grounded)
    for _ in range(3):                    # a few more throws: it catches some, misses some
        pt.toy.vx, pt.toy.vy = -600.0 if pt.toy.center_x() > sp.x() else 600.0, -260.0
        pt._thrown()
        seen.update(run(sp, pt, 700, grounded))
    assert seen["bat"] and seen["pounce"], seen
    assert pt.catches >= 1


def test_left_alone_it_brings_the_toy_to_you(play):
    sp, pt = play
    notes = []
    pt.note.connect(notes.append)
    assert pt.start_toy("toy.mouse")
    seen = run(sp, pt, 1600)
    assert seen["pickup"] and seen["carrywalk"] and seen["drop"], seen
    assert "dropped" in notes


def test_the_wind_up_mouse_gets_caught(play):
    sp, pt = play
    ended = []
    pt.ended.connect(ended.append)
    assert pt.start_hunt()
    run(sp, pt, 2500)
    assert pt.catches >= 1


def test_tidying_puts_the_toy_back(play):
    sp, pt = play
    ended, put = [], []
    pt.ended.connect(ended.append)
    assert pt.start_toy("toy.mouse")
    run(sp, pt, 30)
    pt.tidy(lambda: put.append(sp.carrying()) or True)
    run(sp, pt, 1500)
    assert ended == ["tidied"] and put and put[0] is not None
    assert pt.toy is None and not pt.active()
    # and play is really over: no energy pips left hanging, out of play mode
    assert not sp._meter_on and not sp.meter_shown()       # faded out by now
    assert not sp.in_play and not sp.tired


def test_the_laser_is_chased_on_the_floor_and_jumped_for_above(play, monkeypatch):
    sp, pt = play
    assert pt.start_laser()
    scr = sp.screen()
    floor = sp.floor_line(scr)
    spot = [QPoint(sp.x() + 500, floor - 10)]
    monkeypatch.setattr(PTM.QCursor, "pos", staticmethod(lambda: spot[0]))
    x0 = sp.x()
    seen = run(sp, pt, 200)
    assert sp.x() > x0 + 200 and (seen["run"] or seen["walk"])
    from companion.sprite import W
    spot[0] = QPoint(int(sp.x() + W / 2), floor - int(sp._body().stand * 1.5))
    seen = run(sp, pt, 400)
    assert seen["jump"], seen


def test_break_routine_from_the_basket_and_back(play, cat, qapp):
    """Out of bed, a toy from the basket, carried over and dropped by you;
    at the end of the break, back into the basket."""
    from companion.home import HomeCorner
    sp, pt = play
    g, _pet, _baked, ft = cat
    home = HomeCorner()
    scr = qapp.primaryScreen()
    assert home.build(g, {"home": {"offset": 0}}, sp.pixel_scale(), sp.floor_line(scr), scr)
    sp.home = lambda k: home.spots.get(k)
    toy = KINDS["toy"].render(catalog.BY_ID["toy.mouse"].design, ft)
    assert sp.go_use("basket", 0.95)
    sp.on_frame("pickup", 5, lambda: sp.carry(toy, sp.pixel_scale()))
    for _ in range(2500):                     # to the basket, the bite, back up
        Clock.t += 0.07
        sp._tick()
        if sp.using() is None and sp.state not in ("hop", "fall"):
            break
    assert sp.carrying() is toy
    notes = []
    pt.note.connect(notes.append)
    assert pt.start_toy("toy.mouse", carried=True)
    run(sp, pt, 800)
    assert "dropped" in notes                 # brought over and put down by you
    # break over: tidy up
    put = []

    def to_basket():
        ok = sp.go_use("basket", 1.0, anim="drop")
        if ok:
            sp.on_frame("drop", 4, sp.let_go)
            put.append(1)
        return ok
    pt.tidy(to_basket)
    run(sp, pt, 1500)
    for _ in range(600):
        Clock.t += 0.07
        sp._tick()
    assert put and sp.carrying() is None and not pt.active()



def _session(sp, pt, ft, energy, n=2600):
    import dataclasses
    pt.fit_fn = lambda: dataclasses.replace(ft, energy=energy)
    assert pt.start_toy("toy.yarn_red")
    seen = collections.Counter()
    for k in range(n):
        if k % 260 == 0 and pt.toy is not None and pt.toy.resting():   # throw it now and then
            pt.toy.vx = (480.0 if pt.toy.center_x() < sp.x() + 300 else -480.0)
            pt.toy.vy = -200.0
            pt._thrown()
        seen.update(run(sp, pt, 1))
    return seen


def test_personality_lively_cats_pounce_more_lazy_ones_rest(play, cat):
    sp, pt = play
    ft = cat[3]
    rest = ("watch", "watchup", "sit", "sleep", "crouch", "pant")
    totals = {}
    for energy in (1.0, 0.0):
        seen, pounces, misses = collections.Counter(), 0, 0
        for _ in range(3):
            seen.update(_session(sp, pt, ft, energy))
            pounces, misses = pounces + pt.pounces, misses + pt.misses
            pt.stop(quiet=True)
        totals[energy] = (seen, pounces, misses)
    (lively, lp, lm), (lazy, zp, zm) = totals[1.0], totals[0.0]
    assert lp > zp                                   # lively cats pounce more
    assert sum(lazy[a] for a in rest) > sum(lively[a] for a in rest)   # lazy cats lounge
    assert lm + zm >= 1                              # it doesn't always land it


def test_stamina_carries_over_and_refills_between_plays(play):
    import companion.playtime as PT
    sp, pt = play
    assert pt.start_toy("toy.mouse") and pt.stamina == 1.0      # a fresh cat: full
    for _ in range(10):
        pt._spend("pounce")
    tired = pt.stamina
    pt.stop(quiet=True)
    assert pt.start_toy("toy.mouse") and pt.stamina == pytest.approx(tired)   # straight back: still tired
    pt.stop(quiet=True)
    Clock.t += PT.REFILL_S / 2
    assert pt.start_toy("toy.mouse") and tired < pt.stamina < 1.0           # half rested
    pt.stop(quiet=True)
    Clock.t += 25 * 60                                                       # a focus block's nap
    assert pt.start_toy("toy.mouse") and pt.stamina == 1.0


def test_stamina_drains_with_play_and_comes_back_resting(play):
    sp, pt = play
    assert pt.start_toy("toy.mouse")
    start = pt.stamina
    for _ in range(4):
        pt._spend("pounce")
    assert pt.stamina < start
    low = pt.stamina
    sp.state = "sit"
    pt._plan = "watch"
    pt._plan_until = Clock.t + 100
    run(sp, pt, 200)
    assert pt.stamina > low


@pytest.fixture
def hand(monkeypatch):
    """A cursor the test moves (the wand is held at it)."""
    import companion.playground as PG
    pos = [QPoint(400, 300)]
    monkeypatch.setattr(PG.QCursor, "pos", staticmethod(lambda: pos[0]))
    monkeypatch.setattr(PTM.QCursor, "pos", staticmethod(lambda: pos[0]))
    return pos


def _wand_steps(pt, n):
    for _ in range(n):
        Clock.t += 1 / 60
        pt.wand._step()


def test_the_wand_string_keeps_its_length_hangs_and_swings(play, hand):
    import math
    sp, pt = play
    assert pt.start_wand()
    w = pt.wand
    w.floor_y = 10 ** 6                       # high up: nothing to drag on
    _wand_steps(pt, 300)
    for a, b in zip(w.pts, w.pts[1:]):        # the string doesn't stretch
        assert abs(math.dist(a, b) - w.seg) < 1.0
    tip = w.tip()
    assert abs(w.feather().x() - tip.x()) < 4 and w.feather().y() > tip.y()   # hangs straight down
    for _ in range(10):                       # sweep the hand across (~1800 px/s)
        hand[0] = QPoint(hand[0].x() + 30, hand[0].y())
        _wand_steps(pt, 1)
    assert w.feather().x() < w.tip().x() - 10                 # the feather trails behind
    before = w.feather()
    w.swat(800.0, -600.0)
    _wand_steps(pt, 5)
    assert w.feather().x() > before.x() + 5                   # knocked away


def test_the_cat_plays_with_the_wand_on_the_floor_and_jumps_for_it(play, hand):
    sp, pt = play
    assert pt.start_wand()
    scr = sp.screen()
    floor = sp.floor_line(scr)
    seen = collections.Counter()
    floor_y = sp._floor_y()

    def grounded():
        if sp.state not in ("hop", "fall"):
            assert sp.y() == floor_y
    # drag the feather back and forth along the floor
    for k in range(900):
        x = sp.x() + 250 + 180 * math.sin(k / 40.0)
        hand[0] = QPoint(int(x), floor - int(pt.wand.SEGMENTS * pt.wand.seg) + 20)
        _wand_steps(pt, 4)
        seen.update(run(sp, pt, 1, grounded))
    assert seen["bat"] or seen["pounce"], seen
    # dangle it just above the cat, within a leap
    from companion.sprite import W
    for k in range(900):
        hand[0] = QPoint(int(sp.x() + W / 2) - pt.wand.rod[0],
                         floor - int(sp._body().stand * 1.6) - int(pt.wand.SEGMENTS * pt.wand.seg))
        _wand_steps(pt, 4)
        seen.update(run(sp, pt, 1, grounded))
    assert seen["jump"], seen
    assert pt.catches >= 1


def _ticks(sp, pt, n):
    for _ in range(n):
        Clock.t += 0.07
        sp._tick()
        pt._tick()


def test_the_energy_meter_fades_in_follows_stamina_and_fades_out(play):
    sp, pt = play
    assert pt.start_toy("toy.mouse")
    _ticks(sp, pt, 12)
    assert sp.meter_shown() and sp._meter_alpha == 1.0
    assert abs(sp._meter - pt.stamina) < 0.02         # (a tick behind at most)
    before = sp._meter_sig()
    pt.stamina = 0.2
    _ticks(sp, pt, 1)
    assert sp._meter_sig() != before                 # it drops as the cat tires (and repaints)
    pt.stop(quiet=True)
    _ticks(sp, pt, 2)
    assert sp.meter_shown() and sp._meter_alpha < 1.0   # fading, not popping
    _ticks(sp, pt, 12)
    assert not sp.meter_shown() and not sp.tired


def test_the_meter_can_be_turned_off(play):
    sp, pt = play
    pt.show_meter = False
    assert pt.start_toy("toy.mouse")
    _ticks(sp, pt, 12)
    assert not sp.meter_shown()


def test_the_meter_draws_blue_pips_above_the_cat(play):
    from PyQt6.QtGui import QImage, QPainter, QColor
    from companion.sprite import W, H
    sp, pt = play
    assert pt.start_toy("toy.mouse")
    pt.stamina = 0.5
    _ticks(sp, pt, 12)
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    sp._draw_meter(p)
    p.end()
    blue = [(x, y) for y in range(H) for x in range(W)
            if (c := img.pixelColor(x, y)).alpha() > 200 and c.blue() > 200 and c.red() < 120]
    dim = [(x, y) for y in range(H) for x in range(W)
           if 40 < img.pixelColor(x, y).alpha() < 140]
    assert blue and dim                              # half full: lit pips and empty ones
    x, y, _w, _h = sp._sprite_box()
    an = sp.sheet.anchor("sit", 0, sp.facing)
    head = y + an["head_top"][1] * sp.pixel_scale()
    assert max(py for _x, py in blue) < head         # above the head


def test_a_tired_cat_trudges_and_barely_wiggles(play):
    sp, pt = play
    assert pt.start_toy("toy.mouse", at_x=sp.x() + 900)
    pt.stamina = 0.25
    _ticks(sp, pt, 1)
    sp.state, sp.gait = "walk", "walk"
    sp._advance_anim()
    assert sp.tired and sp._display_anim() == "trudge"
    PTM.random.seed(1)
    pt._stalk_then_pounce(sp.x() + 50)
    tired_wiggle = pt._plan_until - Clock.t
    pt.stamina = 1.0
    PTM.random.seed(1)
    pt._stalk_then_pounce(sp.x() + 50)
    assert tired_wiggle < 0.6 * (pt._plan_until - Clock.t)


def test_spent_it_flops_and_pants_then_calls_it_a_day(play):
    sp, pt = play
    notes, ended = [], []
    pt.note.connect(notes.append)
    pt.ended.connect(ended.append)
    assert pt.start_toy("toy.mouse")
    _ticks(sp, pt, 5)
    pt.stamina = 0.05
    shown = set()
    for _ in range(40):
        _ticks(sp, pt, 1)
        shown.add(sp._trans or sp._shown()[0])
    assert sp.state == "pant" and {"flop", "pant"} <= shown, shown
    assert notes.count("tired") == 1
    low = pt.stamina
    _ticks(sp, pt, 60)
    assert pt.stamina > low                          # getting its breath back
    for _ in range(400):                             # worn out again and again
        if pt._plan != "breather":
            pt.stamina = 0.05
        _ticks(sp, pt, 1)
        if ended:
            break
        if pt._plan == "breather":
            pt._plan_until = Clock.t                 # (skip the rest of each breather)
    assert ended == ["worn out"] and not pt.active()
    assert notes.count("tired") == 1                 # one bubble, not one per breather
    _ticks(sp, pt, 30)
    assert sp.state != "pant" or sp._next_decision < 10 ** 6   # it doesn't lie there forever


def test_the_laser_tires_it_out_too(play, monkeypatch):
    sp, pt = play
    assert pt.start_laser()
    spot = [QPoint(sp.x() + 600, sp.floor_line(sp.screen()) - 10)]
    monkeypatch.setattr(PTM.QCursor, "pos", staticmethod(lambda: spot[0]))
    start = pt.stamina
    for k in range(400):                             # sweep it back and forth
        spot[0] = QPoint(int(sp.x() + (500 if k // 60 % 2 else -500)), spot[0].y())
        run(sp, pt, 1)
    assert pt.stamina < start or pt.breathers


class _Page:
    """A web page as the extension reports it: boxes of text."""
    def __init__(self, boxes):
        self.bxs, self.active, self.version = list(boxes), True, 0

    def boxes(self):
        return list(self.bxs)

    def view(self):
        return None

    def window(self):
        return None

    def metrics(self):
        return (0.0, 0.0)

    def take_scroll(self):
        return 0.0

    def going_on(self):
        return {}


def _column(sp, left, n_par=3):
    """Paragraphs stacked up the screen, the lowest a climb above the floor."""
    from companion.perch import Box
    floor = sp.floor_line(sp.screen())
    boxes, y = [], floor - 6
    for b in range(n_par):
        lines = [Box(left, y - (3 - i) * 22, left + 380, y - (3 - i) * 22 + 14, "p", n_par - b)
                 for i in range(3)]
        boxes = lines + boxes
        y = lines[0].y0 - 20
    return boxes


class _NoGliding:
    """Down off the page the way a cat goes: down the side of the text, or a
    step off the end and a drop; never a long glide through the text."""
    def __init__(self, sp):
        self.sp, self.air_x, self.worst = sp, None, 0.0

    def __call__(self):
        sp = self.sp
        if sp.state in ("hop", "fall"):
            self.air_x = sp.x() if self.air_x is None else self.air_x
            self.worst = max(self.worst, abs(sp.x() - self.air_x))
        else:
            self.air_x = None

    def check(self):
        assert self.worst <= self.sp._body().w * 1.3, self.worst


def test_the_laser_up_on_the_page_gets_climbed_for(play, monkeypatch):
    """A dot held up on the text: the cat climbs the page after it, ledge by
    ledge, and plays with it up there; down on the floor again, it comes down."""
    sp, pt = play
    from companion.sprite import W
    r = sp._screen_rect()
    boxes = _column(sp, r.left() + 200)
    sp.surfaces = _Page(boxes)
    sp.move(r.left() + 640 - W // 2, sp._floor_y())
    sp._sync_fpos()
    assert pt.start_laser()
    pt.stamina = 1.0
    pt.fit_fn = lambda: pt.fit
    top = min(b.y0 for b in boxes)
    spot = [QPoint(r.left() + 420, int(top - sp._body().stand * 0.8))]
    monkeypatch.setattr(PTM.QCursor, "pos", staticmethod(lambda: spot[0]))
    seen, best = collections.Counter(), 10 ** 9
    for _ in range(3000):
        pt.stamina = max(pt.stamina, 0.8)            # (not testing tiredness here)
        seen.update(run(sp, pt, 1))
        if sp.ledge() is not None:
            best = min(best, sp.ledge().y)
        if sp.ledge() is not None and abs(sp.ledge().y - (top + 2)) < 6 and not sp.busy():
            break
    assert pt.trips >= 1, (pt.trips, seen)
    assert sp.ledge() is not None and abs(sp.ledge().y - top) < 8, (best, top)
    assert seen["climb"] and seen["pullup"], seen
    # it plays up there: right under the dot, it jumps for it
    spot[0] = QPoint(int(sp.x() + W / 2), int(sp.ground_line() - sp._body().stand * 1.4))
    up_there = sp.y()

    def stays_up():                                  # it never falls off doing it
        pt.stamina = max(pt.stamina, 0.8)
        assert sp.y() <= up_there + 2
    seen = run(sp, pt, 600, stays_up)
    assert seen["jump"], seen
    # the dot goes down to the floor: so does the cat
    spot[0] = QPoint(r.left() + 120, sp.floor_line(sp.screen()) - 6)
    log = []
    glide = _NoGliding(sp)
    for _ in range(3000):
        pt.stamina = max(pt.stamina, 0.8)
        run(sp, pt, 1, glide)
        log.append((sp.state, pt._plan, pt.trips, sp.y(), sp._perched))
        if not sp._perched and sp.state not in ("hop", "fall", "climb") and sp.y() == sp._floor_y():
            break
    assert not sp._perched and sp.y() == sp._floor_y(), sorted(set(log))[:30]
    glide.check()


def test_a_flick_across_the_page_is_not_worth_a_climb(play, monkeypatch):
    sp, pt = play
    from companion.sprite import W
    r = sp._screen_rect()
    boxes = _column(sp, r.left() + 200)
    sp.surfaces = _Page(boxes)
    sp.move(r.left() + 640 - W // 2, sp._floor_y())
    sp._sync_fpos()
    assert pt.start_laser()
    top = min(b.y0 for b in boxes)
    def wiggle():                                    # flicked back and forth, 3 times a second
        return QPoint(r.left() + 220 + (0 if int(Clock.t * 6) % 2 else 300), int(top - 40))
    monkeypatch.setattr(PTM.QCursor, "pos", staticmethod(wiggle))
    run(sp, pt, 300)
    assert pt.trips == 0 and not sp._perched


def test_too_tired_to_climb_it_watches_from_below(play, monkeypatch):
    sp, pt = play
    from companion.sprite import W
    r = sp._screen_rect()
    boxes = _column(sp, r.left() + 200)
    sp.surfaces = _Page(boxes)
    sp.move(r.left() + 640 - W // 2, sp._floor_y())
    sp._sync_fpos()
    assert pt.start_laser()
    top = min(b.y0 for b in boxes)
    monkeypatch.setattr(PTM.QCursor, "pos", staticmethod(lambda: QPoint(r.left() + 420, int(top - 40))))
    for _ in range(200):
        pt.stamina = 0.2
        run(sp, pt, 1)
    assert pt.trips == 0 and not sp._perched


def _toy_steps(toy, n):
    for _ in range(n):
        Clock.t += 1 / 60
        toy._step()


def test_a_toy_lands_on_a_line_of_text_rides_the_scroll_and_rolls_off(play):
    sp, pt = play
    assert pt.start_toy("toy.yarn_red")
    toy = pt.toy
    floor = toy.floor_y
    line = [(300.0, 500.0, float(floor - 300), "k")]
    toy.ledges_fn = lambda: list(line)
    toy.place(400, floor, toy.bounds)
    toy.y_f, toy.vx, toy.vy = floor - 600.0, 0.0, 0.0      # dropped from above the line
    _toy_steps(toy, 120)
    assert toy.ledge is not None and toy.on_floor() and abs(toy.y_f + toy.th - (floor - 300)) < 1
    line[0] = (300.0, 500.0, float(floor - 340), "k")      # the page scrolls 40 px up
    _toy_steps(toy, 2)
    assert abs(toy.y_f + toy.th - (floor - 340)) < 1
    toy.hit(300.0)                                        # batted: rolls off the end
    _toy_steps(toy, 240)
    assert toy.ledge is None and toy.on_floor() and abs(toy.y_f + toy.th - floor) < 1
    toy.place(400, floor, toy.bounds)                     # thrown up through it from below
    toy.vy = -1100.0
    _toy_steps(toy, 4)
    assert toy.ledge is None


def _toy_on_top(sp, pt, boxes, x):
    top = min(boxes, key=lambda b: b.y0)
    line = next(ln for ln in pt._toy_ledges() if ln[3][:2] == (top.x0, top.x1) and abs(ln[2] - top.edge) < 1)
    pt.toy.place(x, pt.toy.floor_y, pt.toy.bounds, line)
    pt._thrown()
    return line


def test_a_toy_thrown_up_on_the_page_gets_fetched_from_up_there(play):
    sp, pt = play
    from companion.sprite import W
    r = sp._screen_rect()
    boxes = _column(sp, r.left() + 200)
    sp.surfaces = _Page(boxes)
    sp.move(r.left() + 640 - W // 2, sp._floor_y())
    sp._sync_fpos()
    assert pt.start_toy("toy.yarn_red")
    line = _toy_on_top(sp, pt, boxes, r.left() + 420)
    seen = collections.Counter()
    up = False
    for _ in range(3000):
        pt.stamina = max(pt.stamina, 0.8)
        seen.update(run(sp, pt, 1))
        if sp.ledge() is not None and abs(sp.ground_line() - line[2]) <= 4:
            up = True
        if up and (seen["bat"] or seen["pounce"] or seen["pickup"]) and not sp.busy():
            break
    assert up and pt.trips >= 1, (pt.trips, seen)
    assert seen["bat"] or seen["pounce"] or seen["pickup"], seen
    # it goes back down the page after it once it's down on the floor
    if sp.carrying() is None:
        pt.toy.place(r.left() + 120, pt.toy.floor_y, pt.toy.bounds)
        pt._thrown()
    glide = _NoGliding(sp)
    for _ in range(3000):
        pt.stamina = max(pt.stamina, 0.8)
        run(sp, pt, 1, glide)
        if not sp._perched and sp.y() == sp._floor_y() and not sp.busy():
            break
    assert not sp._perched and sp.y() == sp._floor_y()
    glide.check()


def test_a_toy_out_of_reach_gets_watched_not_flown_to(play):
    from companion.perch import Box
    sp, pt = play
    from companion.sprite import W
    r = sp._screen_rect()
    floor = sp.floor_line(sp.screen())
    shelf = Box(r.left() + 300, floor - 520, r.left() + 420, floor - 500, "img", 0)   # high and alone
    sp.surfaces = _Page([shelf])
    sp.move(r.left() + 360 - W // 2, sp._floor_y())
    sp._sync_fpos()
    notes = []
    pt.note.connect(notes.append)
    assert pt.start_toy("toy.yarn_red")
    _toy_on_top(sp, pt, [shelf], r.left() + 360)
    seen = run(sp, pt, 300, lambda: setattr(pt, "stamina", max(pt.stamina, 0.8)))
    assert "out of reach" in notes and seen["watchup"]
    assert not sp._perched and sp.y() == sp._floor_y()


def test_dust_survives_a_clock_that_jumps(qapp, monkeypatch):
    """A puff made on one clock and stepped on another (a resume from sleep,
    or a test's fake clock) used to overflow (0.02 ** big negative)."""
    import companion.playground as PG
    d = PG.Dust(100, 500, 3)
    d._last = d._born = time_now = 10 ** 6                 # "made" far in the future
    d._step()                                              # must not raise
    assert not d.isVisible() and d not in PG._PUFFS
    _ = time_now


def test_every_toy_has_its_own_feel(qapp, cat, monkeypatch):
    """Each toy style slides or rolls its own way; the spring bounces the most."""
    import companion.playground as PG
    from companion.things import catalog
    from companion.things.kinds import KINDS
    for style in KINDS["toy"].STYLES:
        assert style in PG.FRICTION, style
    ft = cat[3]

    class Clock:
        t = 100.0

        @staticmethod
        def monotonic():
            return Clock.t
    monkeypatch.setattr(PG, "time", Clock)

    def peak_after_bounce(item_id):
        it = catalog.BY_ID[item_id]
        toy = PG.FloorToy(KINDS["toy"].render(it.design, ft), 3)
        toy.place(500, 900, (0, 2000))
        toy.y_f, toy.vy, toy._last = 300.0, 0.0, Clock.t
        landed, top = False, 9e9
        for _ in range(400):
            Clock.t += 0.016
            toy._step()
            if toy.on_floor():
                landed = True
            elif landed:
                top = min(top, toy.y_f)
        toy.stop()
        toy.deleteLater()
        return toy.ground_y() - toy.th - top             # how high it came back up
    spring, mouse = peak_after_bounce("toy.spring"), peak_after_bounce("toy.mouse")
    assert mouse > 20 and spring > 1.8 * mouse, (spring, mouse)


@pytest.mark.parametrize("item_id", ["toy.crinkle", "toy.fish", "toy.bee", "toy.spring"])
def test_every_kind_of_toy_gets_chased_and_caught(play, item_id):
    sp, pt = play
    assert pt.start_toy(item_id)
    seen = collections.Counter()
    for k in range(4):
        pt.toy.vx = (-1 if pt.toy.center_x() > sp.x() else 1) * (650.0 - 60 * k)
        pt.toy.vy = -300.0
        pt._thrown()
        seen.update(run(sp, pt, 700))
    assert seen["bat"] or seen["pounce"], seen
    assert pt.catches >= 1, (item_id, seen)
