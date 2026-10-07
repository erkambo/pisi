"""Shared test data. A fresh Store starts with no habits (they're personal),
so tests that need some add a small sample set here."""
from companion.store import Store

SAMPLE_HABITS = (("Textbook", "\U0001F4D6", "daily"),
                 ("LeetCode", "\U0001F4BB", "daily"),
                 ("Workout", "\U0001F3CB", "every2-3"))


def sample_store() -> Store:
    """A Store with the sample habits (added once; a reload keeps them)."""
    s = Store()
    if not s.habits:
        for name, emoji, cadence in SAMPLE_HABITS:
            s.add_habit(name, emoji, cadence)
    return s
