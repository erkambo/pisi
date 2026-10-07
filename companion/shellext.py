"""Installing PISI's panel extension (see panelbridge.py and extensions/).

Cinnamon and GNOME Shell keep clicks on their panels and docks for
themselves; a small extension makes the corner's things clickable there.
This puts it where the desktop looks for it and switches it on. KDE Plasma
doesn't need one: its panel is an ordinary window, and the corner stands
above it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .paths import app_root

UUID = "pisi-corner@pisi"
SOURCE = app_root() / "extensions"          # the source checkout, or the packaged app


def desktop(env=None) -> str | None:
    """"cinnamon", "gnome", "kde", or None (something else)."""
    env = os.environ if env is None else env
    cur = (env.get("XDG_CURRENT_DESKTOP", "") + ":" + env.get("DESKTOP_SESSION", "")).lower()
    if "cinnamon" in cur:
        return "cinnamon"
    if "gnome" in cur or "ubuntu" in cur or "unity" in cur:
        return "gnome"
    if "kde" in cur or "plasma" in cur:
        return "kde"
    return None


def needed(shell: str | None) -> bool:
    return shell in ("cinnamon", "gnome")


def _home_dir(shell: str) -> Path:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data / ("cinnamon/extensions" if shell == "cinnamon" else "gnome-shell/extensions") / UUID


def _version(d: Path) -> int:
    try:
        return int(json.loads((d / "metadata.json").read_text())["version"])
    except Exception:  # noqa: BLE001 - missing or odd: treat as not there
        return 0


def installed(shell: str) -> bool:
    return (_home_dir(shell) / "metadata.json").exists()


def enabled(shell: str) -> bool:
    if shell == "cinnamon":
        return UUID in (_cinnamon_enabled() or [])
    if shell == "gnome":
        out = _run(["gnome-extensions", "list", "--enabled"])
        return out is not None and UUID in out.split()
    return False


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _cinnamon_enabled() -> list[str] | None:
    """Cinnamon's switched-on extensions, or None if they can't be read (then
    nothing is written: writing a guessed list would switch off your others)."""
    out = _run(["gsettings", "get", "org.cinnamon", "enabled-extensions"])
    if not out:
        return None
    out = out.strip()
    if out.startswith("@as"):
        out = out[3:].strip()
    try:
        return list(json.loads(out.replace("'", '"')))
    except ValueError:
        return None


def install(shell: str | None = None, enable: bool = True) -> str:
    """Copy the extension in (or refresh an older copy) and switch it on.
    Returns what happened, in a sentence for a speech bubble."""
    shell = shell or desktop()
    if not needed(shell):
        return "nothing to do here: your panel lets clicks through"
    src = SOURCE / shell / UUID
    if not (src / "metadata.json").exists():
        return "the panel extension isn't in this copy of PISI"
    dst = _home_dir(shell)
    if _version(dst) < _version(src) or not (dst / "extension.js").exists():
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
    if not enable:
        return "installed"
    if shell == "cinnamon":
        on = _cinnamon_enabled()
        if on is None:
            return "installed: switch it on in System Settings → Extensions"
        if UUID not in on:
            vals = ", ".join(f"'{u}'" for u in on + [UUID])
            if _run(["gsettings", "set", "org.cinnamon", "enabled-extensions", f"[{vals}]"]) is None:
                return "installed: switch it on in System Settings → Extensions"
        return "done! the corner's things are clickable on the panel now"
    # GNOME: on Wayland the shell only finds new extensions after you log in again
    if _run(["gnome-extensions", "enable", UUID]) is None:
        return "installed: log out and back in, then switch on “PISI's corner” in Extensions"
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return "installed: log out and back in to finish"
    return "done! the corner's things are clickable over the dock now"


def refresh() -> None:
    """At start-up: if an older copy is installed, bring it up to date
    (it stays on or off as you had it)."""
    shell = desktop()
    if needed(shell) and installed(shell) and _version(_home_dir(shell)) < _version(SOURCE / shell / UUID):
        install(shell, enable=False)


def uninstall(shell: str | None = None) -> bool:
    shell = shell or desktop()
    if not needed(shell):
        return False
    if shell == "cinnamon":
        on = _cinnamon_enabled()
        if on is not None and UUID in on:
            _run(["gsettings", "set", "org.cinnamon", "enabled-extensions",
                  "[" + ", ".join(f"'{u}'" for u in on if u != UUID) + "]"])
    else:
        _run(["gnome-extensions", "disable", UUID])
    d = _home_dir(shell)
    if d.exists():
        shutil.rmtree(d)
        return True
    return False
