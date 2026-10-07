"""Pet Studio — make your own pixel pet (replaces Settings → Coat).

A consumer of the companion.creatures public API: the preview draws with the
exact same pipeline as the desktop pet. Non-modal, so nudges and focus
sessions keep running while it's open.

Layout: big animated preview (backgrounds, zoom, state, facing, play/pause,
frame-step, slow motion, rig overlay) on the left; on the right the pet's
name, family, seed, New pet, coat presets and every gene grouped with a lock
per group; undo/redo, reset to saved, save/load files and Use as my pet at
the bottom.
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                             QFormLayout, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QProgressBar, QPushButton, QScrollArea, QSlider,
                             QSpinBox, QVBoxLayout, QWidget)

from . import species
from .creatures import api
from .creatures import qt as cq

GROUP_LABELS = {"body": "Body", "head": "Head", "ears": "Ears", "tail": "Tail",
                "coat": "Coat", "eyes": "Eyes & nose", "motion": "Movement"}

STATE_LABELS = {
    "sit": "Sit", "idle": "Stand", "walk": "Walk", "run": "Run",
    "sleep": "Sleep", "yawn": "Yawn", "meow": "Meow", "talk": "Talk",
    "eat": "Eat", "pounce": "Pounce", "jump": "Jump", "attack": "Swipe",
    "hurt": "Ouch", "tailswish": "Tail swish", "lookaround": "Look around",
    "death": "Flop over", "crouch": "Crouch", "stretch": "Stretch (wake up)",
    "celebrate": "Celebrate", "petted": "Petted", "dangle": "Picked up",
    "sitdown": "→ sit down", "standup": "→ stand up", "liedown": "→ lie down",
    "getup": "→ get up", "turn": "→ turn around",
}

BACKGROUNDS = ("Checker", "Light wallpaper", "Dark wallpaper", "Desktop + taskbar")


def presets_dir() -> Path:
    from .paths import data_dir
    d = data_dir() / "pets" / "presets"
    d.mkdir(parents=True, exist_ok=True)
    return d


class PetPreview(QWidget):
    """Animated, integer-zoomed preview. Simulation time is independent of
    the repaint rate: frames come from ``sim_time * fps``."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 330)
        self.pet: api.Creature | None = None
        self.state = "sit"
        self.facing = 1
        self.zoom = 6
        self.bg = 0
        self.playing = True
        self.slow = 1.0
        self.show_rig = False
        self.t = 0.0                 # simulation seconds
        self.walk_x = 0.0            # desktop-strip position (sprite px)
        self._cache: dict[tuple[str, int, int], QImage] = {}
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._step)
        self._clock.start(16)

    # -- API
    def set_pet(self, pet: api.Creature) -> None:
        self.pet = pet
        self._cache.clear()
        if self.state not in pet.states():
            self.state = "sit"
        self.update()

    def set_state(self, s: str) -> None:
        self.state = s
        self.t = 0.0
        self.update()

    def frame_index(self) -> int:
        if not self.pet:
            return 0
        spec = self.pet.states()[self.state]
        i = int(self.t * spec.fps + 1e-9)
        if spec.loop:
            return i % spec.frames
        # one-shots: play, hold a beat on the last frame, repeat
        cyc = spec.frames + int(spec.fps * 0.8)
        i %= cyc
        return min(i, spec.frames - 1)

    def step_frame(self, d: int) -> None:
        if not self.pet:
            return
        self.playing = False
        spec = self.pet.states()[self.state]
        self.t = max(0.0, self.t + d / spec.fps)
        self.update()

    def _step(self) -> None:
        if not self.playing or not self.pet:
            return
        dt = 0.016 * self.slow
        self.t += dt
        sp = self.pet.speed(self.state)
        if sp and self.bg == 3:
            spec = self.pet.states()[self.state]
            self.walk_x += sp * spec.fps * dt * self.facing
        self.update()

    def _image(self, i: int) -> QImage:
        key = (self.state, i, self.facing)
        img = self._cache.get(key)
        if img is None:
            w, h = self.pet.size
            img = cq.image_from_rgba(self.pet.frame(self.state, i, self.facing), w, h)
            if len(self._cache) > 400:
                self._cache.clear()
            self._cache[key] = img
        return img

    # -- painting
    def _paint_bg(self, p: QPainter, gx: int, gy: int, z: int) -> None:
        r = self.rect()
        if self.bg == 0:
            c1, c2 = QColor(205, 205, 205), QColor(232, 232, 232)
            s = 8 * max(1, z // 2)
            for yy in range(0, r.height(), s):
                for xx in range(0, r.width(), s):
                    p.fillRect(xx, yy, s, s, c1 if (xx // s + yy // s) % 2 else c2)
        elif self.bg == 1:
            p.fillRect(r, QColor(226, 236, 244))
            p.fillRect(QRect(0, r.height() * 2 // 3, r.width(), r.height()), QColor(206, 222, 236))
        elif self.bg == 2:
            p.fillRect(r, QColor(36, 40, 52))
            p.fillRect(QRect(0, r.height() * 2 // 3, r.width(), r.height()), QColor(46, 52, 68))
        else:
            p.fillRect(r, QColor(92, 128, 168))
            # a window edge and the taskbar the pet walks along
            p.fillRect(QRect(r.width() // 8, r.height() // 10, r.width() // 2, r.height() // 2),
                       QColor(238, 238, 240))
            p.fillRect(QRect(r.width() // 8, r.height() // 10, r.width() // 2, 18),
                       QColor(60, 66, 80))
            p.fillRect(QRect(0, gy, r.width(), r.height() - gy), QColor(30, 33, 40))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        z = self.zoom
        if not self.pet:
            p.fillRect(self.rect(), QColor(40, 40, 40))
            return
        w, h = self.pet.size
        gx = (self.width() - w * z) // 2
        gy = (self.height() - h * z) // 2 + h * z // 6
        ground_y = gy + h * z
        self._paint_bg(p, gx, ground_y, z)
        x = gx
        if self.bg == 3 and self.pet.speed(self.state):
            span = self.width() + w * z
            x = int((gx + w * z + self.walk_x * z) % span) - w * z
        i = self.frame_index()
        p.drawImage(QRect(x, gy, w * z, h * z), self._image(i))
        if self.show_rig:
            self._paint_rig(p, x, gy, z, i)
        p.setPen(QColor(255, 255, 255) if self.bg in (2, 3) else QColor(40, 40, 40))
        p.drawText(8, self.height() - 8,
                   f"{STATE_LABELS.get(self.state, self.state)}  ·  frame {i + 1}/"
                   f"{self.pet.states()[self.state].frames}  ·  {z}×")

    def _paint_rig(self, p: QPainter, ox: int, oy: int, z: int, i: int) -> None:
        """Bones, tail and ground contacts of the current pose (whatever the
        family's body plan reports through ``rig()``)."""
        fam = self.pet.fam
        if not hasattr(fam, "rig"):
            return
        rig = fam.rig(self.pet.built, self.state, i)
        w = self.pet.size[0]

        def pt(x, y):
            if self.facing < 0:
                x = w - x
            return QPointF(ox + x * z, oy + y * z)
        colours = {"spine": QColor(80, 200, 255), "near": QColor(255, 170, 60),
                   "far": QColor(200, 120, 255), "tail": QColor(255, 230, 80)}
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for a_, b_, kind in rig["bones"]:
            p.setPen(QPen(colours.get(kind, QColor(255, 255, 255)), 2))
            p.drawLine(pt(*a_), pt(*b_))
        p.setPen(QPen(QColor(20, 20, 20), 1))
        for (x, y), planted in rig["contacts"]:
            p.setBrush(QColor(60, 220, 90) if planted else QColor(240, 70, 70))
            p.drawEllipse(pt(x, y), 4, 4)
        p.setPen(QPen(QColor(120, 255, 160), 1, Qt.PenStyle.DashLine))
        p.drawLine(pt(0, rig["ground"]), pt(w, rig["ground"]))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)


class PetStudio(QDialog):
    """The editor. Emits ``use_pet(genome, baked)``."""
    use_pet = pyqtSignal(object, object)     # Genome, Baked | None

    def __init__(self, store=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pet Studio")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.store = store
        self.history = api.History()
        self._coalesce: tuple[str, float] | None = None
        self._loading = False
        self._baked: api.Baked | None = None
        self.genome = self._initial_genome()
        self.saved = self.genome.copy()

        self.baker = cq.Baker(self)
        self.baker.ready.connect(self._on_baked)
        self.baker.failed.connect(self._on_bake_failed)
        self.builder = cq.Builder(self)             # slider drags: built off the GUI thread
        self.builder.built.connect(self._on_built)
        self._bake_debounce = QTimer(self)
        self._bake_debounce.setSingleShot(True)
        self._bake_debounce.setInterval(400)
        self._bake_debounce.timeout.connect(self._prebake)
        self._pending_use = False
        self._closed = False

        self._build()
        self._load_into_controls()
        self._refresh()
        self.resize(1080, 700)

    # ---- data -----------------------------------------------------------
    def _initial_genome(self) -> api.Genome:
        cfg = self.store.config if self.store else {}
        d = cfg.get("pet_genome")
        if not species.is_cat(d):
            d = None                # nothing saved, or an animal older builds made
        if d:
            try:
                g, _ = api.genome_from_dict(d)
                return g
            except api.GenomeError:
                pass
        return api.canon_genome("feline")

    @property
    def fam(self):
        return api.family(self.genome.family)

    # ---- UI ---------------------------------------------------------------
    def _build(self) -> None:
        root = QHBoxLayout(self)
        # -- left: preview + transport
        left = QVBoxLayout()
        self.preview = PetPreview()
        left.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.state_box = QComboBox()
        row.addWidget(QLabel("State:"))
        row.addWidget(self.state_box, 1)
        self.face_btn = QPushButton("Facing →")
        self.face_btn.clicked.connect(self._toggle_facing)
        row.addWidget(self.face_btn)
        left.addLayout(row)
        row = QHBoxLayout()
        self.prev_btn = QPushButton("◀")
        self.play_btn = QPushButton("Pause")
        self.next_btn = QPushButton("▶")
        self.prev_btn.setToolTip("Previous frame")
        self.next_btn.setToolTip("Next frame")
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn.clicked.connect(lambda: self._step(1))
        self.play_btn.clicked.connect(self._toggle_play)
        for b in (self.prev_btn, self.play_btn, self.next_btn):
            row.addWidget(b)
        self.slow_box = QComboBox()
        for lab, v in (("1×", 1.0), ("½×", 0.5), ("¼×", 0.25)):
            self.slow_box.addItem(lab, v)
        self.slow_box.currentIndexChanged.connect(
            lambda _: setattr(self.preview, "slow", self.slow_box.currentData()))
        row.addWidget(QLabel("Speed:"))
        row.addWidget(self.slow_box)
        left.addLayout(row)
        row = QHBoxLayout()
        self.bg_box = QComboBox()
        self.bg_box.addItems(BACKGROUNDS)
        self.bg_box.currentIndexChanged.connect(self._set_bg)
        row.addWidget(self.bg_box)
        self.zoom_box = QComboBox()
        for zz in (2, 3, 4, 5, 6, 8):
            self.zoom_box.addItem(f"{zz}×", zz)
        self.zoom_box.setCurrentIndex(4)
        self.zoom_box.currentIndexChanged.connect(self._set_zoom)
        row.addWidget(QLabel("Zoom:"))
        row.addWidget(self.zoom_box)
        self.rig_box = QCheckBox("Show rig")
        self.rig_box.setToolTip("Joints, legs, tail and ground contacts "
                                "(green = planted paw)")
        self.rig_box.toggled.connect(self._set_rig)
        row.addWidget(self.rig_box)
        left.addLayout(row)
        root.addLayout(left, 3)

        # -- right: controls
        right = QVBoxLayout()
        top = QGridLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name (optional)")
        self.name_edit.textChanged.connect(self._name_changed)
        top.addWidget(QLabel("Name:"), 0, 0)
        top.addWidget(self.name_edit, 0, 1, 1, 3)
        self.voice_btn = QPushButton("\U0001F50A")
        self.voice_btn.setFixedWidth(34)
        self.voice_btn.setToolTip("Hear its meow")
        self.voice_btn.clicked.connect(self._hear_voice)
        top.addWidget(QLabel("Voice:"), 1, 0)
        top.addWidget(self.voice_btn, 1, 1, Qt.AlignmentFlag.AlignLeft)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2_000_000_000)
        self.seed_spin.setToolTip("Same seed + same locks = the same pet")
        self.seed_spin.editingFinished.connect(self._seed_entered)
        top.addWidget(QLabel("Seed:"), 1, 2)
        top.addWidget(self.seed_spin, 1, 3)
        self.sample_box = QComboBox()
        self.sample_box.setToolTip("Start from one of the saved sample pets")
        self.sample_box.activated.connect(self._sample_chosen)
        top.addWidget(QLabel("Samples:"), 3, 0)
        top.addWidget(self.sample_box, 3, 1, 1, 3)
        self.new_btn = QPushButton("\U0001F3B2  New pet")
        self.new_btn.setToolTip("Roll a new pet (locked groups stay as they are)")
        self.new_btn.clicked.connect(self._new_pet)
        top.addWidget(self.new_btn, 2, 0, 1, 4)
        right.addLayout(top)

        self.preset_row = QHBoxLayout()
        right.addLayout(self.preset_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.genes_host = QWidget()
        self.genes_layout = QVBoxLayout(self.genes_host)
        scroll.setWidget(self.genes_host)
        right.addWidget(scroll, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        right.addWidget(self.progress)

        row = QHBoxLayout()
        self.undo_btn = QPushButton("↶ Undo")
        self.redo_btn = QPushButton("↷ Redo")
        self.reset_btn = QPushButton("Reset to saved")
        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn.clicked.connect(self._redo)
        self.reset_btn.clicked.connect(self._reset)
        for b in (self.undo_btn, self.redo_btn, self.reset_btn):
            row.addWidget(b)
        right.addLayout(row)
        row = QHBoxLayout()
        self.save_btn = QPushButton("Save to file…")
        self.load_btn = QPushButton("Open file…")
        self.save_btn.clicked.connect(self._save_file)
        self.load_btn.clicked.connect(self._load_file)
        row.addWidget(self.save_btn)
        row.addWidget(self.load_btn)
        right.addLayout(row)
        row = QHBoxLayout()
        self.use_btn = QPushButton("\U0001F43E  Use as my pet")
        self.use_btn.setDefault(True)
        self.use_btn.clicked.connect(self._use)
        row.addStretch(1)
        row.addWidget(self.use_btn)
        right.addLayout(row)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        right.addWidget(close)
        root.addLayout(right, 2)

        from PyQt6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self._redo)
        QShortcut(QKeySequence("Space"), self, activated=self._toggle_play)
        QShortcut(QKeySequence("Left"), self, activated=lambda: self._step(-1))
        QShortcut(QKeySequence("Right"), self, activated=lambda: self._step(1))
        self.state_box.currentIndexChanged.connect(self._state_changed)

    def _rebuild_gene_controls(self) -> None:
        while self.genes_layout.count():
            it = self.genes_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        while self.preset_row.count():
            it = self.preset_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.controls: dict[tuple[str, str], QWidget] = {}
        self.locks: dict[str, QCheckBox] = {}
        presets = getattr(self.fam, "presets", {})
        if presets:
            box = QGroupBox("Quick coats")
            grid = QGridLayout(box)
            for k, (name, genes) in enumerate(presets.items()):
                b = QPushButton(name)
                b.clicked.connect(lambda _=False, g=genes, n=name: self._apply_preset(n, g))
                grid.addWidget(b, k // 5, k % 5)
            self.preset_row.addWidget(box)
        groups: dict[str, list] = {}
        for gene in self.fam.schema:
            groups.setdefault(gene.group, []).append(gene)
        for group, genes in groups.items():
            box = QGroupBox(GROUP_LABELS.get(group, group.capitalize()))
            v = QVBoxLayout(box)
            lock = QCheckBox("\U0001F512 Lock")
            lock.setToolTip("Keep this group when rolling a New pet")
            self.locks[group] = lock
            v.addWidget(lock)
            form = QFormLayout()
            for gene in genes:
                w = self._make_control(gene)
                self.controls[(group, gene.name)] = w
                lab = QLabel(gene.label or gene.name)
                if gene.doc:
                    lab.setToolTip(gene.doc)
                form.addRow(lab, w)
            v.addLayout(form)
            self.genes_layout.addWidget(box)
        self.genes_layout.addStretch(1)

    def _make_control(self, gene) -> QWidget:
        key = (gene.group, gene.name)
        if gene.kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda v, k=key: self._gene_changed(k, bool(v)))
            return w
        if gene.kind == "choice":
            w = QComboBox()
            for c in gene.choices:
                w.addItem(str(c).capitalize() if c else "Automatic", c)
            w.currentIndexChanged.connect(
                lambda _i, k=key, ww=w: self._gene_changed(k, ww.currentData()))
            return w
        if gene.kind in ("int", "seed"):
            w = QSpinBox()
            w.setRange(int(gene.lo), int(gene.hi))
            w.valueChanged.connect(lambda v, k=key: self._gene_changed(k, int(v)))
            return w
        # float: slider with a value readout
        host = QWidget()
        h = QHBoxLayout(host)
        h.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(0, 100)
        lab = QLabel()
        lab.setMinimumWidth(36)
        h.addWidget(s, 1)
        h.addWidget(lab)
        host.slider, host.readout = s, lab
        lo, hi = float(gene.lo), float(gene.hi)

        def moved(v, k=key, lo=lo, hi=hi, lab=lab):
            val = lo + (hi - lo) * v / 100.0
            lab.setText(f"{val:.2f}")
            self._gene_changed(k, round(val, 3))
        s.valueChanged.connect(moved)
        return host

    def _set_control(self, gene, value) -> None:
        w = self.controls[(gene.group, gene.name)]
        if gene.kind == "bool":
            w.setChecked(bool(value))
        elif gene.kind == "choice":
            i = w.findData(value)
            w.setCurrentIndex(max(0, i))
        elif gene.kind in ("int", "seed"):
            w.setValue(int(value))
        else:
            lo, hi = float(gene.lo), float(gene.hi)
            pos = 0 if hi == lo else round((float(value) - lo) / (hi - lo) * 100)
            w.slider.setValue(int(pos))
            w.readout.setText(f"{float(value):.2f}")

    def _load_into_controls(self) -> None:
        self._loading = True
        try:
            if not hasattr(self, "controls"):
                self._rebuild_gene_controls()
            for gene in self.fam.schema:
                self._set_control(gene, self.genome.get(gene.group, gene.name, gene.default))
            self.seed_spin.setValue(int(self.genome.seed) % 2_000_000_000)
            if not hasattr(self, "_samples"):
                self._samples = api.samples(self.genome.family)
                self.sample_box.clear()
                self.sample_box.addItem("Pick a sample…", -1)
                for k, sg in enumerate(self._samples):
                    self.sample_box.addItem(sg.name or f"Sample {k + 1}", k)
            self.name_edit.setText(self.genome.name)
            cur = self.state_box.currentData()
            self.state_box.blockSignals(True)
            self.state_box.clear()
            pet_states = self.fam.states()
            for s in pet_states:
                self.state_box.addItem(STATE_LABELS.get(s, s), s)
            self.state_box.setCurrentIndex(max(0, self.state_box.findData(cur or "sit")))
            self.state_box.blockSignals(False)
        finally:
            self._loading = False

    # ---- editing ---------------------------------------------------------------
    def _push(self, coalesce_key: str | None = None) -> None:
        """Remember the current genes for undo. Consecutive changes to the
        same control within a second (a slider drag) become one step."""
        import time
        now = time.monotonic()
        if (coalesce_key and self._coalesce and self._coalesce[0] == coalesce_key
                and now - self._coalesce[1] < 1.0):
            self._coalesce = (coalesce_key, now)
            return
        self._coalesce = (coalesce_key, now) if coalesce_key else None
        self.history.push(self.genome.to_dict())

    def _gene_changed(self, key, value) -> None:
        if self._loading:
            return
        group, name = key
        if self.genome.genes.get(group, {}).get(name) == value:
            return
        self._push(f"{group}.{name}")
        self.genome.genes.setdefault(group, {})[name] = value
        self._refresh(soon=True)

    def _name_changed(self, text: str) -> None:
        if not self._loading:
            self.genome.name = text.strip()[:40]

    def _locked(self) -> set[str]:
        return {g for g, cb in self.locks.items() if cb.isChecked()}

    def _new_pet(self) -> None:
        seed = int.from_bytes(os.urandom(4), "little") % 2_000_000_000
        self._roll(seed)

    def _seed_entered(self) -> None:
        if self._loading:
            return
        seed = self.seed_spin.value()
        if seed != self.genome.seed:
            self._roll(seed)

    def _roll(self, seed: int) -> None:
        self._push()
        g = api.new_genome(self.genome.family, seed, base=self.genome,
                           locked=self._locked())
        g.name = self.genome.name
        self.genome = g
        self._load_into_controls()
        self._refresh()
        if g.notes:
            self.status.setText("Tidied: " + "; ".join(g.notes))

    def _hear_voice(self) -> None:
        from . import chime
        vol = int((self.store.config if self.store else {}).get("sound_volume", 70))
        chime.play("voice", max(vol, 40))

    def _sample_chosen(self, _i: int) -> None:
        k = self.sample_box.currentData()
        if k is None or k < 0:
            return
        self._push()
        self.genome = self._samples[k].copy()
        self._load_into_controls()
        self._refresh()
        self.status.setText(f"Sample: {self.genome.name}")
        self.sample_box.setCurrentIndex(0)

    def _apply_preset(self, name: str, genes: dict) -> None:
        self._push()
        for group, vals in genes.items():
            self.genome.genes.setdefault(group, {}).update(vals)
        self._load_into_controls()
        self._refresh()
        self.status.setText(f"Coat: {name}")

    def _undo(self) -> None:
        d = self.history.undo(self.genome.to_dict())
        if d is not None:
            self._restore(d)

    def _redo(self) -> None:
        d = self.history.redo(self.genome.to_dict())
        if d is not None:
            self._restore(d)

    def _restore(self, d: dict) -> None:
        g, _ = api.genome_from_dict(d)
        self.genome = g
        self._coalesce = None
        self._load_into_controls()
        self._refresh()

    def _reset(self) -> None:
        self._push()
        self.genome = self.saved.copy()
        self._load_into_controls()
        self._refresh()
        self.status.setText("Back to your saved pet.")

    # ---- preview -----------------------------------------------------------------
    def _refresh(self, soon: bool = False) -> None:
        """Redraw the preview for the current genes. ``soon``: build the cat
        in the background (a slider drag sends many edits a second; building
        each on the GUI thread would make the window stutter)."""
        self._baked = None
        self.undo_btn.setEnabled(self.history.can_undo())
        self.redo_btn.setEnabled(self.history.can_redo())
        if soon:
            self._bake_debounce.stop()             # restarted once the preview is in
            self.builder.request(self.genome)
            return
        try:
            pet = api.Creature(self.genome)
        except Exception as e:  # noqa: BLE001 - show, don't crash the editor
            self.status.setText(f"⚠ This pet can't be drawn: {e}")
            return
        self._show_pet(pet)

    def _on_built(self, genome, result) -> None:
        if self._closed or genome.key() != self.genome.key():
            return                                  # edited again since
        if isinstance(result, Exception):
            self.status.setText(f"⚠ This pet can't be drawn: {result}")
            return
        self._show_pet(result)

    def _show_pet(self, pet) -> None:
        self.preview.set_pet(pet)
        self._bake_debounce.start()

    def _prebake(self) -> None:
        """Bake in the background once edits settle, so Use is instant."""
        if self._closed:
            return                  # (closed while an edit was settling)
        self.baker.request(self.genome)

    def _on_baked(self, b) -> None:
        if b.key != self.genome.key():
            return                                  # edited since; stale
        self._baked = b
        if self._pending_use:
            self._pending_use = False
            self._finish_use()

    def _on_bake_failed(self, msg: str) -> None:
        self.progress.setVisible(False)
        self._pending_use = False
        self.use_btn.setEnabled(True)
        self.status.setText(f"⚠ Couldn't prepare this pet: {msg}")

    def _state_changed(self, _i) -> None:
        s = self.state_box.currentData()
        if s:
            self.preview.set_state(s)

    def _toggle_facing(self) -> None:
        self.preview.facing *= -1
        self.preview.update()
        self.face_btn.setText("Facing →" if self.preview.facing > 0 else "← Facing")

    def _toggle_play(self) -> None:
        self.preview.playing = not self.preview.playing
        self.play_btn.setText("Pause" if self.preview.playing else "Play")

    def _step(self, d: int) -> None:
        self.preview.step_frame(d)
        self.play_btn.setText("Play")

    def _set_bg(self, i: int) -> None:
        self.preview.bg = i
        self.preview.update()

    def _set_zoom(self, _i: int) -> None:
        self.preview.zoom = self.zoom_box.currentData()
        self.preview.update()

    def _set_rig(self, on: bool) -> None:
        self.preview.show_rig = on
        self.preview.update()

    # ---- files -------------------------------------------------------------------
    def _save_file(self) -> None:
        name = (self.genome.name or "pet").replace("/", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save pet", str(presets_dir() / f"{name}.pisipet.json"),
            "PISI pet (*.pisipet.json *.json)")
        if not path:
            return
        try:
            Path(path).write_text(self.genome.to_json(), "utf-8")
            self.status.setText(f"Saved {Path(path).name}")
        except OSError as e:
            QMessageBox.warning(self, "Pet Studio", f"Couldn't save: {e}")

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open pet", str(presets_dir()), "PISI pet (*.pisipet.json *.json)")
        if path:
            self.load_path(path)

    def load_path(self, path: str) -> bool:
        try:
            text = Path(path).read_text("utf-8")
            g, warns = api.genome_from_json(text)
        except (OSError, api.GenomeError) as e:
            QMessageBox.warning(self, "Pet Studio", f"Couldn't open that pet:\n{e}")
            return False
        self._push()
        self.genome = g
        self._load_into_controls()
        self._refresh()
        self.status.setText("Opened." + (" Notes: " + "; ".join(warns[:4]) if warns else ""))
        return True

    # ---- apply ---------------------------------------------------------------------
    def _use(self) -> None:
        if self._baked is not None and self._baked.key == self.genome.key():
            self._finish_use()
            return
        self._pending_use = True
        self.use_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText("Getting your pet ready…")
        self.baker.request(self.genome)

    def _finish_use(self) -> None:
        self.progress.setVisible(False)
        self.use_btn.setEnabled(True)
        if self.store is not None:
            self.store.config["pet_genome"] = self.genome.to_dict()
            self.store.save()
        b = self._baked
        if b is not None:
            try:
                cq.save_cache(b)
            except Exception:  # noqa: BLE001 - cache is best effort
                pass
        self.saved = self.genome.copy()
        self.use_pet.emit(self.genome.copy(), b)
        self.status.setText("✓ That's your pet now.")

    def closeEvent(self, e) -> None:
        # no bake may start after this: a timer firing later would start one
        # in a thread that outlives the window (Qt aborts when it goes)
        self._closed = True
        self._bake_debounce.stop()
        self.baker.shutdown(2000)
        super().closeEvent(e)

