"""Measure a cat so a thing can be drawn to fit it.

Measurements come from the cat's real frames and rig anchors, never from
guessed sizes: the curl's footprint is the bounding box of the drawn curl
(every frame, so breathing fits too), the bowl's height comes from where
the mouth is while eating, the post from how high that cat reaches.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..creatures import api
from ..creatures import quadmotion as QM
from ..creatures.render import FX_WHITE

Box = tuple[int, int, int, int]      # x0, y0, x1, y1 (inclusive), frame px


@dataclass(frozen=True)
class CatFit:
    frame: tuple[int, int]       # the cat's frame size
    floor: int                   # frame row of the cat's floor (its bottom outline row)
    curl: Box                    # where the curled-up cat is drawn (all frames)
    eat_mouth: tuple[int, int]   # the mouth at the bottom of an eating bob
    toy_spot: tuple[int, int]    # where a toy lies to be picked up
    bat_target: tuple[int, int]  # the paw at the end of a swipe
    post_x: int                  # a scratching post's near face
    scratch_top: int             # top of the scratching stroke
    scratch_bottom: int
    sit_top: int                 # top of the sitting cat (its head height)
    coat: tuple[int, int, int]   # the colour most of the cat is (its main fill)
    energy: float = 0.5          # its motion genes: how lively it plays
    curious: float = 0.5

    @property
    def curl_w(self) -> int:
        return self.curl[2] - self.curl[0] + 1

    @property
    def curl_h(self) -> int:
        return self.curl[3] - self.curl[1] + 1


def _bbox(pet: api.Creature, state: str) -> Box:
    xs, ys = [], []
    for i in range(pet.states()[state].frames):
        fr, _ = pet.frame_grid(state, i, 1)
        w = fr.w
        for k, r in enumerate(fr.role):
            if r and r != FX_WHITE:              # not the z's
                xs.append(k % w)
                ys.append(k // w)
    return (min(xs), min(ys), max(xs), max(ys))


def _main_colour(pet: api.Creature) -> tuple[int, int, int]:
    from collections import Counter
    data = pet.frame("sit", 0, 1)
    c = Counter(tuple(data[i:i + 3]) for i in range(0, len(data), 4) if data[i + 3])
    return c.most_common(1)[0][0]


def measure(pet: api.Creature) -> CatFit:
    a = pet.built.anat
    w, h = pet.size
    curl = _bbox(pet, "curl")
    sit = _bbox(pet, "sit")
    eat = [pet.anchors("eat", i)["mouth"] for i in range(pet.states()["eat"].frames)]
    sg = QM.scratch_geometry(a)
    return CatFit(frame=(w, h), floor=curl[3], curl=curl,
                  eat_mouth=max(eat, key=lambda m: m[1]),
                  toy_spot=QM.toy_spot(a), bat_target=QM.bat_target(a),
                  post_x=int(sg["post_x"]), scratch_top=int(sg["top"]),
                  scratch_bottom=int(sg["bottom"]), sit_top=sit[1],
                  coat=_main_colour(pet), energy=float(pet.built.motion.energy),
                  curious=float(pet.built.motion.curious))
