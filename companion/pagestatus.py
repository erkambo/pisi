"""What the browser extension's icon shows: can the cat use the page you're on?

PISI works this out (the extension can't: it doesn't know where the cat is,
whether it's napping through a focus block, or whether the page has been
found on screen) and sends it back over the bridge as
``{"type": "page", "tab": <browser tab id>, "state": ..., "why": ...}``,
whenever it changes and every few seconds besides (so a freshly reloaded
extension catches up). The extension turns it into a badge on its icon.

States:

* ``on``       the cat can play on this page
* ``finding``  the page is in view but PISI is still checking where it is
* ``napping``  a focus block is on: the cat stays down, pages wait
* ``guarding`` a focus block is on and this is a site you asked it to guard:
               the cat is sitting on it
* ``away``     you're in another window (or another tab has the cat's eye)
* ``off``      web pages are switched off in PISI's settings
"""
from __future__ import annotations

import time

WHY = {
    "on": "PISI can play on this page",
    "finding": "PISI is finding this page on your screen…",
    "napping": "PISI is napping through your focus block",
    "guarding": "PISI is guarding your focus block",
    "away": "PISI is watching another window",
    "off": "Web pages are switched off in PISI's settings",
}
RESEND_S = 5.0          # repeat the current state this often (cheap, a few bytes)


def state(web, focusing: bool, perch_on: bool, guarding: bool = False) -> str | None:
    """The state of the page the cat would use (None: no page has spoken)."""
    if web._active is None:
        return None
    if not perch_on:
        return "off"
    if guarding:
        return "guarding"
    if focusing:
        return "napping"
    if not web.active:
        return "away"
    return "on" if web.located else "finding"


class PageStatus:
    """Sends the active page's state to its tab; a tab that stops being the
    active one is told it's ``away``."""

    def __init__(self, web, send, clock=time.monotonic) -> None:
        self.web, self.send, self.clock = web, send, clock
        self._last: tuple | None = None          # (key, state) last sent
        self._sent_at = -1e9

    def update(self, focusing: bool, perch_on: bool, guarding: bool = False) -> None:
        key = self.web._active
        st = state(self.web, focusing, perch_on, guarding)
        now = self.clock()
        if self._last is not None and self._last[0] != key:
            self._post(self._last[0], "away")     # the old page lost the cat's eye
            self._last = None
        if key is None or st is None:
            return
        if self._last == (key, st) and now - self._sent_at < RESEND_S:
            return
        self._post(key, st)
        self._last, self._sent_at = (key, st), now

    def _post(self, key, st: str) -> None:
        conn, tab = key
        if tab is None:
            return
        self.send({"type": "page", "tab": tab, "state": st, "why": WHY[st]}, conn)
