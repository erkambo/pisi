"""The cat's animation sheet: frames per animation, as crisp QPixmaps.

PISI draws its cat itself (``companion.creatures``); ``load`` bakes the cat
from the saved genome (the one made in Pet Studio) into a :class:`Sheet`.
"""
from __future__ import annotations

from PyQt6.QtGui import QPixmap

# app-state -> preferred animation names, in fallback order
STATE_ALIASES = {
    "sit": ["idle", "sit", "sitting", "stand", "standing"],
    "walk": ["walk", "walking", "move", "movement", "run", "running"],
    "run": ["run", "running", "walk", "walking"],
    "sleep": ["sleep", "sleeping", "lay", "laydown", "laying", "rest"],
    "yawn": ["yawn", "yawning", "meow", "idle"],
}


# per-animation frame rates (frames/sec); anything not listed uses the default
DEFAULT_ANIM_FPS = {
    "sleep": 3,     # slow, restful breathing
    "sit": 6,
    "idle": 7,
    "eat": 6,
    "meow": 13,     # quick — don't linger on the wide-open mouth frame
    "tailswish": 8,
    "lookaround": 6,
}


class Sheet:
    def __init__(self, anims: dict[str, list[QPixmap]], fps: int = 8,
                 anim_fps: dict[str, int] | None = None):
        self.anims = {k: v for k, v in anims.items() if v}
        self.fps = max(1, fps)
        self.anim_fps = anim_fps or {}
        # procedural pets (companion.creatures) also provide:
        self.anims_left: dict[str, list[QPixmap]] = {}  # drawn for facing left
        self.speed: dict[str, float] = {}       # sprite px per frame (gaits)
        self.transitions: dict[tuple[str, str], str] = {}
        # facing -> state -> per-frame anchors (mouth, head_top, paws, ground)
        self.anchors: dict[int, dict[str, list[dict]]] = {}
        self.procedural = False
        self.frame_w = self.frame_h = 32
        for frames in self.anims.values():
            if frames:
                self.frame_w = frames[0].width()
                self.frame_h = frames[0].height()
                break

    def anchor(self, name: str, i: int, facing: int = 1) -> dict | None:
        """Where the mouth / paws are in frame ``i`` of ``name`` (frame
        pixels), or None for a sheet without a rig."""
        frames = self.anchors.get(1 if facing >= 0 else -1, {}).get(name)
        return frames[i % len(frames)] if frames else None

    def fps_for(self, name: str) -> float:
        return max(1, self.anim_fps.get(name, self.fps))

    def has_any(self) -> bool:
        return bool(self.anims)

    def resolve(self, state: str) -> str | None:
        if state in self.anims:
            return state
        for name in STATE_ALIASES.get(state, [state]):
            if name in self.anims:
                return name
        # last resort: any animation at all
        return next(iter(self.anims), None)

    def frames(self, anim: str, facing: int = 1) -> list[QPixmap]:
        if facing < 0 and anim in self.anims_left:
            return self.anims_left[anim]
        return self.anims.get(anim, [])

    def mirrored(self, anim: str, facing: int) -> bool:
        """Whether a frame must be flipped to face ``facing``."""
        return facing < 0 and anim not in self.anims_left


def procedural_sheet(genome_dict: dict | None) -> Sheet | None:
    """A procedural pet (companion.creatures) as a Sheet; ``None`` genome =
    PISI's default cat. Never raises: a broken genome logs
    and falls back to the canonical cat."""
    from .log import get_logger
    log = get_logger(__name__)
    try:
        from .creatures import api
        g = api.canon_genome()
        if genome_dict:
            try:
                g, warns = api.genome_from_dict(genome_dict)
                for w in warns:
                    log.info("pet genome: %s", w)
            except api.GenomeError as e:
                log.warning("pet genome unusable (%s) — using the default cat", e)
                g = api.canon_genome()
        from .creatures import qt as cq
        return cq.load_sheet(g)
    except Exception:  # noqa: BLE001 - never block startup on the pet
        log.warning("procedural pet failed", exc_info=True)
        return None


def load(config: dict) -> Sheet | None:
    """The cat saved in Pet Studio, or the default cat. None only if the cat
    can't be drawn at all (the sprite then falls back to a simple shape)."""
    from . import species
    g = config.get("pet_genome")
    if not species.is_cat(g):
        g = None                    # nothing saved, or an animal older builds made
    return procedural_sheet(g)
