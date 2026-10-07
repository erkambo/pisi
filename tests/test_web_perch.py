"""The pet walking on web pages: the browser extension's geometry, the
surface model, the pet's leap/ride/fall physics, the native-messaging bridge
and its installer. No real browser is started."""
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from companion import bridge, perch
from PyQt6.QtCore import QPoint

from companion.perch import Box, Seg, WebSurfaces

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"


# ---- the extension -----------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("suite", ["lines.test.mjs", "badge.test.mjs"])
def test_extension_unit_tests(suite):
    r = subprocess.run(["node", "--test", str(EXT / "test" / suite)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]


def test_extension_manifest_asks_for_as_little_as_possible():
    m = json.loads((EXT / "manifest.json").read_text())
    assert m["manifest_version"] == 3
    # on by default on web pages — and nothing more: no history, cookies,
    # downloads, request interception or browser pages
    assert set(m["host_permissions"]) == {"http://*/*", "https://*/*"}
    # (contextMenus: "Throw PISI a toy here" on right-click; no install warning)
    assert set(m["permissions"]) == {"nativeMessaging", "storage", "scripting", "activeTab",
                                     "contextMenus"}
    (cs,) = m["content_scripts"]
    assert set(cs["matches"]) == {"http://*/*", "https://*/*"}
    # sensitive sites are skipped out of the box
    ex = " ".join(cs["exclude_matches"])
    for site in ("mail.google.com", "paypal.com", "bitwarden.com", "1password.com",
                 "login.microsoftonline.com", "accounts.google.com"):
        assert site in ex, site
    # the ids the native host trusts are the ids this manifest produces
    der = base64.b64decode(m["key"])
    cid = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(der).hexdigest()[:32])
    assert cid == bridge.CHROME_EXTENSION_ID
    assert m["browser_specific_settings"]["gecko"]["id"] == bridge.FIREFOX_EXTENSION_ID
    # every file it points at ships
    files = [m["background"]["service_worker"], *m["background"]["scripts"],
             m["action"]["default_popup"], *m["icons"].values()]
    for f in files:
        assert (EXT / f).exists(), f
    for f in ("lines.js", "content.js", "popup.js", "popup.css",
              "welcome.html", "welcome.js", "welcome.css"):
        assert (EXT / f).exists(), f


def test_content_script_never_sends_page_text_or_address():
    src = (EXT / "content.js").read_text() + (EXT / "background.js").read_text()
    for leak in ("location.href", "document.URL", "textContent", "innerText",
                 "document.title", "fetch(", "XMLHttpRequest", "WebSocket"):
        assert leak not in src, leak


def test_content_script_steps_off_secret_pages_and_respects_off_switches():
    src = (EXT / "content.js").read_text()
    assert 'input[type="password"]' in src and 'autocomplete^="cc-"' in src
    assert '"off", "paused"' in src or "'off', 'paused'" in src


# ---- the surface model --------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _lines(lines, focused=True, sy=0, tab=1, conn=7):
    return {"type": "lines", "conn": conn, "tab": tab, "focused": focused,
            "scroll": [0, sy], "lines": lines}


def test_surfaces_follow_the_focused_tab_and_go_stale():
    clock = Clock()
    s = WebSurfaces(clock)
    assert not s.active and s.segments() == []
    s.feed(_lines([[100, 300, 400, 20]]))
    (seg,) = s.segments()
    assert (seg.x0, seg.x1) == (100, 500) and 300 <= seg.y <= 304
    s.feed(_lines([[0, 50, 200, 20]], focused=False, tab=2))   # a background tab
    assert s.segments() == [seg]
    clock.t += perch.STALE_S + 0.1                              # the page went quiet
    assert not s.active


def test_unfocused_page_is_dropped_after_a_grace_period():
    clock = Clock()
    s = WebSurfaces(clock)
    s.feed(_lines([[100, 300, 400, 20]]))
    clock.t += 1.0
    s.feed(_lines([[100, 300, 400, 20]], focused=False))       # you clicked elsewhere
    assert s.active
    clock.t += perch.FOCUS_GRACE_S + perch.HEARTBEAT_S
    s.feed(_lines([[100, 300, 400, 20]], focused=False))
    assert not s.active


def test_scrolling_is_reported_as_text_movement():
    s = WebSurfaces(Clock())
    s.feed(_lines([[100, 300, 400, 20]], sy=0))
    s.feed(_lines([[100, 260, 400, 20]], sy=40))                # scrolled down 40
    assert s.take_scroll() == -40
    assert s.take_scroll() == 0


def test_a_page_you_switched_away_from_stays_while_its_in_view():
    clock = Clock()
    s = WebSurfaces(clock)
    s.feed(_lines([[100, 300, 400, 20]]))
    clock.t += perch.FOCUS_GRACE_S + 5
    s.feed(_lines([[100, 300, 400, 20]], focused=False))
    assert not s.active                          # nobody checked: the grace ran out
    s.set_covered(False)                         # the screen check: still there to be seen
    assert s.active
    s.set_covered(True)                          # now another window covers it
    assert not s.active
    s.feed(_lines([[100, 300, 400, 20]]))        # back to it
    assert s.active


def test_gone_and_host_gone_clear_lines():
    s = WebSurfaces(Clock())
    s.feed(_lines([[100, 300, 400, 20]]))
    s.feed({"type": "gone", "conn": 7, "tab": 1})
    assert not s.active
    s.feed(_lines([[100, 300, 400, 20]]))
    s.feed({"type": "host-gone", "conn": 7})
    assert not s.active


def test_physics_helpers():
    segs = [Seg(100, 500, 300), Seg(100, 500, 340), Seg(600, 900, 200)]
    assert perch.support(segs, 300, 302) == segs[0]
    assert perch.support(segs, 300, 320) is None
    assert perch.landing(segs, 300, 250, 330) == segs[0]        # first line it crosses
    assert perch.landing(segs, 550, 250, 400) is None          # between columns
    x, y = perch.hop_point(0, 300, 200, 200, 0.5)
    assert x == 100 and y < 200                                 # clears the higher end
    assert perch.hop_point(0, 300, 200, 200, 1.0) == (200, 200)
    assert perch.hop_point(0, 300, 200, 300, 0.5, lift=80)[1] == pytest.approx(220)


# ---- the pet -------------------------------------------------------------------------
class FakeSurfaces:
    """Stands in for perch.WebSurfaces: a page made of boxes."""
    def __init__(self, boxes, view=None, win=None, metrics=(0.0, 0.0)):
        self.bxs = list(boxes)
        self.scroll = 0.0
        self.active = True
        self.version = 0
        self._view = view
        self._win = win
        self._metrics = metrics
        self.page, self.events, self.moves = {}, [], []
        self._active, self._zoom = ("c", 1), 1.0

    def set(self, boxes):
        self.bxs = list(boxes)
        self.version += 1

    def boxes(self):
        return list(self.bxs)

    def view(self):
        return self._view

    def window(self):
        return self._win

    def metrics(self):
        return self._metrics

    def take_scroll(self):
        dy, self.scroll = self.scroll, 0.0
        return dy

    # what's going on in the page (WebSurfaces.going_on and friends)
    def going_on(self):
        return dict(self.page)

    def take_events(self):
        ev, self.events = self.events, []
        return ev

    def scrolls(self, within):
        return [m for m in self.moves if m[0] <= within]

    def zoom(self):
        return self._zoom


def _text(x0, y, x1, h=20, block=0, kind="p"):
    return Box(x0, y, x1, y + h, kind, block)


@pytest.fixture
def pet(qapp):
    from companion.sprite import CatSprite
    p = CatSprite()
    p.timer.stop()
    p.place_start()
    landed = []
    p.landed.connect(lambda x, y: landed.append((x, y)))
    p._landed = landed
    yield p
    p.close()


def _run(pet, ticks=200, until=None):
    for _ in range(ticks):
        pet._tick()
        if until and until():
            return


def _settled(pet):
    return pet.state not in ("hop", "fall", "climb")


def _put(pet, x, feet):
    """Stand the pet with its middle at x and its feet at ``feet``."""
    from companion.sprite import W
    pet.move(int(round(x - W / 2)), int(round(feet - pet.foot_offset())))
    pet._perched = True
    pet._sync_fpos()


def test_pet_leaps_onto_a_line_and_says_where(pet, monkeypatch):
    """From the floor, up onto a line within a leap's reach."""
    from companion import sprite as S
    r = pet._screen_rect()
    line = _text(r.left() + 300, r.bottom() - 120, r.left() + 600)
    pet.surfaces = FakeSurfaces([line])
    monkeypatch.setattr(S.random, "random", lambda: 0.5)
    assert pet._web_move()
    _run(pet, until=lambda: pet.state == "hop")          # (a few steps to take off from)
    assert pet.state == "hop"
    _run(pet, until=lambda: _settled(pet))
    cx, feet = pet._feet()
    assert pet._perched and abs(feet - line.edge) <= 1 and line.x0 <= cx <= line.x1
    assert pet._landed == [(int(cx), int(feet))]


def test_pet_rides_the_scroll_then_falls_when_the_line_leaves(pet):
    r = pet._screen_rect()
    line = _text(r.left() + 100, r.bottom() - 260, r.left() + 700)
    fake = FakeSurfaces([line])
    pet.surfaces = fake
    _put(pet, line.x0 + 150, line.edge)
    # the page scrolls: the line moves up 40 px and the pet goes with it
    fake.scroll = -40
    fake.set([_text(line.x0, line.y0 - 40, line.x1)])
    pet._stay_on_surface()
    assert pet._perched and pet._feet()[1] == pytest.approx(line.edge - 40, abs=1)
    # the line scrolls off-screen: down it goes, onto the floor, no bump
    fake.set([])
    pet._stay_on_surface()
    assert pet.state == "fall"
    _run(pet, until=lambda: _settled(pet))
    assert not pet._perched and pet.y() == pet._floor_y()
    assert pet._landed == []


def test_scrolling_never_carries_the_pet_out_of_the_window(pet):
    """A long scroll takes the pet's line off the top of the page: the pet
    lets go at the window's edge instead of riding up and dropping from the
    top of the screen."""
    r = pet._screen_rect()
    view = (r.left() + 50, r.top() + 300, 800, 500)       # the page, on screen
    line = _text(r.left() + 100, view[1] + 200, r.left() + 700)
    fake = FakeSurfaces([line], view=view)
    pet.surfaces = fake
    _put(pet, line.x0 + 150, line.edge)
    fake.scroll = -400                                  # way past the top
    fake.set([_text(line.x0, line.y0 - 400, line.x1)])
    pet._stay_on_surface()
    _, feet = pet._feet()
    assert feet == pytest.approx(view[1] + pet._body().stand, abs=1)
    assert pet.state == "fall"                         # off its line, still in view


def test_dropped_pet_falls_onto_the_text_below(pet):
    r = pet._screen_rect()
    line = _text(r.left(), r.top() + 300, r.right())
    pet.surfaces = FakeSurfaces([line])
    pet.move(r.left() + 200, int(line.edge - pet.foot_offset() - 150))
    pet._dragging = True
    pet._pressed = True

    class Ev:
        def button(self):
            from PyQt6.QtCore import Qt
            return Qt.MouseButton.LeftButton
    pet.mouseReleaseEvent(Ev())
    assert pet.state == "fall"
    _run(pet, until=lambda: _settled(pet))
    assert pet._perched and pet._feet()[1] == pytest.approx(line.edge, abs=1)
    assert len(pet._landed) == 1


def test_pet_creeps_under_something_low(pet):
    r = pet._screen_rect()
    x0, y = r.left() + 100, r.top() + 300
    shelf = _text(x0, y, x0 + 700)
    # a line 82 px over the shelf's middle: under the pet's 92, over its 70
    low = _text(x0 + 300, y + 2 - 82 - 20, x0 + 500, block=1)
    pet.surfaces = FakeSurfaces([shelf, low])
    _put(pet, x0 + 60, shelf.edge)
    pet._walk_to(x0 + 640 - 85, "walk")
    creeping = []
    _run(pet, 800, until=lambda: creeping.append(pet._creep) or pet.state != "walk")
    assert pet._perched and pet._feet()[0] > x0 + 600
    assert True in creeping and creeping[0] is False and creeping[-1] is False


def test_a_procedural_pet_climbs_with_its_own_frames_and_pulls_itself_up(pet, monkeypatch):
    """Real climbing frames: paw over paw up the wall, then the pull-up, then
    standing on the ledge above (no turned walk cycle)."""
    from companion import pixelsheet
    from companion import sprite as S
    pet.set_sheet(pixelsheet.procedural_sheet(None), {})
    assert pet._climb_geo() is not None
    r = pet._screen_rect()
    body = pet._body()
    left, top = r.left() + 200, r.top() + 150
    line_h = body.stand * 0.3
    upper = [_text(left, top + i * line_h * 1.4, left + 300, h=line_h, block=0) for i in range(3)]
    y2 = upper[-1].y1 + body.stand * 0.85             # room to crouch; a gap it reaches across
    lower = [_text(left, y2 + i * line_h * 1.4, left + 300, h=line_h, block=1) for i in range(3)]
    pet.surfaces = FakeSurfaces(upper + lower)
    page = pet._page()
    here = perch.support(page.segs, lower[0].x0 + 120, lower[0].edge)
    target = perch.support(page.segs, upper[0].x0 + 120, upper[0].edge)
    assert here is not None and target is not None
    _put(pet, lower[0].x0 + 120, lower[0].edge)
    monkeypatch.setattr(S.random, "random", lambda: 0.9)     # no breather, no taskbar trip
    climbs = perch.climbs(page.segs, page.boxes, body, here, lower[0].x0 + 120)
    up = next(c for c in climbs if c.seg == target)
    mv = perch.Move("climb", up.x, up.seg, wall=up.wall_x, side=up.side, start=up.start_x,
                    edge=up.edge)
    pet._web_after = mv
    start, _ = pet._climb_plan(mv)
    _put(pet, start, lower[0].edge)
    pet._start_climb(mv)
    shown = set()
    for _ in range(2000):
        pet._tick()
        if pet.state == "climb":
            shown.add(pet._anim)
            assert pet._angle == 0                          # upright frames, not a turned walk
        if pet._perched:
            break
    assert {"climb", "pullup"} <= shown
    assert pet._perched and pet._feet()[1] == pytest.approx(upper[0].edge, abs=2)


def _two_paragraphs(left, top):
    """Two paragraphs, one above the other, in a column with a free left margin."""
    upper = [_text(left, top + i * 22, left + 500, h=14, block=0) for i in range(4)]
    lower = [_text(left, top + 160 + i * 22, left + 500, h=14, block=1) for i in range(3)]
    return upper, lower


def test_pet_climbs_the_side_of_the_text_to_the_shelf_above(pet, monkeypatch):
    from companion import sprite as S
    r = pet._screen_rect()
    upper, lower = _two_paragraphs(r.left() + 160, r.top() + 200)
    fake = FakeSurfaces(upper + lower)
    pet.surfaces = fake
    _put(pet, lower[0].x0 + 200, lower[0].edge)
    pet.facing = -1
    pet._mood = "climb"
    monkeypatch.setattr(S.random, "random", lambda: 0.5)     # never the taskbar trip
    angles = []
    for _ in range(3000):
        pet._next_decision = min(pet._next_decision, 3)
        pet._tick()
        angles.append(pet._angle)
        if pet._perched and abs(pet._feet()[1] - upper[0].edge) <= 1:
            break
    assert pet._perched and pet._feet()[1] == pytest.approx(upper[0].edge, abs=1)
    assert min(angles) <= -89 or max(angles) >= 89            # it was on the wall
    assert pet._angle == 0


def test_the_pet_is_never_split_across_two_monitors(pet, monkeypatch):
    """Qt's screens on a laptop + 4K monitor, both 2x: a gap between them."""
    from PyQt6.QtCore import QPoint, QRect
    from PyQt6.QtWidgets import QApplication
    from companion.sprite import W

    class Scr:
        def __init__(self, *r):
            self.r = QRect(*r)

        def geometry(self):
            return self.r
    monkeypatch.setattr(QApplication, "screens",
                        staticmethod(lambda: [Scr(0, 0, 1536, 960), Scr(3072, 0, 1920, 1080)]))
    body = pet._body()
    half = body.w / 0.75 / 2
    feet_y = 900 - pet.foot_offset()
    pet.move(1536 - W // 2 + 30, feet_y)                 # walking off the laptop's right edge
    assert pet.x() + W / 2 + half <= 1537
    pet.move(QPoint(2600, feet_y))                      # dragged most of the way over
    assert pet.x() + W / 2 - half >= 3072
    pet.move(3072 - W // 2, feet_y)                      # half off the big monitor's left edge
    assert pet.x() + W / 2 - half >= 3072


def test_switching_off_leaves_the_pet_alone(pet):
    pet.surfaces = None
    assert not pet._web_move()
    pet._stay_on_surface()                      # no surfaces: nothing happens
    assert pet.state == "sit"


# ---- the bridge ---------------------------------------------------------------------
def test_native_framing_round_trip():
    buf = io.BytesIO()
    bridge.write_native(buf, {"type": "dig", "x": 1, "y": 2})
    buf.seek(0)
    assert bridge.read_native(buf) == {"type": "dig", "x": 1, "y": 2}
    assert bridge.read_native(buf) is None                      # end of stream


def test_host_relays_both_ways(qapp, monkeypatch):
    """A real host process between a fake browser (pipes) and BridgeServer."""
    from PyQt6.QtCore import QCoreApplication
    name = f"pisi-bridge-test-{os.getpid()}"
    server = bridge.BridgeServer(name)
    assert server.listening
    got = []
    server.message.connect(got.append)
    env = {**os.environ, "PISI_BRIDGE_NAME": name, "QT_QPA_PLATFORM": "offscreen"}
    host = subprocess.Popen([sys.executable, "-m", "companion", "--browser-host",
                             "chrome-extension://x/"], cwd=ROOT, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        def pump(pred, secs=10):
            end = time.time() + secs
            while time.time() < end and not pred():
                QCoreApplication.processEvents()
                time.sleep(0.01)
            return pred()

        assert pump(lambda: server.clients == 1)
        msg = {"type": "lines", "tab": 3, "focused": True, "scroll": [0, 0],
               "lines": [[10, 20, 300, 18]]}
        bridge.write_native(host.stdin, msg)
        assert pump(lambda: any(m.get("type") == "lines" for m in got))
        seen = next(m for m in got if m.get("type") == "lines")
        assert seen["lines"] == [[10, 20, 300, 18]] and seen["tab"] == 3
        server.send({"type": "dig", "x": 5, "y": 6})
        # the host first says it's connected, then relays the bump
        replies = []
        for _ in range(2):
            replies.append(bridge.read_native(host.stdout))
        assert {"type": "status", "connected": True} in replies
        assert {"type": "dig", "x": 5, "y": 6} in replies
        host.stdin.close()                                      # browser closed
        host.wait(10)
        assert pump(lambda: server.clients == 0)
        assert any(m.get("type") == "host-gone" for m in got)
    finally:
        if host.poll() is None:
            host.kill()
        server.close()


def test_install_registers_with_browsers_found(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("registry install is covered on Windows CI only by import")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    if sys.platform == "darwin":
        brave = tmp_path / "Library/Application Support/BraveSoftware/Brave-Browser"
        moz = tmp_path / "Library/Application Support/Mozilla"
    else:
        brave = tmp_path / ".config/BraveSoftware/Brave-Browser"
        moz = tmp_path / ".mozilla"
    brave.mkdir(parents=True)
    moz.mkdir(parents=True)
    assert bridge.installed() == []
    assert sorted(bridge.install()) == ["Brave", "Firefox"]
    chrome_m = json.loads((brave / "NativeMessagingHosts" / f"{bridge.HOST_NAME}.json").read_text())
    ff_m = json.loads((moz / "NativeMessagingHosts" / f"{bridge.HOST_NAME}.json").read_text())
    assert chrome_m["allowed_origins"] == [f"chrome-extension://{i}/" for i in
                                           (bridge.CHROME_EXTENSION_ID, *bridge.OLD_CHROME_IDS)]
    assert ff_m["allowed_extensions"] == [bridge.FIREFOX_EXTENSION_ID]
    # an older setup that trusted only an old ID is brought up to date at startup
    stale = brave / "NativeMessagingHosts" / f"{bridge.HOST_NAME}.json"
    stale.write_text(json.dumps({**chrome_m, "allowed_origins": ["chrome-extension://old/"]}))
    bridge.refresh()
    assert json.loads(stale.read_text())["allowed_origins"] == chrome_m["allowed_origins"]
    launcher = Path(chrome_m["path"])
    assert launcher.exists() and os.access(launcher, os.X_OK)
    assert "--browser-host" in launcher.read_text()
    assert sorted(bridge.installed()) == ["Brave", "Firefox"]
    assert sorted(bridge.uninstall()) == ["Brave", "Firefox"]
    assert bridge.installed() == []


@pytest.mark.skipif(sys.platform != "linux", reason="AppImages are Linux only")
def test_from_an_appimage_the_bridge_points_at_the_file_not_its_temporary_insides(
        tmp_path, monkeypatch):
    """An AppImage's files live in a mount with a new name each launch: the
    browser's launcher must run the AppImage itself, and the extension a
    browser loads must be a copy that stays put (and keeps up to date)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (tmp_path / ".config/BraveSoftware/Brave-Browser").mkdir(parents=True)
    ai = tmp_path / "Apps" / "PISI-1.3.1-x86_64.AppImage"
    ai.parent.mkdir()
    ai.write_text("#!/bin/sh\n")
    monkeypatch.setenv("APPIMAGE", str(ai))
    assert bridge.install() == ["Brave"]
    launcher = bridge.host_dir() / "pisi-browser-host"
    text = launcher.read_text()
    assert f"exec '{ai}' '--browser-host'" in text and "/tmp/.mount" not in text
    ext = bridge.extension_dir()
    assert ext == tmp_path / "data" / "desktop-companion" / "browser-extension"
    assert (ext / "manifest.json").read_bytes() == (EXT / "manifest.json").read_bytes()
    (ext / "manifest.json").write_text("{}")             # an older copy...
    (ext / "stale.js").write_text("")
    bridge.refresh()                                     # ...is brought up to date at start
    assert (ext / "manifest.json").read_bytes() == (EXT / "manifest.json").read_bytes()
    assert not (ext / "stale.js").exists()
    moved = tmp_path / "PISI.AppImage"                   # and a moved AppImage is followed
    ai.rename(moved)
    monkeypatch.setenv("APPIMAGE", str(moved))
    bridge.refresh()
    assert f"exec '{moved}' '--browser-host'" in launcher.read_text()


# ---- the page's shape and playing on it -------------------------------------------
def test_surfaces_carry_the_page_shape():
    s = WebSurfaces(Clock())
    s.feed({"type": "lines", "conn": 1, "tab": 1, "focused": True, "scroll": [0, 0],
            "view": [0, 100, 1200, 800], "win": [0, 20, 1200, 880],
            "kinds": ["h", "p", "img", "button", "search"],
            "lines": [[50, 120, 300, 40, 0], [50, 180, 600, 20, 1], [50, 207, 600, 20, 1],
                      [50, 234, 300, 20, 1], [50, 300, 400, 200, 2], [500, 300, 60, 30, 3],
                      [600, 120, 300, 30, 4]]})
    segs = s.segments()
    assert [(g.kind, g.block, g.row, g.rows) for g in segs[:5]] == [
        ("h", 0, 0, 1), ("p", 1, 0, 3), ("p", 1, 1, 3), ("p", 1, 2, 3), ("img", 2, 0, 1)]
    assert segs[4].y == 300                       # a picture's top edge exactly
    assert s.view() == (0, 100, 1200, 800)
    assert s.window() == (0, 20, 1200, 880)
    kinds = [b.kind for b in s.boxes()]
    assert kinds == ["h", "p", "p", "p", "img", "button", "search"]
    assert s.metrics()[0] == 20                   # typical line height


# ---- where the pet fits ------------------------------------------------------------------
BODY = perch.Body(w=40, stand=40, crouch=30, sit=36)


def test_a_line_inside_a_paragraph_is_no_place_to_stand():
    para = [_text(100, 200 + i * 24, 700, block=0) for i in range(4)]
    ls = perch.ledges(para, BODY)
    assert [l.y for l in ls] == [para[0].edge]    # only the top of the paragraph
    assert not ls[0].low


def test_crouching_room_between_paragraphs_and_a_nook_by_a_short_line():
    upper = [_text(100, 100, 700, block=0), _text(100, 124, 300, block=0)]   # short last line
    lower = _text(100, 180, 700, block=1)        # 36 px below the long line, 12 more below the short one
    ls = [l for l in perch.ledges([*upper, lower], BODY) if l.y == lower.edge]
    # beside the short line there's room to stand; under the long one, only to crouch
    stand = [l for l in ls if not l.low]
    crouch = [l for l in ls if l.low]
    assert stand and stand[0].x0 >= 300 and crouch and crouch[0].x1 <= stand[0].x0 + 0.01


def test_no_room_at_all_is_no_ledge():
    upper = _text(100, 100, 700, block=0)
    lower = _text(100, 140, 700, block=1)        # 20 px gap: less than crouching height
    assert [l for l in perch.ledges([upper, lower], BODY) if l.y == lower.edge] == []


def test_pictures_buttons_and_the_window_top_are_ledges():
    pic = Box(100, 300, 500, 500, "img", 0)
    btn = Box(600, 300, 660, 330, "button", 1)
    ls = perch.ledges([pic, btn], BODY, view=(0, 100, 1200, 800), ceiling=0,
                      win=(0, 60, 1200, 860))
    assert {l.kind for l in ls} == {"img", "button", "top"}
    # a maximised browser: its top is the top of the screen, no room up there
    ls = perch.ledges([pic, btn], BODY, view=(0, 100, 1200, 800), ceiling=0, win=(0, 0, 1200, 900))
    assert "top" not in {l.kind for l in ls}
    # under the browser's toolbar is not on the page
    hidden = _text(100, 90, 700)
    assert perch.ledges([hidden], BODY, view=(0, 100, 1200, 800)) == []


def test_leaps_go_over_things_not_through_them():
    left, right = _text(100, 300, 400, block=0), _text(500, 300, 900, block=2)
    button = Box(430, 270, 470, 318, "button", 1)
    boxes = [left, button, right]
    ls = perch.ledges(boxes, BODY)
    here = perch.support(ls, 390, left.edge)
    options = perch.hops(ls, boxes, BODY, here, 390)
    over = next(o for o in options if o.seg.block == 2)
    for t in (0.3, 0.5, 0.7):                       # sails over the button
        x, y = perch.hop_point(390, left.edge, over.x, over.seg.y, t, over.lift)
        if 430 - BODY.w / 2 < x < 470 + BODY.w / 2:
            assert y - 8 < button.y0
    # but not up through a paragraph
    para = [_text(100, 100 + i * 24, 700, block=3) for i in range(4)]
    assert perch.find_lift(para, BODY, 300, 250, 300, 60) is None


def test_planner_explores_the_shelf_then_hops_on():
    import random
    left, right = _text(100, 300, 800, block=0), _text(900, 300, 1300, block=1)
    boxes = [left, right]
    page = perch.Page(perch.ledges(boxes, BODY), boxes, BODY)
    here = perch.support(page.segs, 150, left.edge)
    moves = [perch.plan(page, here, 150, 1, random.Random(i)) for i in range(20)]
    walks = [m for m in moves if m.kind in ("walk", "run")]
    assert walks and sum(m.x > 700 for m in walks) > len(walks) / 2   # mostly onwards
    hops = [m for i in range(40)
            if (m := perch.plan(page, here, 790, 1, random.Random(i))).kind == "hop"]
    assert any(m.seg.block == 1 for m in hops)


def test_climbing_mood_goes_up_the_wall_and_naps_at_the_top():
    import random
    upper, lower = _two_paragraphs(200, 200)
    boxes = upper + lower
    body = perch.Body(w=100, stand=92, crouch=70, sit=80)
    page = perch.Page(perch.ledges(boxes, body, ceiling=0), boxes, body)
    here = perch.support(page.segs, 400, lower[0].edge)
    assert here is not None and here.low       # 80 px under the paragraph above
    mv = perch.plan(page, here, 400, -1, random.Random(1), mood="climb")
    assert mv.kind == "scale" and mv.seg.y == upper[0].edge
    climb = [op for op in mv.ops if op[0] == "climb"][0]
    assert climb[1].x < 200 or climb[1].x > 700          # beside the column, either side
    top = perch.support(page.segs, 400, upper[0].edge)
    mv = perch.plan(page, top, 400, -1, random.Random(1), mood="climb")
    assert mv.kind == "stay" and mv.pose == "sleep"


def test_low_ledges_get_a_low_pose_and_search_boxes_a_nap():
    import random
    low = Seg(100, 400, 300, room=BODY.crouch + 2, low=True)
    assert perch._rest_pose(low, BODY, "sit") == "crouch"
    assert perch._rest_pose(low, BODY, "sleep") == "sleep"
    search = Box(100, 300, 500, 330, "search", 0)
    page = perch.Page(perch.ledges([search], BODY), [search], BODY)
    poses = {perch.plan(page, page.segs[0], 300, 1, random.Random(i)).pose for i in range(20)}
    assert "sleep" in poses


def test_from_the_floor_it_finds_a_way_up_not_a_flight():
    import random
    boxes = [_text(100, 300, 800)]
    page = perch.Page(perch.ledges(boxes, BODY), boxes, BODY)
    assert perch.plan(page, None, 900, -1, random.Random(1)) is None    # mid-air: land first
    near = Seg(0, 1000, 302 + BODY.stand * 1.2, "floor", -3)            # a leap below the line
    mv = next(m for i in range(20)
              if (m := perch.plan(page, near, 500, -1, random.Random(i))) is not None)
    assert mv.kind in ("hop", "climb") and mv.seg is page.segs[0]
    far = Seg(0, 1000, 302 + BODY.stand * 6, "floor", -3)               # far too high to leap
    assert all(perch.plan(page, far, 500, -1, random.Random(i)) is None for i in range(20))


def test_it_climbs_a_narrow_gap_between_columns():
    """Wikipedia's Cat article: a photo gallery with a narrow column beside
    it, everything packed down to the floor. A climbing cat hugs the wall,
    so the 74 px between the gallery and that column is room enough to get
    up to the caption above the photos (it used to just sit on the floor)."""
    body = perch.Body(w=78.75, stand=81, crouch=69, sit=81, crawl=51)
    boxes = [Box(951, 474, 1198, 490, "p"), Box(942, 500, 1097, 658, "img"),
             Box(1101, 500, 1207, 659, "img"), Box(942, 660, 1078, 743, "img"),
             Box(1082, 660, 1207, 743, "img"), Box(942, 744, 1068, 923, "img"),
             Box(1072, 744, 1207, 924, "img"),
             Box(1281, 446, 1339, 462, "p"), Box(1281, 558, 1344, 574, "p")]
    boxes += [Box(264, y, 905, y + 18, "p") for y in range(438, 900, 26)]   # the article
    boxes += [Box(58, y, x1, y + 16, "p") for y, x1 in                     # its contents list
              ((461, 181), (490, 143), (518, 109), (546, 207), (574, 198), (602, 113),
               (659, 131), (687, 142))]
    page = perch.Page(perch.ledges(boxes, body), boxes, body, view=(0, 85, 1545, 839))
    floor = Seg(52.5, 1484.5, 902, "floor", -3)
    way = perch.route(page, floor, 1025)
    assert way and way[0].seg.y < 500


def test_route_goes_ledge_by_ledge_to_the_best_spot():
    """A staircase of shelves up to a heading: the way there is one step at a
    time, never one big leap."""
    boxes = [_text(100 + 150 * i, 600 - 50 * i, 220 + 150 * i, block=i) for i in range(5)]
    boxes.append(_text(850, 340, 1100, h=30, block=9, kind="h"))
    page = perch.Page(perch.ledges(boxes, BODY), boxes, BODY, view=(0, 0, 1200, 800))
    floor = Seg(0, 1200, 650, "floor", -3)
    way = perch.route(page, floor, 120)
    assert len(way) >= 4 and way[-1].seg.kind == "h"
    y = floor.y
    for step in way:                                  # each leap is a cat-sized one
        if isinstance(step, perch.Hop):
            assert y - step.seg.y <= BODY.max_rise + 1
        y = step.seg.y


def test_the_pet_takes_on_a_size_that_suits_the_text():
    paras = []
    for i in range(5):                          # 17 px lines, 25 px between paragraphs
        y = 100 + i * 100
        paras += [_text(100, y + j * 25, 700, h=17, block=i) for j in range(3)]
    line_h, gap = perch.metrics(paras)
    assert line_h == 17 and gap == pytest.approx(100 - 2 * 25 - 17)
    unit = perch.Body(w=24, stand=29, crouch=22, sit=26)      # a 48 px sprite at scale 1
    assert perch.fit_scale(unit, line_h, gap, [1, 2, 3]) == 1
    assert perch.fit_scale(unit, line_h, gap, [0.5, 1, 1.5, 2]) == 1.5
    assert perch.fit_scale(unit, 40, 60, [1, 2, 3]) == 2      # big text, a bigger pet
    assert perch.fit_scale(unit, 0, 0, [1, 2, 3]) == 3        # no text: as usual


def test_lets_go_under_the_toolbar_and_drifts_onto_the_next_line(pet):
    r = pet._screen_rect()
    view = (r.left(), r.top() + 120, r.width(), r.height() - 120)
    top_line = _text(r.left() + 50, view[1] + 30, r.left() + 700, block=0)
    next_line = _text(r.left() + 50, view[1] + 240, r.left() + 700, block=1)
    fake = FakeSurfaces([top_line, next_line], view=view)
    pet.surfaces = fake
    _put(pet, r.left() + 300, top_line.edge)
    # scrolled: the line goes up under the toolbar
    fake.set([_text(top_line.x0, view[1] - 10, top_line.x1, block=0),
              _text(next_line.x0, next_line.y0 - 40, next_line.x1, block=1)])
    fake.scroll = -40
    pet._stay_on_surface()
    assert pet.state == "fall"
    speeds = []
    for _ in range(400):
        pet._tick()
        speeds.append(pet._vy)
        if pet.state != "fall":
            break
    from companion.sprite import DRIFT_MAX
    assert max(speeds) <= DRIFT_MAX                 # a slow drift, not a plunge
    assert pet._perched and pet._feet()[1] == pytest.approx(next_line.edge - 40, abs=1)


def test_falling_pet_catches_text_scrolling_up_past_it(pet):
    r = pet._screen_rect()
    line = _text(r.left() + 50, r.top() + 400, r.left() + 700)
    fake = FakeSurfaces([line])
    pet.surfaces = fake
    feet0 = line.edge - 10                           # just above the line
    pet.move(r.left() + 200, int(feet0 - pet.foot_offset()))
    pet.state, pet._vy = "fall", 0.0
    # the user scrolls fast: the line jumps 80 px up, past the pet's feet
    fake.set([_text(line.x0, line.y0 - 80, line.x1)])
    fake.scroll = -80
    pet._tick()
    assert pet._perched and pet._feet()[1] == pytest.approx(line.edge - 80, abs=1)


def test_browser_units_are_converted_when_the_browser_ignores_display_scaling():
    """Measured on a 2x laptop: Brave called the screen 3072 wide, Qt 1536."""
    s = WebSurfaces(Clock(), scale_for=lambda w, h: 1536 / w)
    s.feed({"type": "lines", "conn": 1, "tab": 1, "focused": True, "scroll": [0, 400],
            "screen": [3072, 1920], "view": [0, 10, 3072, 1660], "kinds": ["p"],
            "lines": [[400, 600, 1000, 40, 0]]})
    (seg,) = s.segments()
    assert (seg.x0, seg.x1) == (200, 700) and 300 <= seg.y <= 303
    assert s.view() == (0, 5, 1536, 830)
    s.feed({"type": "lines", "conn": 1, "tab": 1, "focused": True, "scroll": [0, 600],
            "screen": [3072, 1920], "kinds": ["p"], "lines": [[400, 400, 1000, 40, 0]]})
    assert s.take_scroll() == -100                  # 200 browser px = 100 of ours
    assert s.to_browser(250, 300) == (500, 600)     # bumps go back in browser units


def test_pages_are_placed_on_the_right_monitor():
    """Measured: Brave on X11 called a 4K monitor 2560x1440 (1.5x) and the
    laptop 1680x1050 (1.83x), numbering both from 0; Qt said 1920x1080 at
    x=3072 and 1536x960 at x=0, both at 2x."""
    screens = [(3072, 0, 1920, 1080, 2.0), (0, 0, 1536, 960, 2.0)]
    pm = perch.browser_map({"screen": [2560, 1440], "left": 0, "top": 0, "win": [0, 0, 2560, 1440],
                            "inner": [2560, 1300], "dpr": 1.5}, screens)
    assert pm.zoom == 1.0 and pm.s == 0.75
    assert pm.ax == 3072 and pm.ay == pytest.approx(140 * 0.75)    # toolbars above the page
    pm = perch.browser_map({"screen": [1680, 1050], "left": 0, "top": 0, "win": [0, 0, 1680, 1050],
                            "inner": [1344, 800], "dpr": 1.8286 * 1.25}, screens)
    assert pm.zoom == 1.25 and pm.ax == pytest.approx(0) and pm.s == pytest.approx(1.25 * 1536 / 1680)
    # a mouse position over the page: ignored by default (Brave on X11 gives
    # mouse positions in other units, and using them made the page jump)...
    geo = {"screen": [2560, 1440], "win": [100, 50, 1200, 900], "inner": [1000, 800], "dpr": 1.5,
           "mouse": [100 + 200 + 40, 50 + 100 + 30, 40, 30]}
    assert not perch.browser_map(geo, screens).exact
    # ...but when switched on it says exactly where the page sits (a side panel on the left)
    perch.USE_MOUSE = True
    try:
        pm = perch.browser_map(geo, screens)
        assert pm.exact and pm.ax == pytest.approx(3072 + 300 * 0.75)
        geo["mouse"] = [(100 + 200 + 40) * 1.5, (50 + 100 + 30) * 1.5, 40, 30]    # real pixels
        assert perch.browser_map(geo, screens).ax == pytest.approx(3072 + 300 * 0.75)
    finally:
        perch.USE_MOUSE = False


def test_a_made_up_screen_size_still_places_the_page():
    """Measured 2026-10-06: Brave (fingerprinting protection) told Wikipedia
    the 3072x1920 laptop was a 2560x1440 screen; Qt says 1536x960 at 2x. No
    screen has that shape, so the page was never placed and the cat waited
    forever. Its pixel ratio (1.6) is real: the page goes by that."""
    screens = [(0, 0, 1536, 960, 2.0)]
    geo = {"screen": [2560, 1440], "left": 0, "top": 0, "win": [0, 8, 1924, 1044],
           "inner": [1920, 1042], "dpr": 1.6}
    pm = perch.browser_map(geo, screens)
    assert pm is not None and pm.s == pytest.approx(0.8)
    assert pm.win[2] == pytest.approx(1924 * 0.8)                   # the window fills the screen
    assert pm.ay == pytest.approx((8 + 2) * 0.8)                    # the page just under its bar



def test_surfaces_place_page_coordinates_and_send_bumps_back_in_them():
    s = WebSurfaces(Clock(), screens=lambda: [(3072, 0, 1920, 1080, 2.0)])
    s.feed({"type": "lines", "conn": 1, "tab": 1, "focused": True, "scroll": [0, 0],
            "geo": {"screen": [2560, 1440], "win": [0, 0, 2560, 1440], "inner": [2560, 1300],
                    "dpr": 1.5},
            "kinds": ["p"], "lines": [[100, 200, 800, 20, 0]]})
    (b,) = s.boxes()
    assert (b.x0, b.y0) == (3072 + 75, pytest.approx(105 + 150))
    assert s.view()[0] == 3072 and s.window() == (3072, 0, 1920, 1080)
    assert s.to_browser(3072 + 75, 255) == (100, 200)


def test_browser_scale_matches_the_real_screen(qapp):
    from PyQt6.QtWidgets import QApplication
    from companion.app import browser_scale
    g = QApplication.primaryScreen().geometry()
    assert browser_scale(g.width(), g.height()) == 1.0
    assert browser_scale(g.width() * 2, g.height() * 2) == 0.5
    assert browser_scale(123, 4567) == 1.0          # no screen looks like that


def _squeeze_page(left, top, scale=1.0):
    """A paragraph ending in a short line, a heading tucked close under it
    (room to crawl, not to crouch), the next paragraph below."""
    s = scale
    boxes = [Box(left, top + i * 47 * s, left + 1100 * s, top + (i * 47 + 30) * s, "p", 0)
             for i in range(3)]
    boxes.append(Box(left, top + 141 * s, left + 300 * s, top + 171 * s, "p", 0))      # short last line
    boxes.append(Box(left, top + 229 * s, left + 410 * s, top + 275 * s, "h", 1))      # the heading
    boxes += [Box(left, top + (315 + i * 47) * s, left + 1100 * s, top + (345 + i * 47) * s, "p", 2)
              for i in range(15)]                      # on down to the bottom of the window
    return boxes


def test_a_cat_squeezes_through_where_it_can_only_crawl():
    """Measured on Wikipedia: 58 px under the paragraph above the heading
    'Etymology and naming'; the full-size cat is 90 tall, 66 crouched and
    51 flat on its belly."""
    body = perch.Body(74.25, 90, 66, 78, 51)
    boxes = _squeeze_page(764, 30)
    view = (0, 0, 1940, 1040)
    segs = perch.ledges(boxes, body, view, ceiling=0)
    over = [s for s in segs if s.kind == "h"]
    assert over[0].tight and not over[-1].tight          # tight by the paragraph, roomy past it
    floor = Seg(60, 1880, 1060, "floor", -3)
    page = perch.Page(segs, boxes, body, view, calm=True, floor=floor)
    way = perch.route(page, floor, 300)
    assert [type(s).__name__ for s in way][:2] == ["Scale", "Walk"]
    assert way[0].seg.tight and not way[1].seg.tight     # in on its belly, out where it can sit
    # it doesn't settle where it can only crawl
    import random
    mv = perch.plan(page, over[0], over[0].x0 + 20, 1, random.Random(1))
    assert mv.kind == "walk" and mv.x >= over[-1].x0


def test_climbing_follows_the_texts_outline_in_and_out():
    """An indented note in the column's side: a small cat shifts in along it
    and back out below, instead of climbing straight up past the empty bit."""
    body = perch.Body(w=20, stand=24, crouch=18, sit=22, crawl=14)
    boxes = [Box(500, 100 + i * 20, 900, 114 + i * 20, "p", 0) for i in range(4)]
    boxes += [Box(530, 190 + i * 20, 900, 204 + i * 20, "p", 1) for i in range(4)]    # indented 30
    boxes += [Box(500, 280 + i * 20, 900, 294 + i * 20, "p", 2) for i in range(6)]
    w = max((w for w in perch.walls(boxes, body) if w.side > 0), key=lambda w: w.bot - w.top)
    pts = perch.wall_path(boxes, w, 390, 110, body)
    xs = {round(y): x for x, y in pts}
    near = lambda y: xs[min(xs, key=lambda k: abs(k - y))]
    assert near(350) == 500 and near(250) == 530 and near(150) == 500


def test_a_trip_can_leap_from_wall_to_wall():
    """Up the article's side, across to the contents list beside it, on up."""
    body = perch.Body(74.25, 90, 66, 78, 54)
    article = [Box(500, 180 + i * 27, 1180, 198 + i * 27, "p", i // 6) for i in range(32)]
    toc = [Box(232, 270 + i * 29, 232 + w, 288 + i * 29, "li", 50 + i)
           for i, w in enumerate((60, 150, 70, 80, 120, 60, 70, 145, 70, 160, 130, 160))]
    boxes = article + toc
    view = (0, 80, 1920, 960)
    floor = Seg(60, 1860, 1063, "floor", -3)
    page = perch.Page(perch.ledges(boxes, body, view, ceiling=0), boxes, body, view, floor=floor)
    trips = page.wall_map().scales(floor, 300)
    assert any([o[0] for o in t.ops].count("leap") >= 1 and t.seg.kind == "li" for t in trips)
    for t in trips:                           # every trip starts on a wall and ends on a ledge
        assert t.ops[0][0] in ("mount", "leap") and t.ops[-1][0] in ("pullup", "hop")


# ---- the cat guards your focus ------------------------------------------------
def _guarded_page(pet):
    """A page of text in the middle of the screen; returns (fake, view)."""
    r = pet._screen_rect()
    view = (r.left() + 200, r.top() + 150, 900, 600)
    lines = [_text(view[0] + 40, view[1] + 60 + 160 * i, view[0] + 860) for i in range(4)]
    fake = FakeSurfaces(lines, view=view)
    pet.surfaces = fake
    return fake, view


def test_guarding_cat_leaves_its_nap_and_sits_in_the_middle_of_the_page(pet):
    _, view = _guarded_page(pet)
    pet.begin_focus()                                  # napping on the floor
    said = []
    pet.say = lambda text, persist=False: said.append(text)
    pet.guard(True)
    assert not pet._focus                              # the nap is on hold
    _run(pet, 400, until=lambda: said)
    cx, feet = pet._feet()
    assert pet._perched and said
    assert abs(cx - (view[0] + view[2] / 2)) < view[2] * 0.25
    assert abs(feet - (view[1] + view[3] / 2)) < view[3] * 0.3
    # it stays there: no wandering off along the line
    x = pet.x()
    _run(pet, 300)
    assert pet._perched and abs(pet.x() - x) <= 2 and len(said) == 1


def test_done_guarding_it_drops_back_down_to_its_nap(pet):
    _guarded_page(pet)
    pet.begin_focus()
    pet.guard(True)
    _run(pet, 400, until=lambda: pet._perched and pet._guard_said)
    pet.guard(False)                                   # you left the page
    assert pet._focus
    _run(pet, 300, until=lambda: _settled(pet) and pet.y() == pet._floor_y())
    assert pet.y() == pet._floor_y() and not pet._perched


def test_a_focus_block_resumed_mid_guard_waits_for_the_guard(pet):
    _guarded_page(pet)
    pet.guard(True)                                    # (no block running yet)
    pet.begin_focus()                                  # a block starts meanwhile
    assert not pet._focus and pet._guard_back
    pet.guard(False)
    assert pet._focus


class _Web:
    def __init__(self):
        self._active, self.flag = ("c", 7), True

    def guarded(self):
        return self.flag


def test_guard_follows_focus_and_the_page_and_shooing_snoozes_it(pet):
    from companion.guard import SNOOZE_S, Guard
    _guarded_page(pet)
    now = [100.0]
    web = _Web()
    g = Guard(web, pet, clock=lambda: now[0])
    g.update(focusing=False)
    assert not pet._guarding                           # breaks leave sites alone
    g.update(focusing=True)
    assert pet._guarding
    web.flag = False                                   # you switched tabs
    g.update(focusing=True)
    assert not pet._guarding
    web.flag = True
    g.update(focusing=True)
    pet.shooed.emit()                                  # dragged off: five minutes
    assert not pet._guarding
    g.update(focusing=True)
    assert not pet._guarding
    now[0] += SNOOZE_S + 1
    g.update(focusing=True)
    assert pet._guarding


def test_each_shoo_in_a_block_buys_less_time(pet):
    from companion.guard import SNOOZES, Guard
    _guarded_page(pet)
    now = [100.0]
    g = Guard(_Web(), pet, clock=lambda: now[0])
    said = []
    pet.say = lambda text, *a, **k: said.append(text)
    for secs, _line in SNOOZES + SNOOZES[-1:]:          # the last one holds
        g.update(focusing=True)
        assert pet._guarding
        pet.shooed.emit()
        now[0] += secs - 1
        g.update(focusing=True)
        assert not pet._guarding                       # still snoozed...
        now[0] += 2                                    # ... and then not
    assert said == [line for _s, line in SNOOZES + SNOOZES[-1:]]
    g.new_block()                                      # a fresh block: patience is back
    g.update(focusing=True)
    pet.shooed.emit()
    assert said[-1] == SNOOZES[0][1]


def test_pisi_hears_whether_any_site_is_guarded_but_not_which():
    web = WebSurfaces(Clock())
    assert web.guards_any is None                      # not told yet
    web.feed({**_lines([[100, 300, 400, 20]]), "guards": True})
    assert web.guards_any is True
    web.feed({**_lines([[100, 300, 400, 20]]), "guards": False})
    assert web.guards_any is False


def test_the_extension_icon_says_when_the_cat_is_guarding():
    from companion import pagestatus

    class W:
        _active, active, located = ("c", 7), True, True
    assert pagestatus.state(W, focusing=False, perch_on=True, guarding=True) == "guarding"
    assert pagestatus.state(W, focusing=True, perch_on=True) == "napping"


# ---- digging -------------------------------------------------------------------
@pytest.fixture(scope="module")
def _baked():
    from companion.creatures import api
    return api.Creature(api.canon_genome()).bake()


@pytest.fixture
def live(pet, _baked):
    """The pet with real animations (dig, startle, watch...)."""
    from companion.creatures import qt as cq
    pet.set_sheet(cq.sheet_from_baked(_baked), {})
    pet.place_start()
    return pet

def _paragraph(pet, rows=4, gap=4, h=None):
    """A paragraph of ``rows`` lines mid-screen, spaced like real text for
    the pet's size; returns (fake, lines)."""
    r = pet._screen_rect()
    h = h or max(14, int(pet._body().stand * 0.5))
    x0, y0 = r.left() + 300, r.top() + 300
    lines = [_text(x0, y0 + i * (h + gap), x0 + 500, h=h) for i in range(rows)]
    fake = FakeSurfaces(lines, view=(r.left(), r.top(), r.width(), r.height()))
    fake.page = {"mess": True}
    pet.surfaces = fake
    return fake, lines


def test_digging_flicks_the_words_off_and_drops_through_to_the_next_line(live):
    pet = live
    fake, lines = _paragraph(pet)
    _put(pet, lines[0].x0 + 200, lines[0].edge)
    dug = []
    pet.dug.connect(lambda *a: dug.append(a))
    assert pet.can_dig() and pet._below_in_block()
    pet._dig_left = 0
    assert pet.dig()
    assert pet.state == "dig" and pet._mood == "dig"
    cx, feet, w, facing = dug[0]
    assert abs(cx - (lines[0].x0 + 200)) <= 1 and abs(feet - lines[0].edge) <= 1 and w > 0
    # the extension takes the words there away: a hole in the line
    hole = (cx - w / 2, cx + w / 2)
    fake.set([_text(lines[0].x0, lines[0].y0, hole[0], h=lines[0].y1 - lines[0].y0),
              _text(hole[1], lines[0].y0, lines[0].x1, h=lines[0].y1 - lines[0].y0)] + lines[1:])
    _run(pet, 300, until=lambda: pet._perched and pet._feet()[1] > lines[0].edge + 2)
    assert pet._perched and abs(pet._feet()[1] - lines[1].edge) <= 1
    # still burrowing: it digs again on the line it dropped onto
    _run(pet, 40, until=lambda: len(dug) > 1)
    assert len(dug) == 2 and abs(dug[1][1] - lines[1].edge) <= 1


def test_no_digging_where_the_page_says_no_or_on_a_picture(live):
    pet = live
    fake, lines = _paragraph(pet)
    _put(pet, lines[0].x0 + 200, lines[0].edge)
    fake.page = {"mess": False}
    assert not pet.dig()
    fake.page = {"mess": True}
    fake.set([Box(b.x0, b.y0, b.x1, b.y1, "img", b.block) for b in lines])
    assert not pet.can_dig()


def test_a_dig_that_opens_no_hole_ends_the_burrow(live):
    pet = live
    fake, lines = _paragraph(pet)
    _put(pet, lines[0].x0 + 200, lines[0].edge)
    assert pet.dig()
    _run(pet, 200, until=lambda: pet.state != "dig")
    _run(pet, 300, until=lambda: pet._mood != "dig")
    assert pet._mood != "dig" and pet._perched       # nothing gave way: it stops


def test_the_tab_closing_under_it_makes_it_leap_down(live):
    pet = live
    from companion.reactions import Reactions
    fake, lines = _paragraph(pet)
    _put(pet, lines[0].x0 + 200, lines[0].edge)
    pet.reactions = Reactions(pet, fake, cursor=lambda: QPoint(-9999, -9999))
    fake.events = ["closed"]
    fake.set([])
    pet._tick()
    assert pet.state == "hop" and pet._hop.get("anim") == "startle"
    _run(pet, 300, until=lambda: _settled(pet))
    assert pet.y() == pet._floor_y() and not pet._perched


# ---- reacting to the page ----------------------------------------------------------
class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _react(pet, fake, clock, ticks=1, step=0.04):
    for _ in range(ticks):
        clock.t += step
        pet._tick()


def _reacting(pet, fake):
    from companion.reactions import Reactions
    clock = _Clock()
    pet.reactions = Reactions(pet, fake, clock=clock, cursor=lambda: QPoint(-9999, -9999))
    return clock


def test_a_selection_gets_stalked_and_swatted(live, monkeypatch):
    pet = live
    from companion import reactions as R
    monkeypatch.setattr(R.random, "random", lambda: 0.1)
    fake, lines = _paragraph(pet, rows=2)
    _put(pet, lines[0].x0 + 60, lines[0].edge)
    clock = _reacting(pet, fake)
    sel = (lines[0].x0 + 250, lines[0].y0, 80, lines[0].y1 - lines[0].y0)
    fake.page = {"dig": True, "sel": sel}
    seen = set()
    for _ in range(600):
        clock.t += 0.04
        pet._tick()
        seen.add(pet.state)
        if "bat" in seen and pet.reactions.plan is None:
            break
    assert {"walk", "stalk", "hop", "bat"} <= seen                 # crept up, pounced
    cx, _ = pet._feet()
    assert abs(cx - (sel[0] + sel[2] / 2)) < pet._body().w        # onto the highlight
    assert pet._next_decision < 10 ** 6                           # free to wander again


def test_a_video_is_watched_paused_with_and_stretched_after(live):
    pet = live
    fake, lines = _paragraph(pet, rows=2)
    _put(pet, lines[0].x0 + 60, lines[0].edge)
    clock = _reacting(pet, fake)
    vid = (lines[0].x1 + 40, lines[0].y0 - 200, 400, 240)
    fake.page = {"video": vid, "playing": "playing"}
    _react(pet, fake, clock, 400)
    assert pet.reactions.plan == "video" and pet.state == "watch"
    assert pet.facing == 1                                         # toward the video
    fake.page = {"video": vid, "playing": "paused"}
    _react(pet, fake, clock, 2)
    assert pet.state == "lookaround"
    fake.page = {"video": vid, "playing": "ended"}
    _react(pet, fake, clock, 2)
    assert pet.state == "stretch" and pet.reactions.plan is None


def test_a_login_page_makes_it_cover_its_eyes(live):
    pet = live
    fake, lines = _paragraph(pet, rows=2)
    _put(pet, lines[0].x0 + 60, lines[0].edge)
    clock = _reacting(pet, fake)
    fake.events = ["secret"]
    _react(pet, fake, clock, 2)
    assert pet.state == "covereyes"


def test_no_reactions_while_napping_through_a_focus_block(live):
    pet = live
    fake, lines = _paragraph(pet, rows=2)
    _put(pet, lines[0].x0 + 60, lines[0].edge)
    clock = _reacting(pet, fake)
    pet.begin_focus()
    fake.page = {"video": (0, 0, 400, 300), "playing": "playing", "sel": (0, 0, 50, 10)}
    _react(pet, fake, clock, 60)
    assert pet.reactions.plan is None and pet.state in ("sit", "sleep")


def test_a_slow_read_puts_it_to_sleep_on_the_page(live):
    pet = live
    fake, lines = _paragraph(pet, rows=3)
    fake._view = (lines[0].x0 - 100, lines[0].y0 - 150, 700, 450)    # the page, on screen
    _put(pet, lines[0].x0 + 60, lines[0].edge)
    clock = _reacting(pet, fake)
    fake.moves = [(t, 0.3 * fake._view[3]) for t in (5, 20, 35, 50, 65, 80, 95)]
    _react(pet, fake, clock, 400, step=0.04)
    assert pet.reactions.plan == "read" and pet.state == "sleep"
    fake.moves = []                                                 # you stopped reading
    _react(pet, fake, clock, 2)
    assert pet.state != "sleep" and pet.reactions.plan is None


def test_page_signals_arrive_on_screen_with_the_page():
    clock = Clock()
    s = WebSurfaces(clock)
    msg = _lines([[0, 100, 300, 20]])
    msg.update({"sel": [10, 100, 50, 20], "video": [0, 200, 400, 225], "playing": "paused",
                "music": True, "end": True, "mess": True})
    s.feed(msg)
    on = s.going_on()
    assert on["sel"] == (10.0, 100.0, 50.0, 20.0) and on["playing"] == "paused"
    assert on["music"] and on["end"] and on["mess"] and not on["offline"]
    s.feed(dict(_lines([[0, 100, 300, 20]], sy=60), sel=None))
    assert s.going_on()["sel"] is None and s.scrolls(10) == [(0.0, 60.0)]
    s.feed({"type": "gone", "conn": 7, "tab": 1, "why": "closed"})
    assert s.take_events() == ["closed"] and s.take_events() == []
    s.feed({"type": "gone", "conn": 7, "tab": 9, "why": "closed"})   # not the page in front
    assert s.take_events() == []


# ---- tables: the rows are steps ----------------------------------------------------
# A grade table as one browser reported it (screen px): headers, then rows of
# short cells ("0 / 7") 57 px apart, too short to stand on and too close to
# stand between.
_GRADES = [(173, 252, 298, 292, "h"), (188, 369, 258, 383, "cell"), (906, 369, 1013, 383, "cell"),
           (188, 420, 297, 436, "p"), (946, 420, 1013, 436, "p"), (1057, 420, 1116, 436, "p"),
           (952, 478, 1014, 494, "p"), (942, 535, 1013, 551, "p"), (1057, 535, 1116, 551, "p"),
           (952, 592, 1014, 608, "p")] + [(965, y, 1013, y + 16, "p") for y in (652, 709, 766, 823)]
_ROWS = [(173, y, 1330, y + 2, "row") for y in (346, 403, 460, 517, 574, 631, 688, 745, 802)]


def _climb_to(pet, boxes, x, y, legs=12):
    r = pet._screen_rect()
    fake = FakeSurfaces([Box(*b) for b in boxes], view=(150, 230, 1250, r.bottom() - 230),
                        metrics=(16.0, 41.0))
    pet.surfaces = fake
    pet.move(int(456 - pet.width() / 2), pet._floor_y())
    pet._perched = False
    pet._sync_fpos()
    for _ in range(legs):
        if pet.toward(x, y) is None:
            break
        _run(pet, 400, until=lambda: _settled(pet) and pet.state != "walk")
    return pet._feet()


def test_a_table_with_rows_is_a_staircase(live):
    pet = live
    _, feet = _climb_to(pet, _GRADES, 223, 371)
    assert feet > 640                                    # text alone: stuck low down
    _, feet = _climb_to(pet, _GRADES + _ROWS, 223, 371)
    assert feet < 420                                    # up the rows to the header


def test_it_knocks_the_last_word_off_the_end_of_its_line(live):
    """Walks to the nearer end, looks at you, swats: the word goes over the edge."""
    pet = live
    fake, lines = _paragraph(pet, rows=2)
    line = lines[0]
    _put(pet, line.x1 - 120, line.edge)
    knocked = []
    pet.knocked.connect(lambda *a: knocked.append(a))
    assert pet.knock()
    seen = set()
    for _ in range(400):
        pet._tick()
        seen.add(pet.state)
        if knocked:
            break
    assert {"stare", "bat"} <= seen
    x, y, side = knocked[0]
    assert side == 1 and abs(x - line.x1) <= 2 and abs(y - line.edge) <= 1
    assert pet.facing == 1
    _run(pet, 100, until=lambda: pet._knock is None)
    assert pet._knock is None and pet._next_decision < 10 ** 6


def test_no_knocking_where_the_page_says_no(live):
    pet = live
    fake, lines = _paragraph(pet, rows=2)
    _put(pet, lines[0].x0 + 100, lines[0].edge)
    fake.page = {"mess": False}
    assert not pet.knock()


def test_it_only_knocks_where_the_text_really_ends(live):
    """A heading over the start of the line cuts the ledge short there: that
    end isn't the end of the text, so the cat goes for the real end."""
    pet = live
    fake, lines = _paragraph(pet, rows=2)
    line = lines[0]
    heading = _text(line.x0, line.y0 - 30, line.x0 + 260, h=26, block=9, kind="h")
    fake.set([heading] + lines)
    seg = next(s for s in pet._page().segs if abs(s.y - line.edge) <= 1)
    assert seg.x0 > line.x0 + 200                      # the heading took the left part
    _put(pet, seg.x0 + 40, line.edge)                  # near the cut, far from the right end
    assert pet.knock()
    assert pet._knock["side"] == 1 and abs(pet._knock["edge"] - line.x1) <= 1
