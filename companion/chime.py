"""Alert sounds for the end of a focus block or break.

Pomofocus lets you pick a tone; we do the same, but with a pet-themed twist:
PISI can meow or purr, alongside the usual chimes and a kitchen-timer ding. Clips live in ``assets/sounds/*.wav`` (see that folder's CREDITS.md).

Kept dependency-free: PyQt6 ships without QtMultimedia on many distros, so we
just hand the WAV to whatever system player is around (``pw-play`` / ``paplay``
/ ``aplay`` on Linux, ``afplay`` on macOS, ``winsound`` on Windows). Playback is
fired-and-forgotten so it never blocks the UI, and every path is best-effort:
no player, no file, no problem — the visual celebration still happens.
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

from . import species as _species
from .log import get_logger
from .paths import data_dir, sounds_dir

log = get_logger(__name__)

# Ordered catalogue: key -> menu label. "voice"/"happy" are the cat's meow and
# purr (resolve()); the rest map to ``<key>.wav`` in sounds_dir.
SOUNDS: list[tuple[str, str]] = [
    ("voice", "Pet's voice"),
    ("happy", "Pet's happy sound"),
    ("ding", "Kitchen alarm \U000023F0"),
    ("bell", "Tubular bell \U0001F390"),
    ("bowl", "Singing bowl \U0001F963"),
    ("none", "Silent \U0001F507"),
]
_LABELS = dict(SOUNDS)
# settings saved before "voice"/"happy"
LEGACY = {"meow": "voice", "purr": "happy"}


def resolve(key: str) -> str:
    """The clip a catalogue key plays."""
    key = LEGACY.get(key, key)
    if key == "voice":
        return _species.CAT.voice
    if key == "happy":
        return _species.CAT.happy
    return key


def label_for(key: str) -> str:
    sp = _species.CAT
    key = LEGACY.get(key, key)
    if key == "voice":
        return f"{sp.voice_label} {sp.face}  (pet's voice)"
    if key == "happy":
        return f"{sp.happy_label} {sp.face}  (pet's happy sound)"
    return _LABELS.get(key, key)


def sound_path(key: str) -> Path | None:
    key = resolve(key)
    if not key or key == "none":
        return None
    p = sounds_dir() / f"{key}.wav"
    return p if p.exists() else None


def available() -> list[tuple[str, str]]:
    """Catalogue entries whose file is actually present (plus 'none'), followed
    by any extra ``*.wav`` a user has dropped into the sounds folder."""
    out = [(k, label_for(k)) for k, _ in SOUNDS if k == "none" or sound_path(k)]
    known = {k for k, _ in SOUNDS} | _species.sound_clips()
    try:
        for p in sorted(sounds_dir().glob("*.wav")):
            if p.stem not in known:
                out.append((p.stem, p.stem))
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------
def _linux_cmd(path: str, volume: int) -> list[str] | None:
    # pw-play / paplay take a linear volume where 65536 == 100%.
    for exe in ("pw-play", "paplay"):
        if shutil.which(exe):
            vol = max(0, min(65536, round(volume / 100 * 65536)))
            return [exe, f"--volume={vol}", path]
    if shutil.which("aplay"):
        return ["aplay", "-q", path]        # no volume control; scaled file used
    return None


def _scaled_copy(path: Path, volume: int) -> Path:
    """A gain-adjusted copy of a PCM-16 mono/stereo WAV, cached under data_dir.

    Used when the chosen player can't set volume itself (aplay, winsound). The
    cache is keyed by name+volume so we only rebuild when the setting changes."""
    cache = data_dir() / "sound_cache"
    cache.mkdir(exist_ok=True)
    dst = cache / f"{path.stem}@{volume}.wav"
    if dst.exists() and dst.stat().st_mtime >= path.stat().st_mtime:
        return dst
    g = max(0.0, volume / 100.0)
    with wave.open(str(path), "rb") as r:
        params = r.getparams()
        frames = r.readframes(r.getnframes())
    if params.sampwidth == 2:
        cnt = len(frames) // 2
        vals = struct.unpack("<%dh" % cnt, frames)
        scaled = struct.pack(
            "<%dh" % cnt,
            *(max(-32768, min(32767, int(v * g))) for v in vals),
        )
    else:                                    # unknown width: copy verbatim
        scaled = frames
    with wave.open(str(dst), "wb") as w:
        w.setparams(params)
        w.writeframes(scaled)
    return dst


def play(key: str, volume: int = 100) -> None:
    """Play sound ``key`` at ``volume`` (0-100), without blocking. No-op if
    the sound is 'none'/missing or no audio backend is available."""
    path = sound_path(key)
    if path is None:
        return
    volume = max(0, min(100, int(volume)))
    if volume == 0:
        return
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["afplay", "-v", f"{volume / 100:.3f}", str(path)])
            return
        if sys.platform.startswith("win"):
            import winsound  # noqa: PLC0415 - Windows-only, imported lazily
            src = path if volume >= 100 else _scaled_copy(path, volume)
            winsound.PlaySound(str(src), winsound.SND_FILENAME | winsound.SND_ASYNC
                               | winsound.SND_NODEFAULT)
            return
        cmd = _linux_cmd(str(path), volume)
        if cmd and cmd[0] == "aplay" and volume < 100:
            cmd[-1] = str(_scaled_copy(path, volume))
        if cmd:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            log.info("no audio player found; skipping alert sound")
    except Exception:                        # noqa: BLE001 - never break the flow
        log.warning("could not play alert sound %r", key, exc_info=True)
