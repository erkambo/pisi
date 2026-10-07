"""Application logging.

A tray app has no console, and much of the code is intentionally best-effort
(network, calendar, desktop integration) — so failures were being swallowed
silently, leaving nothing to debug. This wires a rotating log file in the data
dir so those failures leave a trace, without ever crashing the app.

Usage:
    from .log import get_logger
    log = get_logger(__name__)
    ...
    except Exception:
        log.warning("calendar refresh failed", exc_info=True)
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .paths import log_file

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging once. Safe to call more than once (no-op after
    the first). Logs to a rotating file in the data dir, plus WARNING+ to
    stderr for anyone running from a terminal."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger("companion")
    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    try:
        fh = RotatingFileHandler(log_file(), maxBytes=512_000, backupCount=2,
                                 encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass                       # a read-only home shouldn't stop the app

    import sys
    if sys.stderr is not None:     # None under pythonw.exe / a windowed .exe
        sh = logging.StreamHandler()
        sh.setLevel(logging.WARNING)
        sh.setFormatter(fmt)
        root.addHandler(sh)


def get_logger(name: str) -> logging.Logger:
    """A module logger under the shared "companion" root. Accepts __name__
    (e.g. "companion.gcal") and returns that logger."""
    if not name.startswith("companion"):
        name = f"companion.{name}"
    return logging.getLogger(name)
