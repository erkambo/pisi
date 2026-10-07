"""The corner through the desktop's panel: PISI's D-Bus end, the corner's
hotspots in real pixels, and the shell extensions (headless)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint

from companion.creatures import panel

EXT = Path(__file__).resolve().parent.parent / "extensions"


@pytest.fixture(scope="module")
def genome():
    return [v for k, v in panel.panel(("owners",)) if k != "canon"][0]


@pytest.fixture
def corner(qapp, genome):
    from companion.home import HomeCorner
    home = HomeCorner()
    scr = qapp.primaryScreen()
    assert home.build(genome, {"home": {"offset": 40}}, 3, scr.geometry().bottom() - 60, scr)
    return home


def test_hotspots_cover_each_thing_in_real_pixels(corner, monkeypatch):
    spots = corner.hotspots()
    assert {h["id"] for h in spots} == set(corner.spots)
    for h in spots:
        s = corner.spots[h["id"]]
        assert (h["x"], h["y"]) == (s.pos.x(), s.pos.y())          # 1x: the same numbers
        assert (h["w"], h["h"]) == (s.r.w * s.scale, s.r.h * s.scale)
    # a 2x screen: real pixels count from the screen's top-left, doubled
    scr = corner._screen
    monkeypatch.setattr(type(scr), "devicePixelRatio", lambda self: 2.0)
    g = scr.geometry()
    bed = corner.spots["bed"]
    h = next(h for h in corner.hotspots() if h["id"] == "bed")
    assert h["x"] == g.x() + 2 * (bed.pos.x() - g.x()) and h["w"] == 2 * bed.r.w * bed.scale
    assert corner.from_real(h["x"], h["y"]) == bed.pos               # and back
    corner.hide()
    assert corner.hotspots() == []                                    # hidden: nothing to click


def test_clicks_and_drags_come_through_the_bridge(corner):
    from companion.panelbridge import Corner
    clicked, moved, sent = [], [], []
    corner.clicked.connect(clicked.append)
    corner.moved.connect(moved.append)
    shop = []
    br = Corner(corner, lambda: shop.append(1))
    br.hotspots_changed.connect(sent.append)
    bowl = next(h for h in json.loads(br.hotspots_json()) if h["id"] == "bowl")
    cx, cy = bowl["x"] + bowl["w"] // 2, bowl["y"] + bowl["h"] // 2
    br.press(cx, cy)
    br.release(cx, cy)
    assert clicked == ["bowl"] and moved == []                        # a click
    x0 = corner.x()
    br.press(cx, cy)
    for d in (4, 20, 60):
        br.move(cx - d, cy)
    br.release(cx - 60, cy)
    assert corner.x() == x0 - 60 and moved == [corner.offset()]       # a drag
    assert clicked == ["bowl"]
    moved_bowl = next(h for h in json.loads(sent[-1]) if h["id"] == "bowl")
    assert moved_bowl["x"] == bowl["x"] - 60                           # the extension hears where


def test_on_wayland_it_runs_through_xwayland(monkeypatch):
    from companion.__main__ import prefer_x11
    import companion.__main__ as M
    monkeypatch.setattr(M.sys, "platform", "linux")
    env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
    assert prefer_x11(env) and env["QT_QPA_PLATFORM"] == "xcb"
    env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "QT_QPA_PLATFORM": "wayland"}
    assert not prefer_x11(env) and env["QT_QPA_PLATFORM"] == "wayland"     # your choice wins
    env = {"WAYLAND_DISPLAY": "wayland-0"}                                  # no XWayland
    assert not prefer_x11(env) and "QT_QPA_PLATFORM" not in env
    env = {"DISPLAY": ":0"}                                                 # plain X11
    assert not prefer_x11(env) and "QT_QPA_PLATFORM" not in env


@pytest.mark.parametrize("shell", ["cinnamon", "gnome"])
def test_the_extensions_are_well_formed(shell):
    d = EXT / shell / "pisi-corner@pisi"
    meta = json.loads((d / "metadata.json").read_text())
    assert meta["uuid"] == d.name
    assert ("cinnamon-version" if shell == "cinnamon" else "shell-version") in meta
    src = (d / "extension.js").read_text()
    from companion import panelbridge as PB
    for word in (PB.SERVICE, PB.PATH, PB.INTERFACE, "HotspotsChanged", "PressRemote",
                 "MoveRemote", "ReleaseRemote", "GRAB_MAX_MS", "captured-event"):
        assert word in src, word
    cjs = shutil.which("cjs") or shutil.which("gjs")
    if cjs is None:
        pytest.skip("no gjs/cjs to compile with")
    check = ("const t = new TextDecoder().decode(imports.gi.GLib.file_get_contents(ARGV[0])[1]);"
             "const b = t.split('\\n').filter(l => !/^import /.test(l)).join('\\n')"
             ".replace('export default class PisiCornerExtension extends Extension',"
             " 'class PisiCornerExtension');"
             "new Function(b); print('ok');")
    out = subprocess.run([cjs, "-c", check, str(d / "extension.js")], capture_output=True,
                         text=True, timeout=30)
    assert out.stdout.strip().endswith("ok"), out.stderr


_ = QPoint


def test_installing_the_extension_for_this_desktop(tmp_path, monkeypatch):
    from companion import shellext
    assert shellext.desktop({"XDG_CURRENT_DESKTOP": "X-Cinnamon"}) == "cinnamon"
    assert shellext.desktop({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}) == "gnome"
    assert shellext.desktop({"XDG_CURRENT_DESKTOP": "KDE"}) == "kde"
    assert not shellext.needed("kde") and shellext.needed("cinnamon")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    calls, state = [], {"on": "['transparent-panels@germanfr']"}

    def fake_run(cmd):
        calls.append(cmd)
        if cmd[:3] == ["gsettings", "get", "org.cinnamon"]:
            return state["on"] + "\n"
        if cmd[:3] == ["gsettings", "set", "org.cinnamon"]:
            state["on"] = cmd[4]
            return ""
        return ""
    monkeypatch.setattr(shellext, "_run", fake_run)
    msg = shellext.install("cinnamon")
    dst = tmp_path / "cinnamon/extensions" / shellext.UUID
    assert (dst / "extension.js").exists() and "done" in msg
    assert state["on"] == "['transparent-panels@germanfr', 'pisi-corner@pisi']"   # theirs kept
    assert shellext.installed("cinnamon") and shellext.enabled("cinnamon")
    shellext.install("cinnamon")
    assert state["on"].count(shellext.UUID) == 1                                   # not twice
    (dst / "metadata.json").write_text('{"uuid": "pisi-corner@pisi", "version": 0}')
    monkeypatch.setattr(shellext, "desktop", lambda env=None: "cinnamon")
    shellext.refresh()                                                              # an old copy
    assert shellext._version(dst) >= 1
    assert shellext.uninstall("cinnamon") and not dst.exists()
    assert state["on"] == "['transparent-panels@germanfr']"


def test_with_the_extension_attached_the_corner_lets_clicks_through(corner):
    from companion.panelbridge import Corner
    br = Corner(corner, lambda: None)
    assert not corner.click_through()
    br.attach()
    assert corner.click_through() and corner.isVisible()          # still there, just see-through
    from PyQt6.QtCore import Qt
    assert corner.windowFlags() & Qt.WindowType.WindowTransparentForInput
    clicked = []
    corner.clicked.connect(clicked.append)
    h = next(h for h in corner.hotspots() if h["id"] == "bed")      # the extension's clicks still work
    br.press(h["x"] + 5, h["y"] + 5)
    br.release(h["x"] + 5, h["y"] + 5)
    assert clicked == ["bed"]
    br.detach()
    assert not corner.click_through() and corner.isVisible()
    assert not corner.windowFlags() & Qt.WindowType.WindowTransparentForInput


def test_an_unreadable_extension_list_is_never_overwritten(tmp_path, monkeypatch):
    """Writing a guessed list would switch off the user's other extensions."""
    from companion import shellext
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    writes = []

    def fake_run(cmd):
        if cmd[:2] == ["gsettings", "set"]:
            writes.append(cmd)
            return ""
        return None                                    # the read fails
    monkeypatch.setattr(shellext, "_run", fake_run)
    msg = shellext.install("cinnamon")
    assert writes == [] and "System Settings" in msg
    shellext.uninstall("cinnamon")
    assert writes == []
