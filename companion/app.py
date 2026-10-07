"""Orchestrator: wires the sprite, its corner, play, focus, the calendar,
the tray icon and the right-click menu together."""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timedelta

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap, QPolygonF
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication, QDialog, QMenu, QSystemTrayIcon

from . import actions, autostart
from .brain import Brain
from .calendar import CalendarService, fmt_time
from .log import get_logger
from .paths import data_dir
from .dialogs import (ManageDialog, PlanDialog, PomodoroCountDialog, SettingsDialog,
                      TutorialDialog, WorkspaceEditor)
from .focus import FocusController
from .gcal import GoogleCalendar
from .planner import Planner
from . import species
from .sprite import CatSprite
from .store import Store

log = get_logger(__name__)

IDLE_DEFER_MS = 120_000       # if user idle > 2 min, wait before nudging
CAL_REFRESH_MS = 5 * 60 * 1000        # cheap conditional GET; 304 when unchanged
SCHED_TICK_MS = 30_000
CARE_EVERY_S = 60 * 60        # self-care reminders outside breaks: at most hourly
TREAT_COOLDOWN_S = 10 * 60    # treats are free now; one every ten minutes is plenty
EVENT_LEAD_MIN = 15           # warn this many minutes before a calendar event
SMART_NUDGE_COOLDOWN_MIN = 75  # min gap between proactive planner suggestions


def browser_scale(sw: float, sh: float) -> float:
    """Factor from a browser's screen units to Qt's: match the browser's
    reported screen size against the real screens (a browser that ignores the
    desktop's 2x scaling reports a screen twice as big)."""
    best = None
    for qs in QApplication.screens():
        g = qs.geometry()
        rw, rh = g.width() / sw, g.height() / sh
        if abs(rw - rh) <= 0.03 * rw:                 # same shape: it's this screen
            if best is None or abs(rw - 1) < abs(best - 1):
                best = rw
    return round(best, 4) if best else 1.0


def qt_screens() -> list[tuple]:
    """The desktop's screens as (x, y, w, h, pixel ratio), for placing pages."""
    out = []
    for qs in QApplication.screens():
        g = qs.geometry()
        out.append((g.x(), g.y(), g.width(), g.height(), qs.devicePixelRatio()))
    return out


def should_offer_setup(store, hid: str) -> bool:
    """True if we've never yet offered to set up this habit (offer at most
    once per habit, so the nudge reaches people without ever nagging)."""
    return hid not in (store.state.get("setup_offered") or [])


def mark_setup_offered(store, hid: str) -> None:
    offered = list(store.state.get("setup_offered") or [])
    if hid not in offered:
        offered.append(hid)
        store.set_state("setup_offered", offered)   # persists (set_state saves)


def _make_icon(color_hex: str) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = QColor(color_hex)
    p.setBrush(base)
    p.setPen(Qt.PenStyle.NoPen)
    # ears
    p.drawPolygon(QPolygonF([QPointF(16, 22), QPointF(10, 4), QPointF(30, 18)]))
    p.drawPolygon(QPolygonF([QPointF(48, 22), QPointF(54, 4), QPointF(34, 18)]))
    p.drawEllipse(QPoint(32, 36), 22, 20)
    p.setBrush(QColor(40, 40, 45))
    p.drawEllipse(QPoint(24, 34), 3, 4)
    p.drawEllipse(QPoint(40, 34), 3, 4)
    p.setBrush(QColor(233, 150, 160))
    p.drawPolygon(QPolygonF([QPointF(29, 42), QPointF(35, 42), QPointF(32, 46)]))
    p.end()
    return QIcon(pm)


def _pixmap_from_sheet(sheet) -> QPixmap | None:
    """A 128px, crisply-upscaled icon built from the loaded cat's own art."""
    if not sheet:
        return None
    for name in ("sit", "idle", "meow"):
        frames = sheet.frames(name)
        if frames:
            src = frames[len(frames) // 2]
            return src.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.FastTransformation)
    return None


def _on_tile(cat: QPixmap, size: int = 128) -> QPixmap:
    """Composite the cat onto a rounded tile so it stays visible on any
    launcher/theme instead of vanishing on transparent: warm beige behind a
    dark cat, warm dark brown behind a light one (white, cream, …)."""
    # crop away the transparent padding so the cat itself fills the tile,
    # and measure how light the cat is while we're looking at every pixel
    img = cat.toImage()
    top, bottom, left, right = img.height(), -1, img.width(), -1
    light = n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 12:
                top = min(top, y); bottom = max(bottom, y)
                left = min(left, x); right = max(right, x)
                light += c.lightnessF(); n += 1
    tile = QPixmap(size, size)
    tile.fill(Qt.GlobalColor.transparent)
    p = QPainter(tile)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#4a3f35" if n and light / n > 0.5 else "#f3e4c6"))
    r = size * 0.10                          # corner radius
    p.drawRoundedRect(0, 0, size, size, r, r)
    if bottom >= top and right >= left:
        from PyQt6.QtCore import QRect
        cat = cat.copy(QRect(left, top, right - left + 1, bottom - top + 1))
    # draw the cropped cat centered, filling most of the tile
    inner = int(size * 0.86)
    scaled = cat.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    p.drawPixmap(x, y, scaled)
    p.end()
    return tile


class _WindowsFront(QObject):
    """Windows quirks of a focus-less tray app: a menu popped from the cat (a
    window that never takes focus) or the tray doesn't close when you click
    elsewhere, and a dialog can open *behind* the window you're in. Activating
    them as they appear fixes both — allowed, because the user just clicked us.

    macOS has the dialog half of this (PISI is a menu-bar app that clicks on the
    cat never activate), plus: floating windows should follow you across Spaces."""

    def __init__(self):
        super().__init__()
        self._floated: set[int] = set()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            if isinstance(obj, QDialog) or (sys.platform == "win32"
                                            and isinstance(obj, QMenu)
                                            and obj.parentWidget() is None):
                QTimer.singleShot(0, lambda o=obj: _bring_front(o))
            elif (sys.platform == "darwin" and obj.isWidgetType() and obj.isWindow()
                  and obj.windowType() == Qt.WindowType.Tool   # not popups/tooltips
                  and id(obj) not in self._floated):
                self._floated.add(id(obj))
                QTimer.singleShot(0, lambda o=obj: _float_everywhere(o))
        return False


def _bring_front(w):
    try:
        if w.isVisible():
            if sys.platform == "darwin":
                from . import macapi
                macapi.activate_app()
            w.raise_()
            w.activateWindow()
    except RuntimeError:                    # already deleted
        pass


def _float_everywhere(w):
    try:
        from . import macapi
        macapi.float_everywhere(w)
        level = getattr(w, "_mac_level", None)      # the corner and the cat: over the Dock
        if level is not None:
            macapi.set_level(w, level)
            w.raise_()
            for top in QApplication.topLevelWidgets():  # the cat stays in front of its things
                if getattr(top, "_mac_front", False) and top.isVisible():
                    top.raise_()
    except RuntimeError:
        pass


class Companion:
    def __init__(self, app: QApplication):
        self.app = app
        if sys.platform in ("win32", "darwin"):
            self._front = _WindowsFront()
            app.installEventFilter(self._front)
        self.store = Store()
        self.brain = Brain(self.store)

        cfg = self.store.config
        self.sprite = CatSprite(speed=float(cfg.get("speed", 2.0)))
        self.sprite.set_wander(bool(cfg.get("wander", True)))
        self.sprite.load_sheet(cfg)
        self.sprite.place_start()
        self.sprite.show()

        # web pages the pet can walk on (PISI browser extension, opt-in per site)
        from .bridge import BridgeServer
        from .perch import WebSurfaces
        from .paths import data_dir
        self.web = WebSurfaces(scale_for=browser_scale, screens=qt_screens,
                               memory=data_dir() / "web-places.json")
        self.bridge = BridgeServer(parent=self.app)
        self.bridge.message.connect(self.web.feed)
        self.bridge.message.connect(self._from_browser)
        self.sprite.dug.connect(self._dig_page)
        self.sprite.knocked.connect(self._knock_page)
        # ... and it notices what happens there (a video, your selection...)
        from .reactions import Reactions
        self.sprite.reactions = Reactions(self.sprite, self.web)
        self._apply_web_perch()
        # now and then, check the reported lines against the screen itself
        from .webcalib import Calibrator
        self.web_calib = Calibrator(self.web, avoid=lambda: self.sprite.geometry(),
                                    own=lambda: [getattr(self, "_web_overlay", None)])
        self._calib_timer = QTimer(self.app)
        self._calib_timer.timeout.connect(self._check_web_geometry)
        self._calib_timer.start(2500)
        # the extension's icon shows whether the cat can use the page you're on
        from .pagestatus import PageStatus
        self.page_status = PageStatus(self.web, self.bridge.send)
        # ... and during a focus block it sits on the sites you'd rather avoid
        from .guard import Guard
        self.guard = Guard(self.web, self.sprite)
        self._status_timer = QTimer(self.app)
        self._status_timer.timeout.connect(self._send_page_status)
        self._status_timer.start(1000)

        # PISI's corner: the bed, bowl, post and toy basket, fitted to the cat
        from .home import HomeCorner
        self.home = HomeCorner()
        self.home.clicked.connect(self._home_clicked)
        self.home.drag_started.connect(self.sprite._drop_thing)
        self.home.moved.connect(lambda off: self._set_corner("offset", off))
        if sys.platform == "darwin":
            # the corner stands in the Dock's strip: both windows go just above
            # the Dock (the cat, raised after it, stays in front of its things)
            from .macapi import ABOVE_DOCK
            self.home._mac_level = ABOVE_DOCK
            self.sprite._mac_level = ABOVE_DOCK
            self.sprite._mac_front = True
        self.panel_bridge = None
        if sys.platform.startswith("linux"):
            # Cinnamon / GNOME keep clicks on their panel: their PISI extension
            # asks us where the corner's things are and passes clicks back
            from . import panelbridge
            self.panel_bridge = panelbridge.start(self.home, lambda: self.open_shop())
            from . import shellext
            try:
                shellext.refresh()                    # an older copy installed: update it
            except Exception:  # noqa: BLE001 - never stop the cat over this
                log.warning("panel extension refresh failed", exc_info=True)
        if sys.platform == "win32":
            # the taskbar is always-on-top too and jumps in front when clicked:
            # keep the cat and its corner (in the taskbar's strip) above it
            self._top_timer = QTimer(self.app)
            self._top_timer.timeout.connect(self._keep_on_top)
            self._top_timer.start(2000)
        self.sprite.home = self._home_spot
        self._build_home()
        for sig in (self.app.screenAdded, self.app.screenRemoved, self.app.primaryScreenChanged):
            sig.connect(lambda *_: QTimer.singleShot(500, self._build_home))
        scr = self.app.primaryScreen()
        if scr is not None:
            scr.availableGeometryChanged.connect(lambda *_: QTimer.singleShot(500, self._build_home))

        # playing: toys on the floor, the laser, a wind-up mouse (needs the rig)
        from .playtime import PlayTime
        self._fit_cache = None
        self.playtime = PlayTime(self.sprite, self._cat_fit, self._toy_for)
        self.playtime.show_meter = bool(self.store.config.get("play_meter", True))
        self.playtime.note.connect(self._play_note)
        self.playtime.ended.connect(self._play_ended)
        self._break_play = False
        self._basket_fetch = False               # walking to the basket for a toy

        # the shop: what's bought arrives in a parcel and gets unboxed
        from .unboxing import Unboxing
        self.unboxing = Unboxing(self.sprite, self.playtime, self._cat_fit, self._render_item,
                                 self._place_item, lambda text, secs: self.say(text, seconds=secs))
        self.unboxing.finished.connect(self._unboxed)
        self._unbox_queue: list = []
        self.shop_win = None
        self._shop_key = None

        self.sprite.petted.connect(self._on_pet)
        # crumbs when it eats at its bowl, a splash when it drinks
        from .playground import splash
        self.sprite.bite.connect(
            lambda kind, x, y: splash(x, y, self.sprite.pixel_scale(), kind))
        self.sprite.request_menu.connect(self.show_menu)
        self.sprite.bubble.clicked.connect(self._on_bubble_click)

        self._bubble_action: str | None = None   # what a bubble-click should do
        self._bubble_focus_min: int | None = None  # minutes for a "focus" action
        self._bubble_ws_habit: str | None = None  # habit whose setup a click opens

        # play toys (laser / mouse) + the chase loop
        self._hush_timer = QTimer(self.app)
        self._hush_timer.setSingleShot(True)
        self._hush_timer.timeout.connect(self.sprite.hush)

        # focus (pomodoro) sessions
        self.focus = FocusController(self.sprite, self.store, self.say,
                                     on_reward=self._focus_reward,
                                     on_complete=self._log_focus_session)
        self.focus.changed.connect(self._on_focus_changed)
        self.focus.pill.countClicked.connect(self.edit_pomodoro_count)

        # calendar (read-only iCal): loads from the on-disk cache immediately so
        # it works offline; a background refresh tops it up when online.
        self.calendar = CalendarService(self.store)
        # smart, calendar-aware suggestions (focus / habit placement)
        self.planner = Planner(self.store, self.calendar)
        self._last_smart = datetime.now()   # gate the first nudge by one cooldown
        # Google Calendar two-way (Option B) — off until you connect
        self.gcal = GoogleCalendar(self.store)
        self._gcal_expiry_told = False    # nudge about a dead token only once

        # build the tray/menu after the services it references exist
        self._build_tray()
        self._apply_icon()
        # desktop notifications go through the tray balloon where notify-send
        # doesn't exist (Windows → native toast)
        actions.set_notifier(
            lambda title, body: self.tray.showMessage(title, body, self._current_icon(), 8000))

        # step out of the way of fullscreen games / videos / presentations
        self._fullscreen = False
        if sys.platform == "win32":
            self._fs_timer = QTimer(self.app)
            self._fs_timer.timeout.connect(self._fullscreen_tick)
            self._fs_timer.start(2000)


        self.calendar.refresh()
        self._cal_timer = QTimer(self.app)
        self._cal_timer.timeout.connect(self.calendar.refresh)
        self._cal_timer.start(CAL_REFRESH_MS)

        # scheduler
        self._sched = QTimer(self.app)
        self._sched.timeout.connect(self._scheduler_tick)
        self._sched.start(SCHED_TICK_MS)

        # self-care reminders (posture, water...): one as a break starts, and
        # now and then otherwise, never more than once an hour
        self._last_care = 0.0
        self._chatter = QTimer(self.app)
        self._chatter.timeout.connect(self._maybe_chatter)
        self._chatter.start(90_000)

        # the home/out menu toggle is gone: don't leave anyone stuck "out"
        # (Plan my day can still set it for the day)
        self.store.set_config("presence", "home")
        first_run = not self.store.config.get("first_run_done", False)
        self.store.set_config("first_run_done", True)
        # Windows has no install script: first launch turns on start-at-sign-in
        # and adds the Start-menu entry; later launches just keep the path fresh.
        threading.Thread(target=autostart.first_run_setup if first_run
                         else autostart.refresh, daemon=True).start()
        threading.Thread(target=self._refresh_bridge, daemon=True).start()
        if first_run:
            # let the cat settle in, then walk the newcomer through the basics
            QTimer.singleShot(900, self.open_tutorial)
        else:
            QTimer.singleShot(1200, self._hello)

    # ---- speech helpers ---------------------------------------------
    def say(self, text: str, persist: bool = False, action: str | None = None,
            seconds: int = 7, focus_min: int | None = None):
        if getattr(self, "_fullscreen", False):
            return                      # cat is tucked away during a fullscreen app
        self._bubble_action = action
        self._bubble_focus_min = focus_min
        self.sprite.say(text, persist=persist)
        self._hush_timer.stop()
        if not persist:
            self._hush_timer.start(seconds * 1000)

    def summon(self):
        """Another launch (e.g. the Start-menu icon clicked again) calls the
        already-running cat over instead of starting a second one."""
        if self._fullscreen:
            return
        self.sprite.show()
        self.sprite.raise_()
        self.sprite.come_to(QCursor.pos())
        self.say("I'm already here! \U0001F43E  right-click me for the menu", seconds=6)

    def _fullscreen_tick(self):
        from .sysinfo import fullscreen_busy
        busy = fullscreen_busy()
        if busy == self._fullscreen:
            return
        self._fullscreen = busy
        if busy:
            self.sprite.bubble.hide()
            self.sprite.hide()
            self.home.hide()
        else:
            self.sprite.show()
            if self.home.spots:
                self.home.show()

    def _hello(self):
        msg = self.brain.greeting()
        summary = self.today_summary() if self.calendar.configured() else None
        if summary:
            msg += f"\ntoday: {summary}"
        self.say(msg, seconds=9)

    # ---- PISI's corner -----------------------------------------------------
    def _home_genome(self):
        """The cat to fit the corner to (None if it couldn't be drawn)."""
        cfg = self.store.config
        if not getattr(self.sprite.sheet, "procedural", False):
            return None
        from .creatures import api
        d = cfg.get("pet_genome")
        try:
            return api.genome_from_dict(d)[0] if d else api.canon_genome()
        except Exception:  # noqa: BLE001 - a bad saved pet: no corner, not a crash
            return None

    def _build_home(self):
        if self.sprite.using():
            self.sprite._drop_thing()        # its spot is about to move
        scr = self.app.primaryScreen()
        if scr is None:
            return
        self.home.build(self._home_genome(), self.store.config, self.sprite.pixel_scale(),
                        self.sprite.floor_line(scr), scr)
        if sys.platform == "win32" and self.home.isVisible():
            self._keep_on_top()

    def _populate_corner(self, menu):
        from .home import home_config
        hc = home_config(self.store.config)
        for mode, label in (("full", "Everything"), ("bed", "Just the bed"), ("off", "Hidden")):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(hc["mode"] == mode)
            act.triggered.connect(lambda _=False, m=mode: self._set_corner("mode", m))
        menu.addSeparator()
        other = "right" if hc["side"] == "left" else "left"
        menu.addAction(f"Bed on the {other}").triggered.connect(
            lambda: self._set_corner("side", other))
        menu.addAction("Position…").triggered.connect(self._corner_position)
        if len(self.home.spots) > 1:
            menu.addAction("Arrange…").triggered.connect(self._corner_arrange)
        menu.addAction("Back to where it started").triggered.connect(
            lambda: self._set_corner("offset", None))
        from . import shellext
        shell = shellext.desktop()
        if shellext.needed(shell) and not (shellext.installed(shell) and shellext.enabled(shell)):
            menu.addSeparator()
            menu.addAction("\U0001F5B1  Make it clickable on the panel").triggered.connect(
                self._install_panel_extension)

    def _install_panel_extension(self):
        from . import shellext
        self.say(shellext.install(), seconds=7)

    def _corner_arrange(self):
        """Drag the things into the order you like (live)."""
        from .arrange import ArrangeDialog
        from .home import home_config
        from .things.layout import order_of
        hc = home_config(self.store.config)
        dlg = ArrangeDialog(self.home, hc["side"], order_of(hc["order"]),
                            lambda order: self._set_corner("order", order))
        dlg.exec()

    def _corner_position(self):
        """A slider that slides the corner along the taskbar, live. (Dragging
        the things works too, except where the desktop keeps clicks on its
        panel for itself: Cinnamon and GNOME.)"""
        from PyQt6.QtWidgets import QDialogButtonBox, QLabel, QSlider, QVBoxLayout
        if not self.home.isVisible():
            return
        before = self.home.offset()
        right = (self.home._side == "right")
        dlg = QDialog()
        dlg.setWindowTitle("Corner position")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Slide PISI's corner along the taskbar to an empty spot."))
        sl = QSlider(Qt.Orientation.Horizontal)
        top = self.home.max_offset()
        sl.setRange(0, top)
        sl.setValue(top - before if right else before)   # the slider reads left to right
        sl.setMinimumWidth(360)
        self.sprite._drop_thing()
        sl.valueChanged.connect(lambda v: self.home.set_offset(top - v if right else v))
        lay.addWidget(sl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec():
            self._set_corner("offset", self.home.offset())
        else:
            self.home.set_offset(before)

    def _set_corner(self, key: str, value):
        h = dict(self.store.config.get("home") or {})
        if value is None:
            h.pop(key, None)
        else:
            h[key] = value
        h.pop("enabled", None)
        self.store.set_config("home", h)
        self._build_home()

    def _keep_on_top(self):
        from . import winapi
        for w in (self.sprite, self.home):
            if w.isVisible():
                winapi.keep_on_top(int(w.winId()))

    def _home_spot(self, kind: str):
        return self.home.spots.get(kind) if self.home.isVisible() else None

    def _home_clicked(self, kind: str):
        from .sprite import VISITS
        if self.focus.active() and self.focus.phase == "focus" and kind != "bed":
            return                           # napping through the focus block
        if kind == "basket" and self.sprite.can_play():
            self._fetch_from_basket()        # the toy basket: a toy out, and play
            return
        lo, hi = VISITS.get(kind, (4.0, 8.0))
        self.sprite.go_use(kind, hi)

    # ---- playing ---------------------------------------------------------------
    def _cat_fit(self):
        if self.home.fit is not None:
            return self.home.fit
        g = self._home_genome()
        if g is None:
            return None
        key = g.key()
        if self._fit_cache is None or self._fit_cache[0] != key:
            from .creatures import api
            from .things import fit as F
            self._fit_cache = (key, F.measure(api.Creature(g)))
        return self._fit_cache[1]

    def _toy_for(self, item_id: str):
        from .things import catalog
        from .things.kinds import KINDS
        it = catalog.BY_ID.get(item_id) or catalog.BY_ID["toy.mouse"]
        return KINDS["toy"].render(it.design, self._cat_fit())

    def _owned_toys(self) -> list[str]:
        from .things import catalog
        owned = self.store.config.get("owned") or [it.id for it in catalog.starter()]
        toys = [i for i in owned if i.startswith("toy.") and i in catalog.BY_ID]
        return toys or ["toy.mouse"]

    def throw_a_toy(self):
        import random
        self._stop_play()
        if self.playtime.start_toy(random.choice(self._owned_toys())):
            self.say("grab it and throw it! 🧶", seconds=5)

    def laser_play(self):
        if self.playtime.mode == "laser":
            self.playtime.stop()
            self.say(f"ok, no more laser {species.CAT.face}", seconds=4)
            return
        self._stop_play()
        if self.playtime.start_laser():
            self.say("ooh, a red dot!! 👀", seconds=4)

    def feather_wand(self):
        if self.playtime.mode == "wand":
            self.playtime.stop()
            return
        self._stop_play()
        if self.playtime.start_wand():
            self.say("the feather!! \U0001FAB6", seconds=4)

    def windup_mouse(self):
        self._stop_play()
        if self.playtime.start_hunt("toy.mouse"):
            self.say("a wind-up mouse! 🐭", seconds=4)

    def _fetch_for_break(self):
        """Break time: the cat gets a toy from the basket and brings it to you."""
        if self.focus.phase != "break":
            return
        self._fetch_from_basket(on_break=True)

    def _fetch_from_basket(self, on_break: bool = False):
        """The cat takes one of its toys out of the basket and play starts
        with the toy in its mouth (a click on the basket, or a break)."""
        import random
        if self.playtime.active() or self.unboxing.active() or not self.sprite.can_play():
            return
        item = random.choice(self._owned_toys())
        toy = self._toy_for(item)
        scale = self.sprite.pixel_scale()
        self._break_play = on_break
        self._basket_fetch = True
        if self.sprite.go_use("basket", 0.95):
            self.sprite.on_frame("pickup", 5, lambda: self.sprite.carry(toy, scale))

            def wait(n=0):
                if not self._basket_fetch or (on_break and self.focus.phase != "break"):
                    return
                if self.sprite.using() is None and self.sprite.state not in ("hop", "fall"):
                    self._basket_fetch = False
                    self.playtime.start_toy(item, carried=self.sprite.carrying() is not None,
                                            at_x=None)
                elif n < 200:
                    QTimer.singleShot(150, lambda: wait(n + 1))
            QTimer.singleShot(400, wait)
        else:
            self._basket_fetch = False
            self.playtime.start_toy(item)       # no basket: the toy just turns up

    def _put_toy_away(self) -> bool:
        """Carrying the toy back to the basket (False: no basket here)."""
        if self._home_spot("basket") is not None:
            if self.sprite.go_use("basket", 1.0, anim="drop"):
                self.sprite.on_frame("drop", 4, self.sprite.let_go)
                return True
        return False

    def _set_play_meter(self, on: bool):
        self.playtime.show_meter = on
        self.store.set_config("play_meter", on)
        if self.playtime.active():
            self.playtime._show_energy()

    def _play_note(self, what: str):
        if what == "dropped" and self._break_play and self.focus.phase == "break":
            self._break_play_prompted = getattr(self, "_break_play_prompted", 0) + 1
            if self._break_play_prompted == 1:
                self.say("play? grab the toy and throw it 🐾", seconds=8)
        elif what == "caught it!":
            self.say(f"caught it! {species.CAT.face}", seconds=4)
        elif what == "out of reach":
            self.say(f"I can't seem to reach it {species.CAT.cheeky}", seconds=6)
        elif what == "tired":
            self.say("pant pant… one more? 💦", seconds=6)

    def _play_ended(self, why: str):
        if why == "worn out":
            self.say("all played out… nap time 💤", seconds=6)
            if self._home_spot("bed") is not None:
                QTimer.singleShot(1500, lambda: self.sprite.go_use("bed", 90.0))
            return
        if why == "caught":
            self.say(f"got it! {species.CAT.face}", seconds=5)
        elif why == "bored":
            self.say(f"it got away {species.CAT.cheeky}", seconds=5)

    def _on_pet(self):
        self.say(self.brain.pet_reaction(), seconds=4)
        self.sprite.play_emote("love")
        for a in ("petted", "meow", "pounce", "jump"):   # a cute one-shot if the pack has it
            if self.sprite.do_anim(a):
                break

    def _maybe_chatter(self):
        import random
        if self._focus_dnd() or self._calendar_busy():   # quiet while busy
            return
        if self.focus.active():
            return                       # breaks get theirs as they start
        if time.monotonic() - self._last_care < CARE_EVERY_S:
            return
        if random.random() < 0.15:
            self._care()

    def _care(self):
        if self.sprite.bubble.isVisible() or self._fullscreen:
            return
        self._last_care = time.monotonic()
        self.say(self.brain.care_line(), seconds=7)

    def _on_bubble_click(self):
        act = self._bubble_action
        self._bubble_action = None
        if act == "focus":
            self.start_focus(self._bubble_focus_min)
        elif act == "plan":
            self.open_plan()
        elif act == "workspace":
            # open the habit's setup, and start its focus session if the nudge
            # offered one — click once, everything's up, timer's running
            hid = self._bubble_ws_habit
            self._bubble_ws_habit = None
            self._open_habit_workspace(hid)
            if self._bubble_focus_min:
                self.start_focus(self._bubble_focus_min)
        elif act == "setup":
            # PISI offered to remember this habit's tabs/files — open the editor
            hid = self._bubble_ws_habit
            self._bubble_ws_habit = None
            self.open_habit_setup(hid)

    def _open_habit_workspace(self, hid: str | None):
        ws = self.store.habit_workspace(hid) if hid else None
        if ws:
            actions.open_workspace(ws)

    def open_habit_setup(self, hid: str | None):
        """Open the setup editor for a habit (files + links), prefilled if it
        already has one, and save what the user assembles."""
        h = self.store.habit(hid) if hid else None
        if not h:
            return
        ws = h.get("workspace") or {}
        ed = WorkspaceEditor(
            title=f"Setup: {h['name']}", show_name=False,
            paths=ws.get("paths"), urls=ws.get("urls"), cmds=ws.get("cmds"),
            intro=f"Files, links and apps for {h['name']}. Open the tabs/files "
                  f"you want first, then “From open windows”. Next time it's "
                  f"{h['name']} time, one click opens them all.")
        if ed.exec():
            self.store.set_habit_workspace(hid, ed.paths, ed.urls, ed.cmds)
            if ed.paths or ed.urls or ed.cmds:
                self.say(f"got it, I'll open {h['name']}'s setup next time 🗂",
                         seconds=6)

    # ---- focus (pomodoro) sessions ----------------------------------
    def start_focus(self, minutes=None):
        self._stop_play()                     # can't chase a laser while focusing
        self.focus.start_focus(minutes)

    def _start_custom_focus(self):
        from PyQt6.QtWidgets import QInputDialog
        cur = int(self.store.config.get("focus_min", 25))
        mins, ok = QInputDialog.getInt(None, "Focus session",
                                       "Minutes to focus:", cur, 1, 180, 5)
        if ok:
            self.start_focus(mins)

    def stop_focus(self):
        self.focus.stop()

    def edit_pomodoro_count(self):
        """Let the user see / set / clear today's pomodoro tally. Clearing it
        also resets progress toward the next long break (same counter)."""
        cur = self.store.pomodoros_today()
        every = int(self.store.config.get("sessions_before_long", 4))
        dlg = PomodoroCountDialog(cur, every)
        if dlg.exec():
            self.store.set_pomodoros(dlg.count)
            self.focus.refresh_count()        # repaint the pill chip if active
            self.say(f"🍅 pomodoros today: {dlg.count}", seconds=4)

    def _set_presence(self, presence: str):
        self.store.set_config("presence", "out" if presence == "out" else "home")

    def open_plan(self):
        if not self.gcal.connected():
            self.say("connect Google Calendar in Settings and I'll plan with you 🗓",
                     seconds=6)
            return
        now = datetime.now()
        day = now.date().isoformat()
        day_start = now.replace(hour=0, minute=0, second=0,
                                microsecond=0).astimezone()
        day_end = day_start + timedelta(days=1)
        current = self.gcal.taken_keys(day_start, day_end)   # on the calendar now
        st = self.store.state
        written = set((st.get("pisi_written") or {}).get(day, []))
        dismissed = set((st.get("pisi_dismissed") or {}).get(day, []))
        # a block we wrote that's no longer there → you deleted it → don't re-offer
        deleted = written - current
        if deleted:
            dismissed |= deleted
            self.store.set_state("pisi_dismissed",
                                 {**(st.get("pisi_dismissed") or {}),
                                  day: sorted(dismissed)})
        items = self.planner.plan_items(now, current | dismissed)
        if not items:
            self.say("nothing left to plan, you're set for today 🐾", seconds=6)
            return
        load = self.planner.day_load(now)
        header = (f"A {load['level']} day · {load['free_min']} free min. "
                  "Reorder with ▲▼, nudge times, tick what you want, then add.")
        dlg = PlanDialog(self.calendar.today(), items,
                         lambda its: self.planner.pack(its, now), header,
                         free_slots=self.planner.free_slots(now, 30),
                         presence=self.planner.presence(),
                         set_presence_cb=self._set_presence,
                         cat_name=self.brain.name())
        if not dlg.exec():
            return
        n = 0
        added = set()
        for p in dlg.accepted:
            try:
                self.gcal.add_event(p["title"], p["start"].astimezone(),
                                    p["end"].astimezone(),
                                    description=p.get("reason", ""),
                                    key=p["key"], kind=p["kind"])
                added.add(p["key"])
                n += 1
            except Exception:              # noqa: BLE001
                log.warning("could not add plan block %r", p.get("key"),
                            exc_info=True)
        if added:
            self.store.set_state("pisi_written",
                                 {**(self.store.state.get("pisi_written") or {}),
                                  day: sorted(written | added)})
        self.say(f"added {n} block(s) to your PISI calendar ✨" if n
                 else "okay, nothing added 🐾", seconds=6)

    def _focus_reward(self):
        from . import shop
        before = self.store.treats()
        n = self.store.add_treats(1)
        self.sprite.play_emote("love")
        line = (f"done! You earned a {species.CAT.treat_name} "
                f"{species.CAT.treat}  ({n} saved) ✨")
        new = shop.just_affordable(self.store, before) if self._home_genome() is not None else None
        if new is not None:
            line += f"  that's enough for the {new.name}! \U0001F6CD"
        self.say(line, seconds=8)
        self._refresh_shop()

    def _log_focus_session(self, start, end):
        """Record a finished focus block on the PISI calendar (best effort)."""
        if not self.gcal.connected():
            return
        mins = max(1, round((end - start).total_seconds() / 60))
        key = f"{start.date().isoformat()}|focuslog|{start.strftime('%H%M')}"

        def work():
            try:
                self.gcal.add_event(f"✓ Focused {mins} min", start, end,
                                    description="Logged by PISI 🐾",
                                    key=key, kind="focuslog")
            except Exception:              # noqa: BLE001
                log.warning("could not log focus session", exc_info=True)
        threading.Thread(target=work, daemon=True).start()

    GUARD_HINT = ("Want me to guard a site while we focus? Open my browser "
                  "extension's menu on it and tick \"Guard my focus here\".")

    def _guard_hint(self) -> None:
        """Once ever: a focus block with the extension connected but no site
        guarded yet. Tell them the guard exists and where it's switched on."""
        cfg = self.store.config
        if (cfg.get("guard_hint_done") or self.web.guards_any is not False
                or not self.bridge.clients or self.sprite.surfaces is None
                or not (self.focus.phase == "focus" and not self.focus._paused)):
            return
        self.store.set_config("guard_hint_done", True)
        self.say(self.GUARD_HINT, seconds=10)

    def _on_focus_changed(self, phase: str):
        if phase == "focus":
            self.guard.new_block()                  # patience back to full
            QTimer.singleShot(8000, self._guard_hint)   # after "let's focus together"
        # a break is playtime: out of bed, a toy from the basket, brought to
        # you; about a minute in, a stretch or a glass of water
        if phase == "focus" and self.unboxing.active():
            self.unboxing._deliver(hurry=True)      # nap time: the parcel just opens
        if phase == "break" and self._unbox_queue:
            QTimer.singleShot(2500, self._next_unbox)   # bought during the block: unbox it now
        elif phase == "break":
            QTimer.singleShot(3500, self._fetch_for_break)
            QTimer.singleShot(60_000, lambda: self.focus.phase == "break" and self._care())
        elif self._break_play or self.playtime.active():
            # the break's over: tidy the toy back into the basket (or, if a
            # block has already started, just let it go)
            self._break_play = False
            if self.focus.active() and not getattr(self.focus, "_armed", False):
                self.playtime.stop(quiet=True)
                self.sprite.let_go()
            else:
                self.playtime.tidy(self._put_toy_away)

    def _focus_dnd(self) -> bool:
        """Quiet time: a focus block with DND on, or a fullscreen game/video."""
        if self._fullscreen:
            return True
        return self.focus.active() and bool(self.store.config.get("focus_dnd", True))

    # ---- calendar (read-only iCal) ----------------------------------
    def _calendar_busy(self) -> bool:
        """True while a timed calendar event is happening right now — used to
        keep the cat quiet during a lecture/meeting."""
        return self.calendar.ongoing_now() is not None

    def _event_line(self, e: dict) -> str:
        name = e.get("summary", "something")
        if e.get("all_day"):
            return name
        line = f"{name} at {fmt_time(e['start'])}"
        if e.get("location"):
            line += f" ({e['location']})"
        return line

    def today_summary(self) -> str | None:
        """A one-line rundown of today's schedule, or None if nothing's on."""
        evs = self.calendar.today()
        if not evs:
            return None
        timed = [e for e in evs if not e.get("all_day")]
        allday = [e for e in evs if e.get("all_day")]
        bits = [f"{e['summary']} {fmt_time(e['start'])}" for e in timed[:4]]
        bits += [f"{e['summary']} (all day)" for e in allday[:2]]
        return ", ".join(bits)

    def _calendar_tick(self, now: datetime):
        if not self.calendar.configured():
            return
        if self._focus_dnd() or self._calendar_busy():
            return                              # stay out of the way
        self._maybe_briefing(now)
        self._maybe_event_alerts(now)

    def _maybe_briefing(self, now: datetime):
        if self.store.state.get("last_briefing") == now.date().isoformat():
            return
        summary = self.today_summary()
        self.store.set_state("last_briefing", now.date().isoformat())
        if summary:
            if self.gcal.connected():
                # offer the consent-based day plan (tap the bubble)
                self.say(f"today: {summary}  ·  tap me to plan the day 🗓",
                         seconds=11, action="plan")
            else:
                gap = self.calendar.free_gap_minutes()
                tail = ""
                if gap is not None and gap >= 40:
                    tail = f"  ·  {gap} free min now. A focus block? 🌙"
                self.say(f"today: {summary}{tail}", seconds=10)

    def _maybe_event_alerts(self, now: datetime):
        soon = self.calendar.starting_within(EVENT_LEAD_MIN)
        if not soon:
            return
        day = now.date().isoformat()
        alerts = self.store.state.get("cal_alerts") or {}
        seen = set(alerts.get(day, []))
        fired = False
        for e in soon:
            key = f"{e['start'].isoformat()}|{e.get('summary','')}"
            if key in seen:
                continue
            mins = max(1, int((e["start"] - now).total_seconds() // 60))
            self.say(f"{self._event_line(e)}, in {mins} min 🐾", seconds=8)
            actions.notify("Coming up \U0001F43E", self._event_line(e))
            seen.add(key)
            fired = True
            break                               # one nudge per tick is plenty
        if fired:
            self.store.set_state("cal_alerts", {day: sorted(seen)})

    # ---- scheduler ---------------------------------------------------
    def _in_quiet_hours(self, now: datetime) -> bool:
        cfg = self.store.config
        try:
            qs = datetime.strptime(cfg.get("quiet_start", "23:00"), "%H:%M").time()
            qe = datetime.strptime(cfg.get("quiet_end", "08:00"), "%H:%M").time()
        except ValueError:
            return False
        t = now.time()
        if qs <= qe:
            return qs <= t < qe
        return t >= qs or t < qe          # wraps midnight

    def _scheduler_tick(self):
        now = datetime.now()
        # a background write may have found the Google token dead — tell the user
        # once so their focus sessions/plans start logging again after reconnect
        if self.gcal.expired or self.gcal.needs_reconnect():
            if not self._gcal_expiry_told:
                self._gcal_expiry_told = True
                self.say("my Google Calendar link needs a quick reconnect: Settings → "
                         "Google Calendar → Connect, and I'll log your focus sessions "
                         "again 🐾", seconds=10)
        else:
            self._gcal_expiry_told = False   # re-arm after a reconnect
        if self._in_quiet_hours(now):
            return
        self._calendar_tick(now)          # briefing + "coming up" nudges
        self._smart_tick(now)             # maybe a smart suggestion

    def _event_imminent(self, now: datetime) -> bool:
        """True if a timed event starts in the next few minutes — so we don't
        nudge right as you're about to head into a class/meeting."""
        return bool(self.calendar.starting_within(EVENT_LEAD_MIN)) \
            if self.calendar.configured() else False

    def _smart_tick(self, now: datetime):
        """At most one gentle, well-timed planner suggestion, with a cooldown."""
        if not self.store.config.get("smart_nudges", True):
            return
        if self._focus_dnd() or self._calendar_busy() or self._event_imminent(now):
            return
        if self.sprite.bubble.isVisible():
            return
        if (now - self._last_smart).total_seconds() < SMART_NUDGE_COOLDOWN_MIN * 60:
            return
        from .sysinfo import idle_ms
        idle = idle_ms()
        if idle is not None and idle > IDLE_DEFER_MS:
            return                        # only when you're actually around
        try:
            sugg = self.planner.suggest(now)
        except Exception:
            sugg = None
        if not sugg:
            return
        self._last_smart = now
        text = sugg["text"]
        action = sugg.get("action")
        # tie a habit's setup to its own nudge:
        hid = sugg.get("habit_id")
        if hid and self.store.habit_workspace(hid):
            # has a setup → one click opens it (keep any focus offer for after)
            self._bubble_ws_habit = hid
            action = "workspace"
            text += "  \U0001F5C2 click to open your setup"
        elif hid and self._should_offer_setup(hid):
            # no setup yet → gently offer to make one, at most once per habit
            self._bubble_ws_habit = hid
            action = "setup"
            text += "  \U0001F5C2 want me to open its tabs next time? click to set up"
            self._mark_setup_offered(hid)
        self.say(text, seconds=13, action=action, focus_min=sugg.get("minutes"))

    def _should_offer_setup(self, hid: str) -> bool:
        return should_offer_setup(self.store, hid)

    def _mark_setup_offered(self, hid: str) -> None:
        mark_setup_offered(self.store, hid)

    # ---- windows -----------------------------------------------------
    def open_manage(self):
        ManageDialog(self.store).exec()

    def open_pet_studio(self):
        """Non-modal: nudges and focus sessions keep going while it's open."""
        from .petstudio import PetStudio
        st = getattr(self, "_studio", None)
        if st is None or not st.isVisible():
            st = PetStudio(self.store)
            st.use_pet.connect(self._use_pet)
            self._studio = st
        st.show()
        st.raise_()
        st.activateWindow()
        return st

    def _use_pet(self, genome, baked):
        from .creatures import qt as cq
        if baked is not None:
            self.sprite.set_sheet(cq.sheet_from_baked(baked), self.store.config)
        else:
            self.sprite.load_sheet(self.store.config)
        self._apply_icon()
        self._build_home()
        self.sprite.play_emote("love")

    def reload_pet(self):
        """Re-read the pet from config (Studio, or another PISI process)."""
        self.store.refresh_from_disk(("pet_genome",))
        self.sprite.load_sheet(self.store.config)
        self._apply_icon()
        self._build_home()

    def _check_web_geometry(self) -> None:
        if self.sprite.surfaces is None or not self.web.active:
            return
        try:
            self.web_calib.check()
        except Exception:                    # noqa: BLE001 - a debugging aid, never fatal
            log.debug("web geometry check failed", exc_info=True)

    @staticmethod
    def _refresh_bridge() -> None:
        from . import bridge
        try:
            bridge.refresh()
        except Exception:  # noqa: BLE001 - never stop the cat over this
            log.warning("browser bridge refresh failed", exc_info=True)

    def _send_page_status(self) -> None:
        perch_on = self.sprite.surfaces is not None
        focusing = (self.focus.active() and self.focus.phase == "focus"
                    and not self.focus._paused and not self.focus._armed)
        self.guard.update(focusing and perch_on)
        known = self.web.guards_any                 # remembered for Settings' warning
        if known is not None and known != bool(self.store.config.get("guard_sites", False)):
            self.store.set_config("guard_sites", known)
        if self.bridge.clients:
            self.page_status.update(self.sprite._focus, perch_on, self.sprite._guarding)

    def _dig_page(self, x: int, y: int, w: int, facing: int) -> None:
        """The cat digs here: the extension flicks the words under its paws off."""
        bx, by = self.web.to_browser(x, y)
        bx1, _ = self.web.to_browser(x + w / 2, y)
        self.bridge.send({"type": "dig", "x": bx, "y": by, "w": max(8, 2 * (bx1 - bx)),
                          "dir": facing})

    def _knock_page(self, x: int, y: int, side: int) -> None:
        """The cat swatted the word at the end of its line: the extension tips it off."""
        bx, by = self.web.to_browser(x, y)
        self.bridge.send({"type": "knock", "x": bx, "y": by, "dir": side})

    def _from_browser(self, msg: dict) -> None:
        """Right-clicked on a page: "Throw PISI a toy here" / "Shine the laser here"."""
        if msg.get("type") != "play" or self.sprite.surfaces is None:
            return
        if self.focus.active() and self.focus.phase == "focus":
            self.say("after this focus block 🐾", seconds=3)
            return
        if msg.get("what") == "laser":
            if self.playtime.mode != "laser":
                self.laser_play()
            return
        import random
        try:
            x, y = self.web.to_screen(float(msg["x"]), float(msg["y"]))
        except (KeyError, TypeError, ValueError):
            x = y = None
        self._stop_play()
        if self.playtime.start_toy(random.choice(self._owned_toys()), at_x=x, drop_y=y):
            self.say("ooh! 🧶", seconds=3)

    def web_debug(self) -> str:
        """Snapshot what the pet sees on web pages (for `--web-debug`)."""
        import json
        from .paths import data_dir
        sp = self.sprite
        cx, feet = sp._feet()
        segs = self.web.segments()
        snap = {
            "active": self.web.active, "bridge_clients": self.bridge.clients,
            "scale": self.web.scale, "correction": self.web.correction,
            "view": self.web.view(), "tabs": len(self.web._tabs),
            "pet": {"x": sp.x(), "y": sp.y(), "feet": [cx, feet], "foot_offset": sp.foot_offset(),
                    "state": sp.state, "perched": sp._perched, "facing": sp.facing,
                    "surfaces_on": sp.surfaces is not None, "wander": sp.wander_enabled,
                    "screen": list(sp._screen_rect().getRect())},
            "segments": [[s.x0, s.x1, s.y, s.kind, s.block, s.row] for s in segs[:60]],
            "page_scale": sp._page_scale, "body": list(vars(sp._body()).values()),
            "metrics": self.web.metrics(), "window": self.web.window(),
            "ledges": [[round(s.x0), round(s.x1), round(s.y), s.kind, s.low]
                       for s in sp._segments()[:80]],
            "mood": sp._mood, "climbing": sp._climb is not None, "focus": sp._focus,
            "in_play": sp.in_play,
            "located": self.web.located,
            "boxes": [[round(b.x0), round(b.y0), round(b.x1), round(b.y1), b.kind]
                      for b in self.web.boxes()[:120]],
            "screens": [[q.name(), list(q.geometry().getRect()), q.devicePixelRatio()]
                        for q in QApplication.screens()],
            "tab_detail": [{"key": str(k), "segs": len(t["segs"]), "view": t["view"],
                            "meta": t.get("meta"),
                            "age_s": round(self.web._clock() - t["seen"], 1),
                            "focus_age_s": round(self.web._clock() - t["focused_at"], 1)}
                           for k, t in self.web._tabs.items()],
            "active_key": str(self.web._active),
        }
        out = data_dir() / "web-debug.json"
        out.write_text(json.dumps(snap, indent=1), encoding="utf-8")
        return str(out)

    def toggle_web_overlay(self):
        """Draw what the pet sees on web pages over the screen (debugging)."""
        from .webdebug import WebOverlay
        if getattr(self, "_web_overlay", None) is None:
            self._web_overlay = WebOverlay(self.web, self.sprite)
            self._web_overlay.start()
        else:
            self._web_overlay.stop()
            self._web_overlay = None

    def _apply_web_perch(self):
        """Walk on web pages (needs the browser extension) unless switched off."""
        on = bool(self.store.config.get("web_perch", True))
        self.sprite.surfaces = self.web if on else None
        self.sprite.web_fit = bool(self.store.config.get("web_fit", False))
        if not on:
            self.sprite._leave_surface()

    def open_feedback(self):
        from .feedback import FeedbackDialog
        FeedbackDialog().exec()

    def open_tutorial(self):
        name = self.store.config.get("cat_name", "PISI")
        actions = {"studio": self.open_pet_studio, "extension": self._set_up_extension}
        if self._home_genome() is not None and self.home.isVisible():
            actions["corner"] = self._corner_position
        tour = getattr(self, "_tour", None)
        if tour is not None and tour.isVisible():
            tour.raise_()
            tour.activateWindow()
            return
        self._tour = TutorialDialog(name, actions=actions)
        self._tour.show()
        self._tour.raise_()
        self._tour.activateWindow()

    def _set_up_extension(self) -> None:
        """Register the browser bridge, then open the extension's folder to
        load into the browser (the tutorial's "Set it up")."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtWidgets import QMessageBox
        from . import bridge
        try:
            done = bridge.install()
        except OSError as e:
            QMessageBox.warning(None, "Browser extension", f"Couldn't set it up: {e}")
            return
        if not done:
            QMessageBox.information(None, "Browser extension",
                                    "I couldn't find Chrome, Brave, Edge, Vivaldi or "
                                    "Firefox on this computer.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(bridge.extension_dir())))
        self.say(f"ready for {', '.join(done)}: load the folder I opened 🐾", seconds=8)

    def open_settings(self):
        if SettingsDialog(self.store, self.calendar, self.gcal,
                          open_pet_studio=self.open_pet_studio,
                          extension_connected=lambda: self.bridge.clients > 0).exec():
            cfg = self.store.config
            self.sprite.speed = float(cfg.get("speed", 2.0))
            self.sprite.set_wander(bool(cfg.get("wander", True)))
            self.sprite.load_sheet(cfg)
            self._apply_web_perch()
            self._apply_icon()
            self._build_home()
            self.calendar.refresh()          # pick up a new/changed iCal URL

    # ---- menu --------------------------------------------------------
    def _populate_menu(self, menu: QMenu):
        s = self.store

        # ---- daily zone: the handful of things you actually reach for ----
        # one-press "open everything for this habit" — front and centre so you
        # can sit down after a reboot and just launch your project
        setups = [h for h in s.habits if self.store.habit_workspace(h["id"])]
        if len(setups) == 1:
            h = setups[0]
            menu.addAction(f"\U0001F5C2  Open {h['name']}"
                           ).triggered.connect(
                lambda _=False, hid=h["id"]: self._open_habit_workspace(hid))
        elif setups:
            sm = menu.addMenu("\U0001F5C2  Open…")
            for h in setups:
                sm.addAction(f"{h.get('emoji','⭐')}  {h['name']}").triggered.connect(
                    lambda _=False, hid=h["id"]: self._open_habit_workspace(hid))

        fm = menu.addMenu("\U0001F345  Focus")     # 🍅 pomodoro
        if self.focus.active():
            phase = "break" if self.focus.phase == "break" else "focus"
            fm.addAction(f"⏹  Stop ({phase})").triggered.connect(self.stop_focus)
        else:
            default_len = int(s.config.get("focus_min", 25))
            fm.addAction(f"\U0001F31F  Start focus  ({default_len} min)"
                         ).triggered.connect(lambda: self.start_focus())
            for m in (15, 25, 50):
                if m != default_len:
                    fm.addAction(f"\U0001F55C  Focus {m} min"
                                 ).triggered.connect(lambda _=False, mm=m: self.start_focus(mm))
            fm.addAction("⚙  Custom…").triggered.connect(self._start_custom_focus)
        fm.addSeparator()
        done = self.store.pomodoros_today()
        fm.addAction(f"\U0001F345  Today: {done} done (edit…)"
                     ).triggered.connect(self.edit_pomodoro_count)

        if self.gcal.connected():
            menu.addAction("\U0001F5D3  Plan my day…").triggered.connect(self.open_plan)

        menu.addSeparator()

        self._populate_play(menu.addMenu("\U0001F3AE  Play"))

        # ---- treats ---------------------------------------------------
        treat = species.CAT.treat
        menu.addAction(f"{treat}  Give a treat").triggered.connect(self.give_treat)
        if self._home_genome() is not None:
            menu.addAction(f"\U0001F6CD  Shop…   {treat} {s.treats()}").triggered.connect(
                self.open_shop)

        # ---- everything else, tucked into one "More" submenu ------------
        menu.addSeparator()
        self._populate_more(menu.addMenu("⋯  More"))

        menu.addAction("⚙  Settings").triggered.connect(self.open_settings)
        menu.addSeparator()
        menu.addAction("❌  Quit").triggered.connect(self.app.quit)

    def _populate_play(self, play: QMenu):
        if self.sprite.can_play():
            play.addAction("\U0001F9F6  Throw a toy").triggered.connect(self.throw_a_toy)
            wand = "\U0001FAB6  Put the wand away" if self.playtime.mode == "wand" \
                else "\U0001FAB6  Feather wand"
            play.addAction(wand).triggered.connect(self.feather_wand)
            laser = "\U0001F534  Stop the laser" if self.playtime.mode == "laser" \
                else "\U0001F534  Laser pointer"
            play.addAction(laser).triggered.connect(self.laser_play)
            play.addAction("\U0001F42D  Wind-up mouse").triggered.connect(self.windup_mouse)
            play.addSeparator()
            meter = play.addAction("\U0001F535  Show energy while playing")
            meter.setCheckable(True)
            meter.setChecked(self.playtime.show_meter)
            meter.toggled.connect(self._set_play_meter)
            if self.playtime.active():
                play.addAction("⏹  Stop playing").triggered.connect(self._stop_play)
            return
        play.addAction("(the cat couldn't be drawn: see --doctor)").setEnabled(False)

    def _populate_more(self, more: QMenu):
        """The long tail: play, wandering, help."""
        more.addAction("\U0001F4C1  Manage habits…").triggered.connect(self.open_manage)

        more.addSeparator()
        label = "⏸  Pause wandering" if self.sprite.wander_enabled else "▶  Resume wandering"
        more.addAction(label).triggered.connect(self._toggle_wander)
        more.addAction("\U0001F43E  Come here").triggered.connect(
            lambda: self.sprite.come_to(QCursor.pos()))

        if self._home_genome() is not None:
            self._populate_corner(more.addMenu("\U0001F3E0  Corner"))

        more.addSeparator()
        more.addAction("\U0001F43E  Pet Studio…").triggered.connect(self.open_pet_studio)
        more.addAction("\U0001F393  Show tutorial").triggered.connect(self.open_tutorial)
        more.addAction("\U0001F41E  Report a bug or get in touch\u2026").triggered.connect(self.open_feedback)

    def show_menu(self, global_pos: QPoint):
        menu = QMenu()
        self._populate_menu(menu)
        menu.exec(global_pos)

    def _toggle_wander(self):
        new = not self.sprite.wander_enabled
        self.sprite.set_wander(new)
        self.store.set_config("wander", new)

    # ---- treats ------------------------------------------------------
    def give_treat(self):
        """Treats from the menu are free (the saved ones are for the shop):
        the cat trots to its bowl for it, if it has one."""
        sp = species.CAT
        now = time.time()
        if now - float(self.store.state.get("last_treat_at", 0)) < TREAT_COOLDOWN_S:
            self.say(f"I'm full {sp.face}  maybe later", seconds=4)
            self.sprite.do_anim("tailswish")
            return
        self.store.set_state("last_treat_at", now)
        self.sprite.play_emote("love")
        napping = self.focus.active() and self.focus.phase == "focus"
        if (not napping and not self.playtime.active() and not self.unboxing.active()
                and self._home_spot("bowl") is not None and self.sprite.go_use("bowl", 4.0)):
            self.say(f"ooh, a {sp.treat_name} {sp.treat}", seconds=4)
            return
        if not self.sprite.do_anim("eat", seconds=2.0):
            self.sprite.do_anim("meow", seconds=1.2)
        self.say(f"nom nom {sp.face}", seconds=4)

    # ---- the shop -------------------------------------------------------------------
    def open_shop(self):
        g = self._home_genome()
        fit = self._cat_fit() if g is not None else None
        if fit is None or not self.sprite.can_play():
            self.say("the shop is for your own cat \U0001F43E  make one in Pet Studio", seconds=6)
            return
        from .shopwindow import ShopWindow
        key = (g.key(), id(self.sprite.sheet))
        if self.shop_win is None or self._shop_key != key:     # a different cat: redraw it all
            if self.shop_win is not None:
                self.shop_win.close()
                self.shop_win.deleteLater()
            self.shop_win = ShopWindow(self.store, self.sprite.sheet, fit, species.CAT.treat,
                                       self._shop_buy, self._shop_place)
            self._shop_key = key
        self.shop_win.arriving = {it.id for it in self._unbox_queue}
        if self.unboxing.active():
            self.shop_win.arriving.add(self.unboxing.item.id)
        self.shop_win.show()
        self.shop_win.raise_()
        self.shop_win.activateWindow()

    def _refresh_shop(self):
        if self.shop_win is not None and self.shop_win.isVisible():
            self.shop_win.refresh()

    def _render_item(self, it):
        from .things.kinds import KINDS
        return KINDS[it.kind].render(it.design, self._cat_fit())

    def _place_item(self, it):
        from . import shop
        shop.place(self.store, it.kind, it.id)
        self._build_home()
        self._refresh_shop()

    def _shop_place(self, kind: str, item_id):
        from . import shop
        shop.place(self.store, kind, item_id)
        self._build_home()

    def _shop_buy(self, it) -> bool:
        """Pay for it, then the parcel: now, or after the focus block (the
        cat is napping), or after the parcel that's already being opened."""
        from . import shop
        if not shop.buy(self.store, it.id):
            return False
        napping = self.focus.active() and self.focus.phase == "focus"
        if napping or self.unboxing.active() or self._unbox_queue:
            self._unbox_queue.append(it)
        else:
            self._unbox(it)
        return True

    def _unbox(self, it):
        self._stop_play()
        self._break_play = False
        if not self.unboxing.start(it):            # no rig to unbox with: just deliver it
            if it.kind != "toy":
                self._place_item(it)
            self.say(f"the {it.name} is here \u2728", seconds=5)
            self._unboxed(it.id)

    def _unboxed(self, item_id: str):
        if self.shop_win is not None:
            self.shop_win.arrived(item_id)
        if self._unbox_queue:
            QTimer.singleShot(9000, self._next_unbox)   # let it enjoy this one first

    def _next_unbox(self):
        if not self._unbox_queue or self.unboxing.active():
            return
        if self.focus.active() and self.focus.phase == "focus":
            return                                  # after this block
        self._unbox(self._unbox_queue.pop(0))

    # ---- play ---------------------------------------------------------
    def _stop_play(self):
        if hasattr(self, "playtime") and self.playtime.active():
            self.playtime.stop(quiet=True)
            self.sprite.let_go()

    # ---- tray --------------------------------------------------------
    def _icon_pixmap(self) -> QPixmap:
        """The launcher/tray pixmap: the cat on a beige tile so it never
        disappears against a dark theme (see _on_tile)."""
        pm = _pixmap_from_sheet(self.sprite.sheet)
        if pm is not None:
            return _on_tile(pm)
        return _make_icon("#e8943a").pixmap(128, 128)

    def _current_icon(self) -> QIcon:
        return QIcon(self._icon_pixmap())

    def _apply_icon(self):
        pm = self._icon_pixmap()
        icon = QIcon(pm)
        self.app.setWindowIcon(icon)
        self.sprite.setWindowIcon(icon)
        if hasattr(self, "tray"):
            self.tray.setIcon(icon)
        try:
            path = data_dir() / "icon.png"
            pm.save(str(path), "PNG")
            self._update_desktop_icons(str(path))
        except Exception:
            log.warning("could not write launcher icon", exc_info=True)

    def _update_desktop_icons(self, icon_path: str):
        import os
        files = [
            os.path.expanduser("~/.config/autostart/desktop-companion.desktop"),
            os.path.expanduser("~/.local/share/applications/desktop-companion.desktop"),
        ]
        for f in files:
            if not os.path.exists(f):
                continue
            try:
                lines = open(f, encoding="utf-8").read().splitlines()
                out = [("Icon=" + icon_path) if ln.startswith("Icon=") else ln
                       for ln in lines]
                open(f, "w", encoding="utf-8").write("\n".join(out) + "\n")
            except OSError:
                pass

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self._current_icon())
        self.tray.setToolTip(f"{self.brain.name()}, your desktop cat")
        menu = QMenu()
        self._populate_menu(menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if sys.platform == "darwin":
            return      # macOS already opens the context menu on click; don't double it
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # rebuild the menu fresh (state may have changed) and pop it
            menu = QMenu()
            self._populate_menu(menu)
            menu.exec(QCursor.pos())
