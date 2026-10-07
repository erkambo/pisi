"""Measure what a pet costs at runtime (CPU per second of animation, sheet
memory, bake/cache times). Uses the real CatSprite tick+paint path.

    QT_QPA_PLATFORM=offscreen python3 scripts/pet_bench.py [seconds]

Offscreen painting skips the compositor, so absolute numbers are a lower
bound for a real desktop; comparisons between runs are fair.
"""
import os
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPoint  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from companion.creatures import api  # noqa: E402
from companion.creatures import qt as cq  # noqa: E402
from companion.sprite import TICK_MS, CatSprite  # noqa: E402

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def run(sheet, state, gait="walk"):
    sp = CatSprite(speed=2.0)
    sp.timer.stop()
    sp.set_sheet(sheet, {})
    sp.move(200, 300)
    sp._sync_fpos()
    sp.show()
    ticks = int(SECS * 1000 / TICK_MS)
    sp.state = state
    sp.gait = gait
    t0 = time.process_time()
    times = []
    for k in range(ticks):
        if state == "walk":
            sp.target = QPoint(sp.x() + (400 if k % 200 < 100 else -400), 300)
            sp.state = "walk"
        a = time.perf_counter()
        sp._tick()
        sp.repaint()
        app.processEvents()
        times.append((time.perf_counter() - a) * 1000)
    cpu = time.process_time() - t0
    sp.close()
    sp.deleteLater()
    times.sort()
    return {"cpu_pct_of_core": round(100 * cpu / SECS, 2),
            "tick_ms_p50": round(times[len(times) // 2], 3),
            "tick_ms_p95": round(times[int(len(times) * 0.95)], 3),
            "tick_ms_p99": round(times[int(len(times) * 0.99)], 3)}


out = {}
g = api.canon_genome()
t = time.perf_counter()
baked = api.Creature(g).bake()
out["bake_cold_ms"] = round((time.perf_counter() - t) * 1000)
tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "pet_bench_cache"
tmp.mkdir(exist_ok=True)
t = time.perf_counter()
cq.save_cache(baked, tmp)
out["cache_write_ms"] = round((time.perf_counter() - t) * 1000)
t = time.perf_counter()
b2 = cq.load_cache(g.key(), tmp)
out["cache_read_ms"] = round((time.perf_counter() - t) * 1000)
t = time.perf_counter()
proc = cq.sheet_from_baked(b2)
out["sheet_upload_ms"] = round((time.perf_counter() - t) * 1000)
out["frames"] = sum(len(v) for v in proc.anims.values()) + sum(len(v) for v in proc.anims_left.values())
out["pixel_bytes"] = b2.nbytes()
for st in ("sit", "walk"):
    out[f"procedural:{st}"] = run(proc, st)
out["max_rss_mb"] = round(rss_mb(), 1)
for k, v in out.items():
    print(f"{k}: {v}")
