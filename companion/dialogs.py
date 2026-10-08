"""The interactive windows: Plan my day, habits and their setups, settings,
the tutorial and the focus count. Each operates directly on the Store and saves as it goes.
"""
from __future__ import annotations

from datetime import timedelta

from PyQt6.QtCore import Qt, QTime, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                             QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QFrame, QGroupBox, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
                             QScrollArea, QSlider, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

import os
import re
import sys

from . import autostart, species, windows
from .store import Store

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
# an example launch command that makes sense on this OS
CMD_EXAMPLE = (r"code C:\dev\my-project" if IS_WINDOWS
               else "open -a Spotify" if IS_MAC else "code ~/dev/my-project")


def _hm(dt) -> str:
    return f"{dt.hour}:{dt.minute:02d}"   # %-H is glibc-only (crashes on Windows)


def _as_item(text: str) -> tuple[str, str] | None:
    """Classify a snapshot row's text into ('file', path) or ('url', url), or
    None if it's just an app title that can't be opened."""
    t = text.strip()
    if not t:
        return None
    if t.startswith(("http://", "https://")) or "://" in t:
        return ("url", t)
    if (t.startswith(("/", "~")) or re.match(r"^[a-zA-Z]:[\\/]|^\\\\", t)
            or os.path.exists(os.path.expanduser(t))):
        return ("file", t)
    if t.lower().startswith("www.") or re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", t, re.I):
        return ("url", t)
    return None

CADENCES = ["daily", "often", "every2-3", "weekly", "flexible"]


# --------------------------------------------------------------------------

def _plain(text: str) -> QLabel:
    """A label that shows ``text`` as it is: calendar event titles come from
    whoever sent the invite, and must never turn into links or pictures."""
    lbl = QLabel(text)
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    return lbl

class PlanDialog(QDialog):
    """The 'Plan my day' consent screen: today's calendar with the cat's
    proposed blocks slotted among your real events. Reorder with ▲▼ (times
    re-flow), flip Home/Outside, tick what you want, then Add. Nothing is
    written unless you approve it."""

    def __init__(self, events: list, items: list, pack_cb, header: str,
                 free_slots: list = (), presence: str = "home",
                 set_presence_cb=None, cat_name: str = "Pisi", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{cat_name}'s plan for today \U0001F5D3")
        self.resize(500, 560)
        self.accepted: list = []
        self._events = [e for e in events if not e.get("all_day")]
        self._allday = [e for e in events if e.get("all_day")]
        self._free = [(s, e) for (s, e, *_ ) in free_slots]
        self._items = list(items)          # ordered plan items (no times)
        self._pack = pack_cb               # items -> placed list (start/end)
        self._set_presence = set_presence_cb
        self._placed = []
        self._rows = []

        root = QVBoxLayout(self)
        top = QLabel(header)
        top.setWordWrap(True); top.setStyleSheet("color:#888;font-size:11px")
        root.addWidget(top)

        # Home / Outside toggle — gates 'home only' habits
        prow = QHBoxLayout()
        prow.addWidget(QLabel("I'm:"))
        self.rb_home = QRadioButton("🏠 Home")
        self.rb_out = QRadioButton("🚶 Outside")
        (self.rb_home if presence != "out" else self.rb_out).setChecked(True)
        self.rb_home.toggled.connect(self._presence_changed)
        prow.addWidget(self.rb_home); prow.addWidget(self.rb_out); prow.addStretch(1)
        pw = QWidget(); pw.setLayout(prow); root.addWidget(pw)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._body = QWidget()
        self._box = QVBoxLayout(self._body)
        scroll.setWidget(self._body)
        root.addWidget(scroll, 1)

        bb = QDialogButtonBox()
        add = bb.addButton("Add to PISI calendar",
                           QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        add.clicked.connect(self._accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._rebuild()

    # ---- presence / reorder -----------------------------------------
    def _presence_changed(self):
        if self._set_presence:
            self._set_presence("home" if self.rb_home.isChecked() else "out")
        self._rebuild()

    def _items_index(self, key):
        for i, it in enumerate(self._items):
            if it["key"] == key:
                return i
        return -1

    def _move(self, key, direction):
        # reorder within the full priority list, so an unscheduled habit can be
        # promoted to swap in for one that fit.
        i = self._items_index(key)
        j = i + direction
        if 0 <= i and 0 <= j < len(self._items):
            self._items[i], self._items[j] = self._items[j], self._items[i]
            self._rebuild()

    # ---- rendering ---------------------------------------------------
    def _rebuild(self):
        while self._box.count():
            w = self._box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._rows = []
        self._placed = self._pack(self._items)

        if self._allday:
            note = _plain("📌 " + ", ".join(e["summary"] for e in self._allday[:3]))
            note.setStyleSheet("color:#888;font-size:11px")
            self._box.addWidget(note)

        timeline = [("event", e["start"], e) for e in self._events]
        timeline += [("prop", p["start"], p) for p in self._placed]
        timeline += [("free", s, (s, e)) for s, e in self._leftover_free()]
        timeline.sort(key=lambda t: t[1])
        for kind, _t, obj in timeline:
            if kind == "event":
                self._box.addWidget(self._event_row(obj))
            elif kind == "prop":
                self._box.addWidget(self._prop_row(obj))
            else:
                self._box.addWidget(self._free_row(*obj))

        # habits that didn't fit — shown so you can promote one to swap it in
        placed_keys = {p["key"] for p in self._placed}
        unplaced = [it for it in self._items if it["key"] not in placed_keys]
        if unplaced:
            div = QLabel("didn't fit today · move ▲ to swap one in")
            div.setStyleSheet("color:#888;font-size:11px;padding-top:8px")
            self._box.addWidget(div)
            for it in unplaced:
                self._box.addWidget(self._unplaced_row(it))
        self._box.addStretch(1)

    def _leftover_free(self):
        """Free gaps not filled by a proposal — so you can see open time."""
        placed = sorted((p["start"], p["end"]) for p in self._placed)
        rows = []
        for s, e in self._free:
            cur = s
            for ps, pe in placed:
                if pe <= cur or ps >= e:
                    continue
                if ps > cur and ps - cur >= timedelta(minutes=20):
                    rows.append((cur, min(ps, e)))
                cur = max(cur, pe)
            if e - cur >= timedelta(minutes=20):
                rows.append((cur, e))
        return rows

    def _free_row(self, s, e):
        w = QLabel(f"{_hm(s)}–{_hm(e)}   free")
        w.setStyleSheet("color:#9a9a9a; font-style:italic; padding:2px;")
        return w

    def _event_row(self, e):
        w = _plain(f"{_hm(e['start'])}–{_hm(e['end'])}   {e['summary']}   ·  busy")
        w.setStyleSheet("color:#7a7a7a; padding:3px 2px;")
        return w

    def _updown(self, key):
        up = QPushButton("↑"); dn = QPushButton("↓")
        for b in (up, dn):
            b.setFixedSize(30, 28)
            b.setToolTip("Move up in priority" if b is up else "Move down")
        up.clicked.connect(lambda _=False, k=key: self._move(k, -1))
        dn.clicked.connect(lambda _=False, k=key: self._move(k, +1))
        return up, dn

    def _prop_row(self, p):
        row = QHBoxLayout()
        cb = QCheckBox(); cb.setChecked(True)
        te = QTimeEdit(); te.setDisplayFormat("H:mm")
        te.setTime(QTime(p["start"].hour, p["start"].minute))
        dur = int((p["end"] - p["start"]).total_seconds() // 60)
        icon = "🌙 " if p["kind"] == "focus" else ""
        lbl = _plain(f"{icon}{p['title']}  ·  {dur} min"
                     + (f":  {p['reason']}" if p.get("reason") else ""))
        lbl.setWordWrap(True)
        up, dn = self._updown(p["key"])
        row.addWidget(cb); row.addWidget(te); row.addWidget(lbl, 1)
        row.addWidget(up); row.addWidget(dn)
        rw = QWidget(); rw.setLayout(row)
        rw.setStyleSheet("background:rgba(232,148,58,0.12); border-radius:6px;")
        self._rows.append((p, cb, te, dur))
        return rw

    def _unplaced_row(self, it):
        row = QHBoxLayout()
        if it.get("where") == "home" and self.rb_out.isChecked():
            why = "🏠 home only (you're out)"
        else:
            why = "no free slot"
        lbl = _plain(f"{it['title']}  ·  {it['minutes']} min  ·  {why}")
        lbl.setStyleSheet("color:#8a8a8a")
        lbl.setWordWrap(True)
        up, dn = self._updown(it["key"])
        row.addWidget(lbl, 1)
        row.addWidget(up); row.addWidget(dn)
        rw = QWidget(); rw.setLayout(row)
        return rw

    def _accept(self):
        for p, cb, te, dur in self._rows:
            if not cb.isChecked():
                continue
            t = te.time()
            start = p["start"].replace(hour=t.hour(), minute=t.minute())
            self.accepted.append({**p, "start": start,
                                  "end": start + timedelta(minutes=dur)})
        self.accept()


class ManageDialog(QDialog):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Manage \U0001F4C1")
        self.resize(500, 480)
        root = QVBoxLayout(self)
        root.addWidget(self._habits_tab(), 1)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        root.addWidget(close)

    # -- habits --
    def _habits_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        self.h_list = QListWidget(); lay.addWidget(self.h_list, 1)
        self._reload_habits()
        box = QGroupBox("Add habit"); f = QFormLayout(box)
        self.h_name = QLineEdit(); self.h_emoji = QLineEdit("⭐")
        self.h_cad = QComboBox(); self.h_cad.addItems(CADENCES)
        self.h_where = QComboBox()
        self.h_where.addItem("Anywhere", "anywhere")
        self.h_where.addItem("Home only", "home")
        f.addRow("Name:", self.h_name); f.addRow("Emoji:", self.h_emoji)
        f.addRow("Cadence:", self.h_cad)
        f.addRow("Where:", self.h_where)
        add = QPushButton("Add"); add.clicked.connect(self._add_habit); f.addRow(add)
        lay.addWidget(box)

        # set location on an existing habit (so the planner won't e.g. schedule a
        # home-only workout while you're on campus)
        locrow = QHBoxLayout()
        locrow.addWidget(QLabel("Location for selected:"))
        self.h_setwhere = QComboBox()
        self.h_setwhere.addItem("Anywhere", "anywhere")
        self.h_setwhere.addItem("Home only", "home")
        setw = QPushButton("Set")
        setw.clicked.connect(self._set_where)
        locrow.addWidget(self.h_setwhere, 1); locrow.addWidget(setw)
        lw = QWidget(); lw.setLayout(locrow); lay.addWidget(lw)

        setup = QPushButton("\U0001F5C2  Setup for selected…")
        setup.setToolTip("Attach the files and links you need for this habit. PISI "
                         "opens them in one click when it's this habit's time")
        setup.clicked.connect(self._edit_workspace)
        lay.addWidget(setup)

        rm = QPushButton("Remove selected"); rm.clicked.connect(self._rm_habit)
        lay.addWidget(rm)
        return w

    def _edit_workspace(self):
        it = self.h_list.currentItem()
        if not it:
            return
        hid = it.data(Qt.ItemDataRole.UserRole)
        h = self.store.habit(hid)
        ws = (h or {}).get("workspace") or {}
        ed = WorkspaceEditor(
            self, title=f"Setup: {h['name']}", show_name=False,
            paths=ws.get("paths"), urls=ws.get("urls"), cmds=ws.get("cmds"),
            intro="Files, links and apps for this habit. When PISI reminds you "
                  f"it's {h['name']} time, one click opens all of these.")
        if ed.exec():
            self.store.set_habit_workspace(hid, ed.paths, ed.urls, ed.cmds)
            self._reload_habits()

    def _set_where(self):
        it = self.h_list.currentItem()
        if not it:
            return
        self.store.set_habit_where(it.data(Qt.ItemDataRole.UserRole),
                                   self.h_setwhere.currentData())
        self._reload_habits()

    def _reload_habits(self):
        self.h_list.clear()
        for h in self.store.habits:
            where = h.get("where", "anywhere")
            wtag = "  · 🏠 home" if where == "home" else ""
            ws = h.get("workspace") or {}
            stag = ("  · 🗂 setup"
                    if (ws.get("paths") or ws.get("urls") or ws.get("cmds"))
                    else "")
            it = QListWidgetItem(f"{h.get('emoji','⭐')}  {h['name']}   "
                                 f"({h.get('cadence')}){wtag}{stag}")
            it.setData(Qt.ItemDataRole.UserRole, h["id"])
            self.h_list.addItem(it)

    def _add_habit(self):
        name = self.h_name.text().strip()
        if not name:
            return
        self.store.add_habit(name, self.h_emoji.text().strip() or "⭐",
                             self.h_cad.currentText(), self.h_where.currentData())
        self.h_name.clear(); self._reload_habits()

    def _rm_habit(self):
        it = self.h_list.currentItem()
        if it and QMessageBox.question(self, "Remove", "Remove this habit and its "
                                       "history?") == QMessageBox.StandardButton.Yes:
            self.store.remove_habit(it.data(Qt.ItemDataRole.UserRole))
            self._reload_habits()


class SnapshotDialog(QDialog):
    """List the windows you have open now and let you tick which to save into a
    workspace. Files come pre-checked; browser tabs are editable hints."""

    _BADGE = {"file": ("file", "#2d7d46"),
              "url": ("link?", "#b8860b"),
              "app": ("app", "#888")}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save what's open")
        self.resize(560, 460)
        self.paths: list[str] = []
        self.urls: list[str] = []
        self.cmds: list[str] = []
        self._rows: list[tuple[QCheckBox, QLineEdit, str, str]] = []

        root = QVBoxLayout(self)
        intro = QLabel(
            "These are your open windows. Tick what to keep; nothing ticked is "
            "dropped. <b>Files</b> are captured for real. Browser <b>tabs</b> are "
            "matched to their real URL from your history (the ones that resolved "
            "are pre-checked); any that couldn't are kept as a title to "
            "double-click and fix. An <b>app</b> becomes a launch command you can "
            f"refine (add the folder, e.g. <i>{CMD_EXAMPLE}</i>).")
        intro.setWordWrap(True); intro.setStyleSheet("font-style:italic;")
        root.addWidget(intro)

        snaps = windows.snapshot()
        if not snaps:
            root.addWidget(QLabel("Couldn't read open windows." if IS_WINDOWS
                                  else "Couldn't read open windows (needs wmctrl on X11)."))
        area = QScrollArea(); area.setWidgetResizable(True)
        inner = QWidget(); grid = QVBoxLayout(inner)
        for s in snaps:
            grid.addLayout(self._row(s))
        grid.addStretch(1)
        area.setWidget(inner); root.addWidget(area, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _row(self, s: dict) -> QHBoxLayout:
        row = QHBoxLayout()
        cb = QCheckBox(); cb.setChecked(bool(s.get("suggested")))
        label, color = self._BADGE.get(s["kind"], self._BADGE["app"])
        badge = QLabel(label); badge.setFixedWidth(46)
        badge.setStyleSheet(f"color:{color}; font-size:11px;")
        edit = QLineEdit(s.get("value", ""))
        edit.setToolTip(s.get("title", ""))
        if s["kind"] == "url":
            edit.setPlaceholderText("paste the real URL here")
        row.addWidget(cb); row.addWidget(badge); row.addWidget(edit, 1)
        self._rows.append((cb, edit, s["kind"], s.get("app", "")))
        return row

    def _ok(self):
        for cb, edit, kind, app in self._rows:
            if not cb.isChecked():
                continue
            text = edit.text().strip()
            if not text:
                continue
            item = _as_item(text)
            if item:                       # a real file path or URL
                (self.paths if item[0] == "file" else self.urls).append(item[1])
            elif kind == "app":            # reopen the app (edit in the folder later)
                if app:                    # never a window's title: pages and files choose those
                    self.cmds.append(app)
            else:                          # a browser tab title — keep it to fix
                self.urls.append(text)
        self.accept()


class WorkspaceEditor(QDialog):
    def __init__(self, parent=None, title="New workspace", name="",
                 paths=None, urls=None, cmds=None, show_name=True, intro=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 560)
        self.name = name
        self.paths: list[str] = list(paths or [])
        self.urls: list[str] = list(urls or [])
        self.cmds: list[str] = list(cmds or [])
        root = QVBoxLayout(self)
        if intro:
            lbl = QLabel(intro); lbl.setWordWrap(True)
            lbl.setStyleSheet("font-style:italic;")   # legible on any theme
            root.addWidget(lbl)
        self.n = QLineEdit(name)
        if show_name:
            f = QFormLayout(); f.addRow("Name:", self.n); root.addLayout(f)

        snap = QPushButton("\U0001F4F8  From open windows…")
        snap.setToolTip("Fill this from the files and tabs you have open right now")
        snap.clicked.connect(self._from_open)
        root.addWidget(snap)
        tip = QLabel("Double-click any item to edit it "
                     "(e.g. paste a tab's real URL, or add a folder to a command).")
        tip.setWordWrap(True); tip.setStyleSheet("font-style:italic;")
        root.addWidget(tip)

        root.addWidget(QLabel("Files:"))
        self.p_list = self._make_list(self.paths); root.addWidget(self.p_list, 1)
        prow = QHBoxLayout()
        addf = QPushButton("Add file…"); addf.clicked.connect(self._add_file)
        rmf = QPushButton("Remove"); rmf.clicked.connect(
            lambda: self._rm(self.p_list))
        prow.addWidget(addf); prow.addWidget(rmf); root.addLayout(prow)

        root.addWidget(QLabel("Links:"))
        self.u_list = self._make_list(self.urls); root.addWidget(self.u_list, 1)
        urow = QHBoxLayout()
        addu = QPushButton("Add link…"); addu.clicked.connect(self._add_url)
        rmu = QPushButton("Remove"); rmu.clicked.connect(
            lambda: self._rm(self.u_list))
        urow.addWidget(addu); urow.addWidget(rmu); root.addLayout(urow)

        root.addWidget(QLabel("Apps / commands:"))
        self.c_list = self._make_list(self.cmds); root.addWidget(self.c_list, 1)
        crow = QHBoxLayout()
        addc = QPushButton("Add command…"); addc.clicked.connect(self._add_cmd)
        rmc = QPushButton("Remove"); rmc.clicked.connect(
            lambda: self._rm(self.c_list))
        crow.addWidget(addc); crow.addWidget(rmc); root.addLayout(crow)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _make_list(self, items) -> QListWidget:
        lst = QListWidget()
        lst.setEditTriggers(QListWidget.EditTrigger.DoubleClicked
                            | QListWidget.EditTrigger.SelectedClicked)
        for it in items:
            self._add_editable(lst, it)
        return lst

    @staticmethod
    def _add_editable(lst: QListWidget, text: str):
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
        lst.addItem(it)

    def _from_open(self):
        snap = SnapshotDialog(self)
        if not snap.exec():
            return
        for lst, incoming in ((self.p_list, snap.paths),
                              (self.u_list, snap.urls),
                              (self.c_list, snap.cmds)):
            have = {lst.item(i).text() for i in range(lst.count())}
            for v in incoming:
                if v not in have:
                    self._add_editable(lst, v)

    def _add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Add file")
        if path:
            self._add_editable(self.p_list, path)

    def _add_url(self):
        url, ok = QInputDialog.getText(self, "Add link", "URL:")
        if ok and url.strip():
            self._add_editable(self.u_list, url.strip())

    def _add_cmd(self):
        cmd, ok = QInputDialog.getText(
            self, "Add command",
            f"Shell command (e.g. {CMD_EXAMPLE}, or spotify):")
        if ok and cmd.strip():
            self._add_editable(self.c_list, cmd.strip())

    def _rm(self, lst: QListWidget):
        row = lst.currentRow()
        if row >= 0:
            lst.takeItem(row)

    @staticmethod
    def _values(lst: QListWidget) -> list[str]:
        return [lst.item(i).text().strip()
                for i in range(lst.count()) if lst.item(i).text().strip()]

    def _ok(self):
        self.name = self.n.text().strip() or "Workspace"
        self.paths = self._values(self.p_list)
        self.urls = self._values(self.u_list)
        self.cmds = self._values(self.c_list)
        self.accept()


# --------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, store: Store, calendar=None, gcal=None, parent=None,
                 open_pet_studio=None, extension_connected=None):
        super().__init__(parent)
        self._extension_connected = extension_connected
        self.store = store
        self.calendar = calendar
        self.gcal = gcal
        self._open_pet_studio = open_pet_studio
        self.setWindowTitle("Settings ⚙")
        cfg = store.config
        # scrollable body so the dialog never outgrows the screen; Save/Cancel
        # stay pinned below it.
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        root = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        appearance = QGroupBox("Your cat")
        f = QFormLayout(appearance)
        self.name = QLineEdit(cfg.get("cat_name", "Pisi"))
        f.addRow("Name:", self.name)
        self.speed = QDoubleSpinBox(); self.speed.setRange(0.3, 3.0)
        self.speed.setSingleStep(0.1); self.speed.setValue(float(cfg.get("speed", 2.0)))
        f.addRow("Walk speed:", self.speed)
        self.wander = QCheckBox("Wander around the screen")
        self.wander.setChecked(bool(cfg.get("wander", True)))
        f.addRow(self.wander)
        self._autostart_was = autostart.is_enabled()
        self.autostart = QCheckBox("Start when I sign in to Windows" if IS_WINDOWS
                                   else "Open at login" if IS_MAC
                                   else "Start when I log in")
        self.autostart.setChecked(self._autostart_was)
        f.addRow(self.autostart)
        pet_btn = QPushButton("\U0001F43E  Pet Studio…")
        pet_btn.setToolTip("Make the cat your own: coat, pattern, eyes, build and "
                           "how it moves.")
        pet_btn.clicked.connect(self._pet_studio)
        pet_btn.setEnabled(open_pet_studio is not None)
        f.addRow("Look:", pet_btn)
        root.addWidget(appearance)

        # --- web pages: the pet walks on text (browser extension, opt-in) ---
        web = QGroupBox("Web pages")
        wf = QFormLayout(web)
        self.web_perch = QCheckBox("Let PISI play on the web pages you read")
        self.web_perch.setChecked(bool(cfg.get("web_perch", True)))
        self.web_perch.setToolTip("Needs the PISI browser extension. Switch it off for "
                                  "a site, or pause it, from the extension's toolbar button.")
        wf.addRow(self.web_perch)
        self.web_fit = QCheckBox("Shrink to fit the page's text")
        self.web_fit.setChecked(bool(cfg.get("web_fit", False)))
        self.web_fit.setToolTip("On a page, PISI becomes about two lines of text tall, so it "
                                "can creep between paragraphs and climb from one to the next "
                                "(busier). Off: it keeps its usual size, heads for a good spot "
                                "(a heading, the search box, a picture) and mostly lounges there.")
        wf.addRow(self.web_fit)
        wrow = QHBoxLayout()
        bridge_btn = QPushButton("Set up browser bridge")
        bridge_btn.clicked.connect(self._setup_bridge)
        store_btn = QPushButton("Get the extension")
        store_btn.setToolTip("Its page on the Chrome Web Store (Chrome, Brave, Edge, Vivaldi)")
        store_btn.clicked.connect(self._open_store)
        ext_btn = QPushButton("Show extension folder")
        ext_btn.setToolTip("For Firefox, which loads it from this folder for now")
        ext_btn.clicked.connect(self._show_extension)
        wrow.addWidget(bridge_btn)
        wrow.addWidget(store_btn)
        wrow.addWidget(ext_btn)
        wrow.addStretch(1)
        ww = QWidget(); ww.setLayout(wrow)
        wf.addRow(ww)
        self.bridge_status = QLabel()
        self.bridge_status.setWordWrap(True)
        self.bridge_status.setStyleSheet("color:#888;font-size:11px")
        wf.addRow(self.bridge_status)
        self._show_bridge_status()
        # guarded sites that can't be guarded: say so, don't fail quietly
        self.guard_warn = QLabel()
        self.guard_warn.setWordWrap(True)
        self.guard_warn.setStyleSheet("color:#b4532a;font-size:11px")
        wf.addRow(self.guard_warn)
        self.web_perch.toggled.connect(self._show_guard_warning)
        self._show_guard_warning()
        root.addWidget(web)

        nudges = QGroupBox("Quiet time")
        nf = QFormLayout(nudges)
        self.q_start = QLineEdit(cfg.get("quiet_start", "23:00"))
        self.q_end = QLineEdit(cfg.get("quiet_end", "08:00"))
        qrow = QHBoxLayout(); qrow.addWidget(self.q_start); qrow.addWidget(QLabel("to"))
        qrow.addWidget(self.q_end)
        qw = QWidget(); qw.setLayout(qrow)
        nf.addRow("Quiet hours:", qw)
        root.addWidget(nudges)

        cal = QGroupBox("Read your calendars")
        cf = QFormLayout(cal)
        what = QLabel("Optional. PISI reads these to tell you what's on each morning, "
                      "stay quiet during your meetings and suggest focus in free gaps. "
                      "It never changes them.")
        what.setWordWrap(True)
        cf.addRow(what)
        self.ical_url = QPlainTextEdit(cfg.get("ical_url", ""))
        self.ical_url.setPlaceholderText("https://calendar.google.com/calendar/ical/…/basic.ics\n"
                                         "(one address per line)")
        self.ical_url.setFixedHeight(72)
        cf.addRow("Addresses:", self.ical_url)
        hint = QLabel("Paste each calendar's private iCal address. In Google Calendar: "
                      "Settings → your calendar → Integrate calendar → "
                      "“Secret address in iCal format”. Works offline once synced.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:11px")
        cf.addRow(hint)

        statusrow = QHBoxLayout()
        self.cal_status = QLabel(self.calendar.status_line() if self.calendar else "")
        self.cal_status.setWordWrap(True)
        self.cal_status.setStyleSheet("font-size:11px")
        sync = QPushButton("Sync now")
        sync.clicked.connect(self._sync_calendars)
        statusrow.addWidget(self.cal_status, 1)
        statusrow.addWidget(sync)
        sw = QWidget(); sw.setLayout(statusrow)
        cf.addRow(sw)
        self.smart_nudges = QCheckBox("Suggest focus blocks in my free time")
        self.smart_nudges.setChecked(bool(cfg.get("smart_nudges", True)))
        cf.addRow(self.smart_nudges)
        root.addWidget(cal)

        if self.gcal is not None:
            gc = QGroupBox("Write to Google Calendar")
            gf = QFormLayout(gc)
            self.g_id = QLineEdit(cfg.get("google_client_id", ""))
            self.g_id.setPlaceholderText("OAuth client ID (…apps.googleusercontent.com)")
            self.g_secret = QLineEdit(cfg.get("google_client_secret", ""))
            self.g_secret.setEchoMode(QLineEdit.EchoMode.Password)
            self.g_secret.setPlaceholderText("OAuth client secret")
            own = self.gcal.uses_own_client()
            if self.gcal.built_in():
                # PISI has its own client: connecting is one click; your own
                # client is an advanced option, folded away
                self.g_own = QCheckBox("Use my own Google client (advanced)")
                self.g_own.setChecked(own)
                gf.addRow(self.g_own)
            gf.addRow("Client ID:", self.g_id)
            gf.addRow("Client secret:", self.g_secret)
            if self.gcal.built_in():
                def _own_toggled(on: bool) -> None:
                    for w in (self.g_id, self.g_secret):
                        w.setVisible(on)
                        lbl = gf.labelForField(w)
                        if lbl is not None:
                            lbl.setVisible(on)
                    if not on:
                        self.g_id.clear()
                        self.g_secret.clear()
                self.g_own.toggled.connect(_own_toggled)
                _own_toggled(own)
            grow = QHBoxLayout()
            self.g_status = QLabel(self.gcal.status_line())
            self.g_status.setWordWrap(True)
            self.g_status.setStyleSheet("font-size:11px")
            self.g_connect = QPushButton("Disconnect" if self.gcal.connected()
                                         else "Connect…")
            self.g_connect.clicked.connect(self._toggle_google)
            grow.addWidget(self.g_status, 1)
            grow.addWidget(self.g_connect)
            gw = QWidget(); gw.setLayout(grow)
            gf.addRow(gw)
            ghint = QLabel("Lets PISI write your finished focus blocks and the plans "
                           "you approve to its own “PISI” calendar. It can't see "
                           "or change your other calendars.")
            ghint.setWordWrap(True)
            ghint.setStyleSheet("color:#888;font-size:11px")
            gf.addRow(ghint)
            root.addWidget(gc)

        focus = QGroupBox("Focus sessions")
        ff = QFormLayout(focus)

        def _spin(val, lo, hi):
            s = QSpinBox(); s.setRange(lo, hi); s.setValue(int(val))
            s.setSuffix(" min"); return s

        self.focus_min = _spin(cfg.get("focus_min", 25), 1, 180)
        ff.addRow("Focus length:", self.focus_min)
        self.break_min = _spin(cfg.get("break_min", 5), 1, 60)
        ff.addRow("Short break:", self.break_min)
        self.long_break_min = _spin(cfg.get("long_break_min", 15), 1, 120)
        ff.addRow("Long break:", self.long_break_min)
        self.sessions_before_long = QSpinBox()
        self.sessions_before_long.setRange(0, 12)
        self.sessions_before_long.setValue(int(cfg.get("sessions_before_long", 4)))
        self.sessions_before_long.setSpecialValueText("never")
        ff.addRow("Long break every:", self.sessions_before_long)
        self.focus_autostart = QCheckBox("Roll into a break automatically")
        self.focus_autostart.setChecked(bool(cfg.get("focus_autostart_breaks", True)))
        ff.addRow(self.focus_autostart)
        self.focus_autostart_focus = QCheckBox(
            "After a break, auto-start the next block (keeps cycling unattended)")
        self.focus_autostart_focus.setChecked(
            bool(cfg.get("focus_autostart_focus", False)))
        self.focus_autostart_focus.setToolTip(
            "Off (default): after a break the timer pauses and waits for you to "
            "press ▶, so it won't keep cycling while you're away from the desk.")
        ff.addRow(self.focus_autostart_focus)
        _sp = species.CAT
        self.focus_reward = QCheckBox(f"Earn a {_sp.treat_name} {_sp.treat} per finished block")
        self.focus_reward.setChecked(bool(cfg.get("focus_reward_treat", True)))
        ff.addRow(self.focus_reward)
        self.focus_dnd = QCheckBox("Do not disturb (hush reminders while focusing)")
        self.focus_dnd.setChecked(bool(cfg.get("focus_dnd", True)))
        ff.addRow(self.focus_dnd)

        # --- alert sounds: what PISI does when a block/break ends ---------
        from . import chime
        opts = chime.available()

        def _sound_combo(current, fallback):
            cb = QComboBox()
            for key, lbl in opts:
                cb.addItem(lbl, key)
            idx = cb.findData(current if any(k == current for k, _ in opts) else fallback)
            cb.setCurrentIndex(max(0, idx))
            return cb

        focus_key = cfg.get("focus_sound", "voice")
        self.focus_sound = _sound_combo(chime.LEGACY.get(focus_key, focus_key), "voice")
        break_key = cfg.get("break_sound", "bowl")
        self.break_sound = _sound_combo(chime.LEGACY.get(break_key, break_key), "bowl")

        def _sound_row(combo):
            row = QHBoxLayout()
            row.addWidget(combo, 1)
            prev = QPushButton("▶")          # ▶ preview
            prev.setToolTip("Preview")
            prev.setFixedWidth(34)
            prev.setCursor(Qt.CursorShape.PointingHandCursor)
            prev.clicked.connect(
                lambda: chime.play(combo.currentData(), self.sound_volume.value()))
            row.addWidget(prev)
            w = QWidget(); w.setLayout(row); return w

        ff.addRow("Focus-end sound:", _sound_row(self.focus_sound))
        ff.addRow("Break-end sound:", _sound_row(self.break_sound))

        self.sound_volume = QSlider(Qt.Orientation.Horizontal)
        self.sound_volume.setRange(0, 100)
        self.sound_volume.setValue(int(cfg.get("sound_volume", 70)))
        vol_lbl = QLabel(f"{self.sound_volume.value()}%")
        vol_lbl.setFixedWidth(38)
        self.sound_volume.valueChanged.connect(lambda v: vol_lbl.setText(f"{v}%"))
        vrow = QHBoxLayout()
        vrow.addWidget(self.sound_volume, 1); vrow.addWidget(vol_lbl)
        vwrap = QWidget(); vwrap.setLayout(vrow)
        ff.addRow("Volume:", vwrap)

        root.addWidget(focus)

        help_box = QGroupBox("Help")
        hrow = QHBoxLayout(help_box)
        fb = QPushButton("\U0001F41E  Report a bug or get in touch\u2026")
        fb.clicked.connect(self._feedback)
        hrow.addWidget(fb)
        hrow.addStretch(1)
        root.addWidget(help_box)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save); bb.rejected.connect(self.reject)
        outer.addWidget(bb)                     # pinned below the scroll area

        # size to fit the screen (cap height so the buttons are always visible)
        scr = self.screen() or QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        h = min(680, int(avail.height() * 0.9)) if avail else 620
        self.resize(470, h)


    def _pet_studio(self) -> None:
        """Settings is modal and would block Pet Studio's window: save and
        close first, then open it."""
        if self._open_pet_studio:
            opener = self._open_pet_studio
            self._save()
            QTimer.singleShot(0, opener)

    def _show_bridge_status(self, done: list[str] | None = None) -> None:
        from . import bridge
        have = bridge.installed() if done is None else done
        if have:
            self.bridge_status.setText(
                "Bridge set up for " + ", ".join(have) + ". Add the extension from the "
                "Chrome Web Store (Get the extension; Firefox: Show extension folder, "
                "then about:debugging → Load Temporary Add-on → manifest.json), "
                "then open any article and watch PISI hop on.")
        else:
            self.bridge_status.setText(
                "Not set up yet. PISI only ever sees the shape of a page (where "
                "paragraphs, headings and pictures are), never the words or the "
                "address, and steps off pages that ask for a password or card number.")

    def guard_warning(self) -> str:
        """Why the sites you asked PISI to guard won't be guarded ("" if they will)."""
        if not self.store.config.get("guard_sites"):
            return ""
        if not self.web_perch.isChecked():
            return ("You've asked PISI to guard some sites, but it can't while web "
                    "pages are switched off (the box above).")
        if self._extension_connected is not None and not self._extension_connected():
            return ("You've asked PISI to guard some sites, but the browser extension "
                    "isn't connected right now. Open your browser, or use "
                    "Set up browser bridge above.")
        return ""

    def _show_guard_warning(self, *_) -> None:
        text = self.guard_warning()
        self.guard_warn.setText(text)
        self.guard_warn.setVisible(bool(text))

    def _setup_bridge(self) -> None:
        from . import bridge
        try:
            done = bridge.install()
        except OSError as e:
            QMessageBox.warning(self, "Browser bridge", f"Couldn't set it up: {e}")
            return
        if not done:
            QMessageBox.information(self, "Browser bridge",
                                    "No supported browser found (Chrome, Chromium, "
                                    "Brave, Edge, Vivaldi or Firefox).")
        self._show_bridge_status(done)

    def _feedback(self) -> None:
        from .feedback import FeedbackDialog
        FeedbackDialog(self).exec()

    def _open_store(self) -> None:
        from . import bridge
        QDesktopServices.openUrl(QUrl(bridge.STORE_URL))

    def _show_extension(self) -> None:
        from . import bridge
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(bridge.extension_dir())))
    def _toggle_google(self):
        if not self.gcal:
            return
        if self.gcal.connected():
            self.gcal.disconnect()
            self.g_status.setText(self.gcal.status_line())
            self.g_connect.setText("Connect…")
            return
        # persist the entered credentials so the connect flow can use them
        self.store.set_config("google_client_id", self.g_id.text().strip())
        self.store.set_config("google_client_secret", self.g_secret.text().strip())
        if not self.gcal.has_credentials():
            self.g_status.setText("Add your client ID and secret first.")
            return
        self.g_connect.setEnabled(False)
        self.gcal.connect(self.g_status.setText)
        # poll the status while the browser flow completes, then restore button
        def tick(n=0):
            self.g_status.setText(self.gcal.status_line()
                                  if self.gcal.connected() else self.g_status.text())
            if self.gcal.connected():
                self.g_connect.setText("Disconnect")
                self.g_connect.setEnabled(True)
            elif n < 60:
                QTimer.singleShot(2000, lambda: tick(n + 1))
            else:
                self.g_connect.setEnabled(True)
        QTimer.singleShot(2000, tick)

    def _sync_calendars(self):
        if not self.calendar:
            return
        # sync exactly what's in the box right now (persist the URLs first)
        self.store.set_config("ical_url", self.ical_url.toPlainText().strip())
        self.cal_status.setText("syncing…")
        self.calendar.refresh()
        # the fetch is on a background thread; poll a few times for the result
        for delay in (1200, 2500, 4500):
            QTimer.singleShot(
                delay, lambda: self.cal_status.setText(self.calendar.status_line()))

    def _save(self):
        cfg = self.store.config
        cfg["cat_name"] = self.name.text().strip() or "Pisi"
        cfg["speed"] = float(self.speed.value())
        cfg["wander"] = self.wander.isChecked()
        cfg["web_perch"] = self.web_perch.isChecked()
        cfg["web_fit"] = self.web_fit.isChecked()
        if self.autostart.isChecked() != self._autostart_was:
            autostart.set_enabled(self.autostart.isChecked())
        cfg["quiet_start"] = self.q_start.text().strip() or "23:00"
        cfg["quiet_end"] = self.q_end.text().strip() or "08:00"
        cfg["ical_url"] = self.ical_url.toPlainText().strip()
        cfg["smart_nudges"] = self.smart_nudges.isChecked()
        if self.gcal is not None:
            cfg["google_client_id"] = self.g_id.text().strip()
            cfg["google_client_secret"] = self.g_secret.text().strip()
        cfg["focus_min"] = int(self.focus_min.value())
        cfg["break_min"] = int(self.break_min.value())
        cfg["long_break_min"] = int(self.long_break_min.value())
        cfg["sessions_before_long"] = int(self.sessions_before_long.value())
        cfg["focus_autostart_breaks"] = self.focus_autostart.isChecked()
        cfg["focus_autostart_focus"] = self.focus_autostart_focus.isChecked()
        cfg["focus_reward_treat"] = self.focus_reward.isChecked()
        cfg["focus_dnd"] = self.focus_dnd.isChecked()
        cfg["focus_sound"] = self.focus_sound.currentData()
        cfg["break_sound"] = self.break_sound.currentData()
        cfg["sound_volume"] = int(self.sound_volume.value())
        self.store.save()
        self.accept()


class TutorialDialog(QDialog):
    """A short, friendly first-run tour of paged cards, replayable from the
    menu (More → Show tutorial). ``actions`` maps a card's link to what it
    does ("studio", "corner", "extension"); a card whose action isn't
    available here is left out. An action that opens a window may return
    it: the tour comes back to the front when that window closes."""

    def __init__(self, cat_name: str = "PISI", parent=None, actions: dict | None = None):
        super().__init__(parent)
        name = cat_name or "PISI"
        pet = species.CAT
        self._actions = actions or {}
        self.setWindowTitle(f"Meet {name}")
        # not modal: its links open other windows (Pet Studio) that must be
        # usable while the tour waits behind them
        self.setModal(False)
        pages = [
            (None, "🐾", f"Hi, I'm {name}!",
             f"I'm a little {pet.noun} who lives on your desktop and keeps you "
             f"company while you work. I'll wander around, play with you on your "
             f"breaks, and remind you to stretch now and then.<br><br>"
             f"Everything I do is behind one <b>right-click</b> on me."),
            (None, "🍅", "Focus with me",
             "Open <b>Focus</b> to start a Pomodoro. A small pill next to me has "
             "pause, skip and stop. I'll nap while you work and stretch when "
             f"it's time for a break. Every block you finish earns me a "
             f"<b>treat</b> {pet.treat} to spend in the <b>Shop</b>."),
            ("studio", "🎨", "Make me yours",
             "In <b>Pet Studio</b> you can change my coat, pattern, eyes, build "
             "and even how I move. Start from a sample cat or roll a new one."
             "<br><br><a href='studio'>Open Pet Studio</a>"
             "<br><small>(later: right-click me → More → Pet Studio)</small>"),
            ("corner", "🏠", "My corner",
             "I have a little corner by your taskbar: a bed, a bowl and a toy "
             "basket. Things you buy in the Shop go there too.<br><br>"
             "If it sits on top of something on your taskbar, slide it to an "
             "empty spot: <a href='corner'>Move my corner</a>"
             "<br><small>(later: right-click me → More → Corner)</small>"),
            (None, "🎮", "Play with me",
             "On a break, open <b>Play</b>: throw me a toy, wave the feather "
             "wand, shine the laser or wind up a mouse. Click me to pet me, and "
             "drag me anywhere you like."),
            ("extension", "🌐", "On your web pages",
             "With my browser extension I climb onto the pages you read "
             "(Chrome, Brave, Edge, Vivaldi or Firefox), knock words off the "
             "ends of lines, pounce on what you select and watch your videos "
             "with you. Mark a site as distracting in its menu and I'll sit "
             "on it during focus blocks."
             "<br><br>"
             "<a href='extension'>Set it up</a>: I'll get your browser ready "
             "and open my page on the Chrome Web Store. Click <b>Add to "
             "Chrome</b> there (it works in Brave, Edge and Vivaldi too)."),
            (None, "🗓", "Your calendar",
             "Both optional, in <b>Settings</b>:<br>"
             "• Add your calendar's <b>iCal address</b> and I'll read it to tell "
             "you what's on each morning, keep quiet in meetings and suggest "
             "focus in free gaps.<br>"
             "• <b>Connect Google Calendar</b> and I'll put your finished focus "
             "blocks on a calendar of my own, called PISI. That connection "
             "can't see your other calendars."),
            (None, "💬", "That's it!",
             "Right-click me <b>any time</b> for focus, play and settings. You "
             "can replay this tour from <b>More → Show tutorial</b>.<br><br>"
             "Let's get started!"),
        ]
        self._pages = [(e, t, b) for key, e, t, b in pages
                       if key is None or key in self._actions]
        if IS_WINDOWS:
            # Windows 11 tucks new tray icons into the ^ overflow by default
            self._pages.insert(-1, (
                "📌", "Find me in the tray",
                "My paw icon lives in the taskbar's <b>^</b> hidden-icons menu. "
                "Drag it onto the taskbar to keep me one click away.<br><br>"
                "I start by myself when you sign in (you can switch that off in "
                "my <b>Settings</b>). If you hide me, open <b>PISI</b> from the "
                "Start menu to call me back."))
        elif IS_MAC:
            self._pages.insert(-1, (
                "📌", "Find me in the menu bar",
                "My paw icon sits in the <b>menu bar</b> at the top right: click "
                "it for my menu, or right-click me. I follow you across all your "
                "desktops and step aside for fullscreen apps.<br><br>"
                "I open by myself when you log in (you can switch that off in my "
                "<b>Settings</b>). If you lose me, open <b>PISI</b> from "
                "Applications or Spotlight to call me back."))
        self._i = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)

        self._emoji = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._emoji.setStyleSheet("font-size:40px;")
        self._title = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("font-size:17px; font-weight:600;")
        self._body = QLabel(wordWrap=True, alignment=Qt.AlignmentFlag.AlignCenter)
        self._body.setStyleSheet("font-size:13px; color:palette(text);")
        self._body.setMinimumWidth(380)
        self._body.setMinimumHeight(132)      # room for the wordiest card
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setOpenExternalLinks(False)
        self._body.linkActivated.connect(self._link)
        for w in (self._emoji, self._title, self._body):
            root.addWidget(w)

        self._dots = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._dots.setStyleSheet("color:palette(mid); letter-spacing:3px;")
        root.addWidget(self._dots)

        row = QHBoxLayout()
        self._skip = QPushButton("Skip")
        self._back = QPushButton("Back")
        self._next = QPushButton("Next")
        self._next.setDefault(True)
        self._skip.clicked.connect(self.accept)
        self._back.clicked.connect(self._go_back)
        self._next.clicked.connect(self._go_next)
        row.addWidget(self._skip)
        row.addStretch(1)
        row.addWidget(self._back)
        row.addWidget(self._next)
        root.addLayout(row)

        # fix the size to the wordiest card so nothing clips as pages change
        longest = max(self._pages, key=lambda p: len(p[2]))
        self._body.setText(longest[2])
        self.setFixedWidth(460)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())
        self._render()

    def _render(self):
        emoji, title, body = self._pages[self._i]
        self._emoji.setText(emoji)
        self._title.setText(title)
        self._body.setText(body)
        self._dots.setText(" ".join("●" if i == self._i else "○"
                                    for i in range(len(self._pages))))
        self._back.setEnabled(self._i > 0)
        last = self._i == len(self._pages) - 1
        self._next.setText("Let's go" if last else "Next")
        self._skip.setVisible(not last)

    def _go_next(self):
        if self._i >= len(self._pages) - 1:
            self.accept()
        else:
            self._i += 1
            self._render()

    def _go_back(self):
        if self._i > 0:
            self._i -= 1
            self._render()

    def _link(self, key: str) -> None:
        do = self._actions.get(key)
        if do is None:
            return
        opened = do()
        finished = getattr(opened, "finished", None)
        if finished is not None:
            # back to this page of the tour when that window closes
            finished.connect(self._come_back)

    def _come_back(self, *_):
        if self.isVisible():
            self.raise_()
            self.activateWindow()


class PomodoroCountDialog(QDialog):
    """Edit today's completed-pomodoro tally. Clearing it (→ 0) also resets
    progress toward the next long break, since the cadence counts from here."""

    def __init__(self, current: int, every: int = 4, parent=None):
        super().__init__(parent)
        self.count = current
        self.setWindowTitle("Pomodoros today 🍅")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)

        blurb = QLabel(f"Completed focus blocks today. A long break comes every "
                       f"{every} of them, counting from this number.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-style:italic;")
        root.addWidget(blurb)

        row = QHBoxLayout()
        row.addWidget(QLabel("Count:"))
        self.spin = QSpinBox()
        self.spin.setRange(0, 50)
        self.spin.setValue(int(current))
        row.addWidget(self.spin, 1)
        root.addLayout(row)

        btns = QHBoxLayout()
        clear = QPushButton("Clear to 0")
        clear.clicked.connect(lambda: self.spin.setValue(0))
        btns.addWidget(clear)
        btns.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        btns.addWidget(bb)
        root.addLayout(btns)

    def _ok(self):
        self.count = int(self.spin.value())
        self.accept()
