"""PISI is a cat: the words and sounds that go with that.

Everything cat-flavoured that the app *says* or *plays* (its treat, its toy,
its meow, what it says when you pet it) reads from :data:`CAT`, so the
wording lives in one place. Qt-free: the chime player and tests use it too.
"""
from __future__ import annotations

from dataclasses import dataclass

FAMILY = "feline"           # the creature family PISI is drawn as


@dataclass(frozen=True)
class Species:
    noun: str                   # "cat"
    face: str                   # the happy face used at the end of lines
    cheeky: str                 # the smug / mischievous face
    voice: str                  # sound clip (assets/sounds/<voice>.wav)
    voice_label: str            # "Meow" (sound menu)
    happy: str                  # contented sound clip
    happy_label: str            # "Purr"
    treat: str                  # emoji of the reward currency
    treat_name: str             # "fish treat"
    reactions: tuple[str, ...]  # lines when you pet it


CAT = Species(
    noun="cat", face="\U0001F638", cheeky="\U0001F63C",
    voice="meow", voice_label="Meow", happy="purr", happy_label="Purr",
    treat="\U0001F41F", treat_name="fish treat",
    reactions=("*purr* \U0001F49B", "meow!", "*happy tail swish*", "\U0001F63A",
               "*nuzzles*", "hehe, that tickles", "*content purr*"),
)


def is_cat(genome: object) -> bool:
    """Whether a saved pet genome (a dict) is a cat. Older builds could make
    a dog, fox or rabbit; those are drawn as the default cat now."""
    return isinstance(genome, dict) and genome.get("family") == FAMILY


def sound_clips() -> set[str]:
    """The clips the cat plays; the chime menu hides these as raw files."""
    return {CAT.voice, CAT.happy}
