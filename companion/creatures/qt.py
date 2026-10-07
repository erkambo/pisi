"""Qt adapter: baked creatures -> pixelsheet.Sheet, disk cache, async bake.

The only creature module that imports Qt. QPixmaps are created on the GUI
thread only; worker threads produce plain bytes (``Baked``), which the GUI
thread converts. A bake job carries a generation number so results from a
superseded request (e.g. a slider dragged on) are dropped, and it can be
cancelled between frames.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from ..log import get_logger
from .creature import Baked, BakeCancelled, Creature
from .genome import GENERATOR, Genome

# what the desktop pet needs; the rest is baked lazily by the editor
TRANSITIONS = {
    ("sit", "walk"): "standup", ("sit", "run"): "standup",
    ("idle", "walk"): None, ("walk", "sit"): "sitdown", ("run", "sit"): "sitdown",
    ("sit", "sleep"): "liedown", ("sleep", "sit"): "getup",
    ("idle", "sit"): "sitdown", ("sit", "idle"): "standup",
    ("sit", "curl"): "curldown", ("curl", "sit"): "curlup",
    # all played out: down flat to pant (from whatever it was doing), and back up
    ("*", "pant"): "flop", ("pant", "*"): "pantup",
}

CACHE_KEEP = 4           # baked pets kept on disk


def image_from_rgba(data: bytes, w: int, h: int) -> QImage:
    img = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return img.copy()                     # own the pixels (data may go away)


def sheet_from_baked(b: Baked):
    """Build a pixelsheet.Sheet (GUI thread)."""
    from ..pixelsheet import Sheet
    w, h = b.size
    right = {name: [QPixmap.fromImage(image_from_rgba(f, w, h)) for f in frames]
             for name, frames in b.frames.get(1, {}).items()}
    left = {name: [QPixmap.fromImage(image_from_rgba(f, w, h)) for f in frames]
            for name, frames in b.frames.get(-1, {}).items()}
    s = Sheet(right, 8, {k: v for k, v in b.fps.items()})
    s.anims_left = left
    s.speed = dict(b.speed)
    s.loop = dict(b.loop)
    s.hold_last = dict(b.hold_last)
    s.transitions = {k: v for k, v in TRANSITIONS.items() if v and v in right}
    s.procedural = True
    s.key = b.key
    s.anchors = b.anchors
    return s


def _anchors_to_json(anchors: dict) -> dict:
    return {str(fc): states for fc, states in anchors.items()}


def _anchors_from_json(d: dict) -> dict:
    def pt(v):
        return tuple(v) if isinstance(v, list) else v

    out: dict = {}
    for fc, states in (d or {}).items():
        out[int(fc)] = {name: [{"ground": an.get("ground"), "mouth": pt(an.get("mouth")),
                                "head_top": pt(an.get("head_top")),
                                "paws": {k: pt(v) for k, v in an.get("paws", {}).items()}}
                               for an in frames]
                        for name, frames in states.items()}
    return out


# ---- disk cache ---------------------------------------------------------------
def cache_dir() -> Path:
    from ..paths import data_dir
    d = data_dir() / "pets" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def save_cache(b: Baked, d: Path | None = None) -> Path | None:
    """One PNG sheet (rows = facing x state, cols = frames) + JSON next to it."""
    d = d or cache_dir()
    w, h = b.size
    rows = []
    for fc in (1, -1):
        for name, frames in b.frames.get(fc, {}).items():
            rows.append((fc, name, frames))
    if not rows:
        return None
    cols = max(len(r[2]) for r in rows)
    sheet = QImage(cols * w, len(rows) * h, QImage.Format.Format_RGBA8888)
    sheet.fill(0)
    from PyQt6.QtGui import QPainter
    p = QPainter(sheet)
    for r, (_fc, _name, frames) in enumerate(rows):
        for c, f in enumerate(frames):
            p.drawImage(c * w, r * h, image_from_rgba(f, w, h))
    p.end()
    stem = d / _digest(b.key)
    from .quadmotion import STATES
    meta = {"key": b.key, "generator": b.generator, "frame_w": w, "frame_h": h,
            "rows": [[fc, name, len(frames)] for fc, name, frames in rows],
            "full": set(STATES) <= {name for _fc, name, _f in rows},
            "fps": b.fps, "loop": b.loop, "hold_last": b.hold_last, "speed": b.speed,
            "anchors": _anchors_to_json(b.anchors)}
    tmp = stem.with_suffix(".png.tmp")
    if not sheet.save(str(tmp), "PNG"):
        return None
    tmp.replace(stem.with_suffix(".png"))
    stem.with_suffix(".json").write_text(json.dumps(meta), "utf-8")
    _prune(d)
    return stem.with_suffix(".png")


def _prune(d: Path) -> None:
    pngs = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in pngs[CACHE_KEEP:]:
        for ext in (".png", ".json"):
            try:
                old.with_suffix(ext).unlink()
            except OSError:
                pass


def load_cache(key: str, d: Path | None = None) -> Baked | None:
    d = d or cache_dir()
    stem = d / _digest(key)
    try:
        meta = json.loads(stem.with_suffix(".json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if meta.get("key") != key or meta.get("generator") != GENERATOR:
        return None
    from .quadmotion import STATES
    if meta.get("full", True) and not set(STATES) <= {row[1] for row in meta.get("rows", [])}:
        return None                     # a whole cat baked before some animations existed
    img = QImage(str(stem.with_suffix(".png")))
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = int(meta["frame_w"]), int(meta["frame_h"])
    b = Baked(key, (w, h), GENERATOR)
    for r, (fc, name, n) in enumerate(meta["rows"]):
        frames = []
        for c in range(int(n)):
            cell = img.copy(c * w, r * h, w, h)
            ptr = cell.constBits()
            ptr.setsize(w * h * 4)
            frames.append(bytes(ptr))
        b.frames.setdefault(int(fc), {})[name] = frames
    b.fps = {k: float(v) for k, v in meta.get("fps", {}).items()}
    b.loop = {k: bool(v) for k, v in meta.get("loop", {}).items()}
    b.hold_last = {k: bool(v) for k, v in meta.get("hold_last", {}).items()}
    b.speed = {k: float(v) for k, v in meta.get("speed", {}).items()}
    b.anchors = _anchors_from_json(meta.get("anchors", {}))
    try:
        stem.with_suffix(".png").touch()
    except OSError:
        pass
    return b


def baked_for(genome: Genome, use_cache: bool = True) -> Baked:
    """Synchronous: cache hit or bake (and store)."""
    key = genome.key()
    if use_cache:
        b = load_cache(key)
        if b is not None:
            return b
    b = Creature(genome).bake()
    if use_cache:
        try:
            save_cache(b)
        except Exception as e:  # noqa: BLE001 - a cache is best effort
            get_logger(__name__).warning("pet cache write failed: %s", e)
    return b


def load_sheet(genome: Genome):
    return sheet_from_baked(baked_for(genome))


# ---- async baking ----------------------------------------------------------------
_LIVE: set = set()          # every bake thread still running (see wait_all)


def wait_all(ms: int = 10000) -> bool:
    """Wait for every background bake to finish (Qt aborts the process if a
    thread object is destroyed while it runs). True if they all did."""
    ok = True
    for t in list(_LIVE):
        ok = t.wait(ms) and ok
    return ok


class _Worker(QThread):
    done = pyqtSignal(int, object)          # generation, Baked | Exception

    def __init__(self, gen: int, genome: Genome, cancel: threading.Event,
                 states=None, facings=(1, -1)) -> None:
        super().__init__()
        self.gen, self.genome, self.cancel = gen, genome, cancel
        self.states, self.facings = states, facings

    def run(self) -> None:
        try:
            b = Creature(self.genome).bake(self.states, self.facings,
                                           cancelled=self.cancel.is_set)
            self.done.emit(self.gen, b)
        except BakeCancelled:
            pass
        except Exception as e:  # noqa: BLE001 - reported to the caller
            self.done.emit(self.gen, e)


class Baker(QObject):
    """Latest-wins background baker. ``request()`` cancels the previous job;
    only the newest generation's result is ever delivered."""
    ready = pyqtSignal(object)              # Baked
    failed = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gen = 0
        self._cancel: threading.Event | None = None
        self._threads: list[_Worker] = []

    def request(self, genome: Genome, states=None, facings=(1, -1)) -> int:
        self.cancel()
        self._gen += 1
        ev = threading.Event()
        self._cancel = ev
        w = _Worker(self._gen, genome.copy(), ev, states, facings)
        w.done.connect(self._finished)
        w.finished.connect(lambda w=w: self._reap(w))
        self._threads.append(w)
        _LIVE.add(w)
        w.finished.connect(lambda w=w: _LIVE.discard(w))
        w.start()
        return self._gen

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    def _finished(self, gen: int, result) -> None:
        if gen != self._gen:
            return                          # stale: a newer request exists
        if isinstance(result, Exception):
            self.failed.emit(str(result))
        else:
            self.ready.emit(result)

    def _reap(self, w: _Worker) -> None:
        if w in self._threads:
            self._threads.remove(w)
        w.deleteLater()

    def busy(self) -> bool:
        return any(t.isRunning() for t in self._threads)

    def shutdown(self, ms: int = 3000) -> None:
        self.cancel()                         # a cancelled bake stops within a frame
        for t in list(self._threads):
            t.wait(ms)


class _BuildWorker(QThread):
    done = pyqtSignal(object, object)       # the genome built, Creature | Exception

    def __init__(self, genome: Genome) -> None:
        super().__init__()
        self.genome = genome

    def run(self) -> None:
        try:
            self.done.emit(self.genome, Creature(self.genome))
        except Exception as e:  # noqa: BLE001 - reported to the caller
            self.done.emit(self.genome, e)


class Builder(QObject):
    """Builds a :class:`Creature` off the GUI thread, newest edit wins: one
    build at a time, and edits made meanwhile collapse into one more build,
    so dragging a slider never piles up work or freezes the window."""
    built = pyqtSignal(object, object)       # Genome, Creature | Exception

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pending: Genome | None = None
        self._worker: _BuildWorker | None = None

    def request(self, genome: Genome) -> None:
        self._pending = genome.copy()
        if self._worker is None:
            self._start()

    def busy(self) -> bool:
        return self._worker is not None or self._pending is not None

    def _start(self) -> None:
        g, self._pending = self._pending, None
        w = _BuildWorker(g)
        self._worker = w
        _LIVE.add(w)
        w.done.connect(self._done)
        w.finished.connect(lambda w=w: self._reap(w))
        w.start()

    def _done(self, genome, result) -> None:
        if self._pending is None:           # nothing newer: show this one
            self.built.emit(genome, result)

    def _reap(self, w: _BuildWorker) -> None:
        _LIVE.discard(w)
        w.deleteLater()
        self._worker = None
        if self._pending is not None:
            self._start()
