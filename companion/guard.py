"""The cat guards your focus.

In the browser extension's menu you can mark a site as distracting. During a
focus block, open one and the cat gets up from its nap, leaps onto the page
and sits in the middle of it until you leave. Drag it off and it lets you
have that tab for five minutes; drag it off again in the same block and it
gives you less each time (three minutes, then one).

The extension decides which pages are guarded and only says so with a flag:
PISI never learns the site.
"""
from __future__ import annotations

import time

# each drag-off in the same focus block: how long you get, and what it says
SNOOZES = ((5 * 60, "Fine. Five minutes."),
           (3 * 60, "Again? Three minutes."),
           (60, "One minute. Then I'm back."))
SNOOZE_S = SNOOZES[0][0]


class Guard:
    def __init__(self, web, sprite, clock=time.monotonic) -> None:
        self.web, self.sprite, self.clock = web, sprite, clock
        self._snoozed: dict = {}                 # tab key -> until when
        self._shoos = 0                          # drag-offs this focus block
        sprite.shooed.connect(self.snooze)

    def wanted(self, focusing: bool) -> bool:
        if not focusing or not self.web.guarded():
            return False
        return self._snoozed.get(self.web._active, 0.0) <= self.clock()

    def new_block(self) -> None:
        """A new focus block: the cat's patience is back to full."""
        self._shoos = 0
        self._snoozed = {}

    def update(self, focusing: bool) -> None:
        """``focusing``: a focus block is running (not paused, not a break)."""
        want = self.wanted(focusing)
        if want != self.sprite._guarding:
            self.sprite.guard(want, nap=focusing)

    def snooze(self) -> None:
        """You dragged the cat off: this tab is yours for a few minutes, fewer
        each time you do it in the same block."""
        now = self.clock()
        secs, line = SNOOZES[min(self._shoos, len(SNOOZES) - 1)]
        self._shoos += 1
        self._snoozed = {k: t for k, t in self._snoozed.items() if t > now}
        self._snoozed[self.web._active] = now + secs
        self.sprite.guard(False)
        self.sprite.say(line)
