"""Pomodoro-style focus sessions, themed around the cat.

While you focus, the cat curls up and naps alongside you (its pose deepens as
the block runs down — see ``CatSprite.focus_pose``). A small "curl-ring" pill
floats near it with the exact time left. When the block completes the cat wakes,
stretches, sparkles, and you bank a treat. Breaks are gentle and optional.

Nothing here nags: transitions are soft invitations, in keeping with the rest of
the app's tone.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from PyQt6.QtCore import (QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer,
                          pyqtSignal)
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from . import chime


# ---------------------------------------------------------------------------
class _Face(QWidget):
    """The painted part of the pill: the progress ring + a moon (focus) or sun
    (break) glyph + the remaining time. During focus it also draws little pips
    showing how far you are through the long-break cycle — so a glance tells you
    whether the next break is short or long. On a break, a *bigger, gold* sun
    marks a long break vs. the small green sun of a short one."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(96, 38)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._frac = 1.0
        self._label = "25:00"
        self._phase = "focus"          # focus | break
        self._paused = False
        self._long = False             # break: this break is long / focus: next is
        self._pips = (0, 0)            # (blocks done this cycle, cycle length)

    def set_state(self, frac, label, phase, paused, long, pips) -> None:
        self._frac = max(0.0, min(1.0, frac))
        self._label, self._phase, self._paused = label, phase, paused
        self._long, self._pips = long, pips
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        on_break = self._phase == "break"
        if on_break:
            accent = QColor(226, 168, 58) if self._long else QColor(90, 170, 110)
        else:
            accent = QColor(232, 148, 58)
        if self._paused:
            accent = QColor(150, 150, 155)
        R = 14
        cx, cy = R + 3, h // 2
        ring = QRect(cx - R, cy - R, 2 * R, 2 * R)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 30), 4.0))
        p.drawEllipse(ring)
        pen = QPen(accent, 4.0); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(ring, 90 * 16, -int(360 * 16 * self._frac))
        if on_break:
            self._sun(p, cx, cy, 8 if self._long else 5, accent)
        else:
            self._moon(p, cx, cy, 7, QColor(120, 120, 150))

        tx = cx + R + 4
        show_pips = (not on_break) and self._pips[1] > 1
        # time — sits a touch higher when pips share the row
        p.setPen(QColor(50, 50, 58))
        f = QFont(); f.setPointSize(13); f.setBold(True); p.setFont(f)
        p.drawText(QRect(tx, 0, self.width() - tx, h - (10 if show_pips else 0)),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   self._label)
        if show_pips:
            self._draw_pips(p, tx, h)
        p.end()

    def _draw_pips(self, p, tx, h) -> None:
        filled, total = self._pips
        long_next = filled >= total - 1        # this block leads into a long break
        base = QColor(226, 168, 58) if long_next else QColor(232, 148, 58)
        r, gap, y = 2, 7, h - 5
        for i in range(total):
            cxp = tx + 2 + i * gap + r
            if i < filled:                      # a block already banked this cycle
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(base)
            elif i == filled and long_next:     # the current block → gold ring
                p.setPen(QPen(base, 1.3)); p.setBrush(Qt.BrushStyle.NoBrush)
            else:                               # still to come
                p.setPen(QPen(QColor(0, 0, 0, 45), 1.0)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPoint(cxp, y), r, r)

    def _moon(self, p, cx, cy, r, col):
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
        p.drawEllipse(QPoint(cx, cy), r, r)
        p.setBrush(QColor(255, 253, 245, 255))
        p.drawEllipse(QPoint(cx + r // 2 + 1, cy - 1), r, r)

    def _sun(self, p, cx, cy, r, col):
        p.setPen(QPen(col, 2.0))
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(int(cx + math.cos(a) * (r + 2)), int(cy + math.sin(a) * (r + 2)),
                       int(cx + math.cos(a) * (r + 5)), int(cy + math.sin(a) * (r + 5)))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
        p.drawEllipse(QPoint(cx, cy), r, r)


_BTN_CSS = """
QPushButton { border:none; border-radius:13px; background:rgba(0,0,0,0.06);
              color:#3a3a42; font-size:13px; }
QPushButton:hover { background:rgba(0,0,0,0.14); }
QPushButton:pressed { background:rgba(0,0,0,0.22); }
"""

_CHIP_CSS = """
QPushButton { border:none; border-radius:13px; background:rgba(232,148,58,0.16);
              color:#3a3a42; font-size:12px; font-weight:600; }
QPushButton:hover { background:rgba(232,148,58,0.30); }
QPushButton:pressed { background:rgba(232,148,58,0.42); }
"""


class _IconBtn(QPushButton):
    """A round control button whose glyph is painted by hand, so it's perfectly
    centred (font media-control glyphs render off-centre and inconsistently)."""

    def __init__(self, kind: str, tip: str) -> None:
        super().__init__()
        self._kind = kind
        self.setFixedSize(26, 26)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(_BTN_CSS)

    def set_kind(self, kind: str) -> None:
        if kind != self._kind:
            self._kind = kind
            self.update()

    def paintEvent(self, e) -> None:
        super().paintEvent(e)                     # the styled round background
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.width() / 2                       # square button → same for y
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(58, 58, 66))
        k = self._kind
        if k == "pause":
            p.drawRoundedRect(QRectF(c - 4, c - 5, 3, 10), 1, 1)
            p.drawRoundedRect(QRectF(c + 1, c - 5, 3, 10), 1, 1)
        elif k == "play":
            p.drawPolygon(QPolygonF([QPointF(c - 3.5, c - 5),
                                     QPointF(c - 3.5, c + 5), QPointF(c + 4.5, c)]))
        elif k == "skip":
            p.drawPolygon(QPolygonF([QPointF(c - 5, c - 4.5),
                                     QPointF(c - 5, c + 4.5), QPointF(c + 1.5, c)]))
            p.drawRoundedRect(QRectF(c + 2.5, c - 4.5, 2.4, 9), 1, 1)
        elif k == "stop":
            p.drawRoundedRect(QRectF(c - 4.5, c - 4.5, 9, 9), 1.6, 1.6)
        p.end()


class FocusPill(QWidget):
    """A small floating control bar near the cat: progress ring + time, plus
    pause/resume, skip, and stop buttons — so you can drive a session without
    the tray menu."""

    H = 46
    pauseToggled = pyqtSignal()
    skipClicked = pyqtSignal()
    stopClicked = pyqtSignal()
    countClicked = pyqtSignal()
    moved = pyqtSignal(QPoint)           # you dragged it here (its new top-left)
    unpinned = pyqtSignal()              # "Back beside PISI"

    def __init__(self) -> None:
        super().__init__(None)
        self._press = None              # (global press point, pill pos) while dragging
        self._dragged = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # macOS hides "tool" windows whenever another app is active — keep it up
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)
        # today's pomodoro tally — click to edit / clear
        self.btn_count = QPushButton("🍅 0")
        self.btn_count.setFixedSize(46, 26)
        self.btn_count.setToolTip("Pomodoros today: click to edit or clear")
        self.btn_count.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_count.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_count.setStyleSheet(_CHIP_CSS)
        self.btn_count.clicked.connect(self.countClicked)
        lay.addWidget(self.btn_count)
        self._face = _Face()
        lay.addWidget(self._face)
        self.btn_pause = _IconBtn("pause", "Pause / resume")
        self.btn_skip = _IconBtn("skip", "Skip to the next phase (focus ⇄ break)")
        self.btn_stop = _IconBtn("stop", "End the whole session")
        self.btn_pause.clicked.connect(self.pauseToggled)
        self.btn_skip.clicked.connect(self.skipClicked)
        self.btn_stop.clicked.connect(self.stopClicked)
        for b in (self.btn_pause, self.btn_skip, self.btn_stop):
            lay.addWidget(b)
        # chip 46 + face 96 + 3 buttons·26 + spacing/margins
        self.setFixedSize(8 + 46 + 96 + 3 * 26 + 4 * 4 + 8, self.H)

    def set_state(self, frac, label, phase, paused=False, count=0,
                  long=False, pips=(0, 0)) -> None:
        self.btn_pause.set_kind("play" if paused else "pause")
        self.btn_count.setText(f"🍅 {count}")
        self._face.set_state(frac, label, phase, paused, long, pips)
        self.setToolTip(self._summary(phase, long, pips))

    @staticmethod
    def _summary(phase, long, pips) -> str:
        if phase == "break":
            kind = "Long break" if long else "Short break"
            return f"{kind}  ·  ⏭ next focus  ·  ⏹ end session"
        filled, total = pips
        if total > 1:
            if filled >= total - 1:
                nxt = "long break next"
            else:
                left = total - 1 - filled
                nxt = f"{left} more block{'s' if left != 1 else ''} → long break"
            return f"Focus  ·  {nxt}  ·  ⏭ break  ·  ⏹ end session"
        return "Focus  ·  ⏭ break  ·  ⏹ end session"

    def place_near(self, anchor: QRect) -> None:
        """Sit beside the cat (never overlapping it or the taskbar); tuck above
        only if there's no room on either side."""
        w, h = self.width(), self.height()
        scr = (QApplication.screenAt(anchor.center())
               or self.screen() or QApplication.primaryScreen())
        from .screens import usable
        g = usable(scr) if scr else anchor
        y = anchor.bottom() - h
        y = max(g.top() + 4, min(y, g.bottom() - h - 4))
        gap = 8
        if anchor.right() + gap + w <= g.right() - 4:
            x = anchor.right() + gap
        elif anchor.left() - gap - w >= g.left() + 4:
            x = anchor.left() - gap - w
        else:
            x = anchor.center().x() - w // 2
            y = max(g.top() + 4, anchor.top() - h - 6)
        x = max(g.left() + 4, min(x, g.right() - w - 4))
        self.move(int(x), int(y))

    def place_at(self, top_left: QPoint) -> None:
        """At a spot of your choosing, kept on a screen (screens change)."""
        from .screens import usable
        w, h = self.width(), self.height()
        scr = QApplication.screenAt(top_left + QPoint(w // 2, h // 2)) or QApplication.primaryScreen()
        g = usable(scr) if scr else QRect(top_left, self.size())
        x = max(g.left() + 4, min(top_left.x(), g.right() - w - 4))
        y = max(g.top() + 4, min(top_left.y(), g.bottom() - h - 4))
        self.move(int(x), int(y))

    # ---- drag it anywhere by its body (the buttons still click) ----------------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = (e.globalPosition().toPoint(), self.pos())
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:
        if self._press is None:
            return
        start, pos = self._press
        d = e.globalPosition().toPoint() - start
        if not self._dragged and d.manhattanLength() < 4:
            return
        self._dragged = True
        self.move(pos + d)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        self._press = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._dragged:
            self.place_at(self.pos())           # (not half off a screen)
            self.moved.emit(self.pos())

    def contextMenuEvent(self, e) -> None:
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Back beside PISI").triggered.connect(self.unpinned)
        menu.exec(e.globalPos())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(60, 60, 70, 90), 1.0))
        p.setBrush(QColor(255, 253, 245, 245))
        p.drawRoundedRect(1, 1, w - 2, h - 2, h // 2, h // 2)
        p.end()


# ---------------------------------------------------------------------------
class FocusController(QObject):
    """Drives a focus/break cycle: the pill, the cat's nap pose, transition
    messages and the treat reward. Kept UI-agnostic via a ``say`` callback so
    the orchestrator stays lean."""

    # emitted on any phase change so the app can toggle do-not-disturb etc.
    changed = pyqtSignal(str)          # "focus" | "break" | "idle"

    def __init__(self, sprite, store, say, on_reward=None, on_complete=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.sprite = sprite
        self.store = store
        self._say = say
        self._on_reward = on_reward
        self._on_complete = on_complete      # (start, end) when a focus block ends
        self.pill = FocusPill()
        self.pill.pauseToggled.connect(self.toggle_pause)
        self.pill.skipClicked.connect(self.skip)
        self.pill.stopClicked.connect(self.stop)
        self.pill.moved.connect(lambda pt: self.store.set_config("pill_pos", [pt.x(), pt.y()]))
        self.pill.unpinned.connect(self._unpin_pill)

        self.phase = "idle"            # idle | focus | break
        self._total = 0.0              # seconds in the current phase
        self._left = 0.0               # seconds remaining
        self._paused = False
        self._armed = False            # a focus block is queued & paused, waiting
                                       # for a manual ▶ (post-break, no auto-cycle)
        self._break_long = False       # is the *current* break a long one?
        self._focus_min = None         # the session's chosen focus length (a custom
                                       # one sticks for every block until Stop);
                                       # None = fall back to the config default
        self._session_start = None     # wall-clock start of the current focus

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

    # ---- config helpers ---------------------------------------------
    def _cfg(self, key, default):
        try:
            return self.store.config.get(key, default)
        except Exception:            # noqa: BLE001
            return default

    def _focus_minutes(self) -> float:
        """The focus length to use now: the session's chosen one if a custom
        block is running, else the config default. This is what keeps a custom
        30-min pomodoro from reverting to 25 after the first break."""
        if self._focus_min is not None:
            return self._focus_min
        return float(self._cfg("focus_min", 25))

    def active(self) -> bool:
        return self.phase != "idle"

    # ---- lifecycle ---------------------------------------------------
    def start_focus(self, minutes: float | None = None) -> None:
        if minutes is not None:
            self._focus_min = float(minutes)   # remember it for the whole session
        mins = self._focus_minutes()
        self._begin("focus", mins)
        self._say(f"let's focus together 🌙  ({int(mins)} min). "
                  "I'll curl up right here.", seconds=6)

    def start_break(self, long: bool = False) -> None:
        mins = float(self._cfg("long_break_min", 15) if long
                     else self._cfg("break_min", 5))
        self._break_long = long
        self._begin("break", mins)
        self.sprite.end_focus()            # out of the nap: pages and toys are back
        self.sprite.wake_stretch()
        self._say(("nice long stretch, we earned it ☀️" if long
                   else "break time ☀️ Stretch with me?"), seconds=6)

    def stop(self, quiet: bool = False) -> None:
        was = self.phase
        self.phase = "idle"
        self._paused = False
        self._armed = False
        self._focus_min = None         # a fresh session starts from the config default
        # NB: the daily pomodoro count is *not* cleared on stop — it's a real
        # tally of the day's work (store.pomodoros_today) and resets at midnight.
        self._timer.stop()
        self.pill.hide()
        self.sprite.end_focus()
        self.changed.emit("idle")
        if was == "focus" and not quiet:
            self._say("stopped for now. I'm here whenever 🐾", seconds=5)

    def toggle_pause(self) -> None:
        if not self.active():
            return
        if self._armed:
            # a focus block is queued after a break — ▶ actually *starts* it now
            self._start_armed()
            return
        self._paused = not self._paused
        if self._paused:
            self._timer.stop()
            if self.phase == "focus":
                # nothing to nap through while the clock's stopped: up it gets
                self.sprite.wake_stretch()
                self.sprite.end_focus()
        else:
            self._timer.start()
            if self.phase == "focus":
                self.sprite.begin_focus()      # back to its nap (the pose catches up next tick)
        self._update_pill()

    def skip(self) -> None:
        """Jump to the next phase — it does *not* end the session (that's ⏹ Stop).

        Skipping a focus early is honest: it logs the actual time worked but
        grants no treat (it wasn't a full block), then starts a short break.
        Skipping a break just moves straight on to the next focus block."""
        if self.phase == "focus":
            self._timer.stop()
            self._paused = False
            self._report_complete()
            self.sprite.wake_stretch()
            self.start_break(long=False)
        elif self.phase == "break":
            self.sprite.end_focus()        # tidy the break pose before re-curling
            self.start_focus()             # straight back to work, session intact

    def _begin(self, phase: str, minutes: float) -> None:
        self.phase = phase
        self._paused = False
        self._armed = False
        self._total = max(1.0, minutes * 60.0)
        self._left = self._total
        if phase == "focus":
            self._session_start = datetime.now().astimezone()
            self.sprite.begin_focus()
        self._update_pill()
        self._show_pill()
        self.pill.raise_()
        self._timer.start()
        self.changed.emit(phase)

    def _arm_next_focus(self) -> None:
        """Queue the next focus block but leave it *paused*, waiting for a manual
        ▶ press. The pill stays put (cat awake, ring full, play button showing) so
        resuming is one click — but nothing runs, and no sounds fire, while you're
        away from the desk. This is the default post-break behaviour."""
        mins = self._focus_minutes()        # keep the session's custom length
        self.phase = "focus"
        self._armed = True
        self._paused = True
        self._break_long = False
        self._session_start = None          # not started until you press ▶
        self._total = max(1.0, mins * 60.0)
        self._left = self._total
        self.sprite.end_focus()             # cat sits up, awake, waiting for you
        self._update_pill()
        self._show_pill()
        self.pill.raise_()
        self.changed.emit("focus")
        self._say("break's over 🌙 Press ▶ when you're ready to dive back in.",
                  seconds=8)

    def _start_armed(self) -> None:
        """Kick off the focus block that was waiting after a break."""
        self._armed = False
        self._paused = False
        self._session_start = datetime.now().astimezone()
        self.sprite.begin_focus()
        self._update_pill()
        self._timer.start()

    # ---- per-tick ----------------------------------------------------
    def _tick(self) -> None:
        self._left -= 0.5
        elapsed = self._total - self._left
        if self.phase == "focus":
            self.sprite.focus_pose(min(1.0, elapsed / self._total))
        self._update_pill()
        if self._left <= 0:
            self._finish_phase()

    def _cycle_info(self) -> tuple[bool, tuple[int, int]]:
        """(is-long, (blocks-done-this-cycle, cycle-length)) for the pill.

        On a break, ``is-long`` reflects the break you're in. On focus, it means
        the block you're doing now will roll into a long break, and the pips show
        how many blocks of the cycle are banked."""
        every = int(self._cfg("sessions_before_long", 4))
        if self.phase == "break":
            return self._break_long, (0, 0)
        if every <= 0:                          # long breaks disabled
            return False, (0, 0)
        filled = self._pomodoros_today() % every
        return (filled == every - 1), (filled, every)

    def _update_pill(self) -> None:
        frac = max(0.0, self._left / self._total) if self._total else 0.0
        secs = max(0, int(math.ceil(self._left)))
        label = f"{secs // 60:d}:{secs % 60:02d}"
        long, pips = self._cycle_info()
        self.pill.set_state(frac, label, self.phase, paused=self._paused,
                            count=self._pomodoros_today(), long=long, pips=pips)

    def _show_pill(self) -> None:
        """Placed once when it appears (not following the cat about: the cat
        naps in its bed down in the corner, and the pill would go too): where
        you last put it, or beside the cat. Stays put while it's up."""
        if not self.pill.isVisible():
            saved = self._cfg("pill_pos", None)
            if isinstance(saved, (list, tuple)) and len(saved) == 2:
                self.pill.place_at(QPoint(int(saved[0]), int(saved[1])))
            else:
                self.pill.place_near(self.sprite.body_anchor())
        self.pill.show()

    def _unpin_pill(self) -> None:
        self.store.set_config("pill_pos", None)
        self.pill.place_near(self.sprite.body_anchor())

    def _pomodoros_today(self) -> int:
        try:
            return self.store.pomodoros_today()
        except Exception:            # noqa: BLE001
            return 0

    def refresh_count(self) -> None:
        """Repaint the pill's 🍅 count (e.g. after the user edits it)."""
        if self.active():
            self._update_pill()

    def _play_alert(self, which: str) -> None:
        """Sound the end of a phase — the pet's own voice, a chime, whatever's set."""
        key = self._cfg("focus_sound" if which == "focus" else "break_sound",
                        "voice" if which == "focus" else "bowl")
        chime.play(key, int(self._cfg("sound_volume", 70)))

    def _report_complete(self) -> None:
        """Hand a finished (or skipped) focus block to ``on_complete`` measured by
        its *actual ticked focus time*, not wall-clock.

        The countdown timer freezes while the machine is suspended or the block
        is paused, so ``now - session_start`` can be wildly larger than the work
        that really happened (a block left running overnight once logged 670 min).
        ``_total - _left`` is the time that actually ticked down — capped at the
        block length — so we log that, ending at completion time."""
        if not (self._on_complete and self._session_start):
            return
        focused = max(0.0, self._total - self._left)
        if focused < 60:                      # under a minute isn't worth logging
            return
        end = datetime.now().astimezone()
        start = end - timedelta(seconds=focused)
        try:
            self._on_complete(start, end)
        except Exception:                     # noqa: BLE001 - never break the flow
            pass

    def _finish_phase(self) -> None:
        self._timer.stop()
        if self.phase == "focus":
            self._play_alert("focus")
            done = self.store.bump_pomodoro()      # persistent, daily, →midnight
            self.sprite.wake_stretch(celebrate=True)
            self._report_complete()
            reward = bool(self._cfg("focus_reward_treat", True))
            if reward and self._on_reward:
                self._on_reward()          # bank a treat + celebratory line
            else:
                self._say("done! Lovely focusing with you 🐾✨", seconds=6)
            # roll into a break? a long one every Nth pomodoro of the day
            if self._cfg("focus_autostart_breaks", True):
                every = int(self._cfg("sessions_before_long", 4))
                long = every > 0 and done % every == 0
                QTimer.singleShot(1500, lambda: self.start_break(long=long))
            else:
                self.stop(quiet=True)
        else:  # break finished
            self._play_alert("break")
            if self._cfg("focus_autostart_focus", False):
                # opt-in: keep cycling unattended, straight into the next block
                self.sprite.end_focus()
                self._say("back to it 🌙 Next block starting…", seconds=4)
                QTimer.singleShot(1500, self.start_focus)
            else:
                # default: pause and wait for a manual ▶ so nothing keeps
                # running (and dinging) while you're away
                self._arm_next_focus()
