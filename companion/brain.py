"""What the cat says on its own: a hello, a reaction when you pet it, and
self-care reminders. Curated lines, entirely offline."""
from __future__ import annotations

import random
from datetime import datetime

from . import species, sysinfo
from .store import Store

GREETINGS = {
    "morning": ["Morning! ☀️", "Good morning \U0001F31E", "A fresh day \U0001F343"],
    "afternoon": ["Afternoon!", "Hey, how's the day going?", "Good afternoon \U0001F60A"],
    "evening": ["Evening \U0001F319", "Good evening!", "Winding down?"],
    "night": ["It's late \U0001F319", "Burning the midnight oil?", "Still up?"],
}

# Self-care, not small talk: the reminders worth an interruption.
CARE_LINES = [
    "posture check \U0001FA91", "hydrate? \U0001F4A7", "take a breath \U0001F343",
    "stand up and stretch with me \U0001F646",
    "look at something far away for 20 seconds \U0001F440",
]


class Brain:
    def __init__(self, store: Store):
        self.store = store

    def name(self) -> str:
        return self.store.config.get("cat_name") or "Pisi"

    def greeting(self, now: datetime | None = None) -> str:
        return random.choice(GREETINGS[sysinfo.part_of_day(now or datetime.now())])

    def pet_reaction(self) -> str:
        return random.choice(species.CAT.reactions)

    def care_line(self) -> str:
        return random.choice(CARE_LINES)
