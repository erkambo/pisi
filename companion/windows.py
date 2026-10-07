"""Best-effort snapshot of the windows you have open right now, so a workspace
can be built from what's already on screen instead of adding every item by hand.

On Linux this is X11 + ``wmctrl`` (a dependency-free CLI most Mint installs
have); on Windows it's EnumWindows via ctypes (see winapi.py); on macOS it's
AppleScript, which can even read browsers' real tab URLs. For each open window we learn the app, its title, and — from the process's launch
command — any real file it was opened with. Those files are the reliable part.

Browsers are the weak part: a browser window only exposes its *active tab title*,
never the URL or the other tabs, so browser rows come back as an editable *hint*
the user turns into a real link (or drops). Nothing here opens or changes anything.
"""
from __future__ import annotations

import ntpath
import os
import re
import subprocess
import sys
from urllib.parse import unquote

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# window WM_CLASS fragments we treat as browsers (title is only the active tab)
BROWSER_CLASSES = (
    "brave-browser", "google-chrome", "chrome", "chromium", "chromium-browser",
    "firefox", "navigator", "mozilla", "vivaldi", "opera", "microsoft-edge",
    "edge", "epiphany", "librewolf",
)

# trailing " - Brave" / " — Mozilla Firefox" etc. that browsers append to titles
_BROWSER_SUFFIX = re.compile(
    r"\s*[-—|]\s*(brave(?:\s+browser)?|google chrome|chromium|"
    r"mozilla firefox|firefox|vivaldi|opera|microsoft\s*edge|edge|"
    r"librewolf|epiphany|zen browser|arc)\s*$",
    re.IGNORECASE,
)

# windows never worth offering as workspace items
SKIP_CLASSES = (
    "nemo-desktop", "desktop-companion", "__main__.py", "plank", "conky",
    "gnome-terminal-server", "xfce4-terminal", "konsole",
)

# path prefixes that are almost certainly the app itself, not a document
_JUNK_PREFIXES = ("/usr/", "/opt/", "/proc/", "/sys/", "/dev/", "/snap/", "/app/")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _cmdline(pid: int) -> list[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read()
    except OSError:
        return []
    return [a.decode("utf-8", "surrogateescape")
            for a in raw.split(b"\x00") if a]


def _file_from_cmdline(pid: int) -> str | None:
    """Pick the most likely *document* the app was launched with, if any."""
    home = os.path.expanduser("~")
    found: list[str] = []
    for arg in _cmdline(pid)[1:]:            # skip argv[0] (the binary)
        p = arg
        if p.startswith("file://"):
            p = unquote(p[7:])
        if not (p.startswith("/") or p.startswith("~")):
            continue
        cand = os.path.expanduser(p)
        if not os.path.exists(cand):
            continue
        if cand.startswith(_JUNK_PREFIXES):
            continue
        found.append(cand)
    if not found:
        return None
    # prefer a real file in your home over a folder or a system path
    home_files = [c for c in found
                  if c.startswith(home) and os.path.isfile(c)
                  and "/.config/" not in c and "/.local/" not in c
                  and "/.cache/" not in c]
    return (home_files or found)[-1]


# Windows browsers decorate titles more: Edge writes "Page and 3 more pages -
# Personal - Microsoft\u200b Edge" (note the zero-width space).
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
_MORE_PAGES = re.compile(r"\s+and \d+ more pages?$", re.IGNORECASE)


def _clean_browser_title(title: str) -> str:
    title = title.translate(_ZERO_WIDTH)
    return _MORE_PAGES.sub("", _BROWSER_SUFFIX.sub("", title).strip()).strip()


def _title_variants(title: str) -> list[str]:
    """The cleaned tab title, plus the same minus a trailing " - <profile>"
    segment (Edge/Chrome can insert the profile name before the browser name)."""
    first = _clean_browser_title(title)
    out = [first]
    head, sep, tail = first.rpartition(" - ")
    if sep and head and len(tail) <= 24:
        out.append(_MORE_PAGES.sub("", head).strip())
    return out


def snapshot() -> list[dict]:
    """Return one dict per open window:

        {"kind": "file"|"url"|"app", "app": str, "title": str,
         "value": str, "suggested": bool}

    ``kind`` "file" carries a real path (suggested for saving); "url" carries a
    browser tab-title *hint* to be edited into a link; "app" is a window with no
    savable file (shown but not pre-checked). Empty list if wmctrl is missing.
    """
    if IS_WINDOWS:
        out = _snapshot_windows()
        _fill_browser_urls(out)
        return out
    if IS_MAC:
        out = _snapshot_mac()
        _fill_browser_urls(out)
        return out
    out: list[dict] = []
    for line in _run(["wmctrl", "-lxp"]).splitlines():
        # id  desktop  pid  wm.class  host  title...
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        _wid, _desk, pid_s, wm_class, _host, title = parts
        cls = wm_class.split(".")[0].lower()
        full_cls = wm_class.lower()
        if any(s in full_cls for s in SKIP_CLASSES):
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            pid = 0

        if any(b in full_cls for b in BROWSER_CLASSES):
            hint = _clean_browser_title(title)
            out.append({"kind": "url", "app": cls, "title": title,
                        "value": hint, "suggested": False})
            continue

        path = _file_from_cmdline(pid) if pid else None
        if path:
            out.append({"kind": "file", "app": cls, "title": title,
                        "value": path, "suggested": True})
        else:
            out.append({"kind": "app", "app": cls, "title": title,
                        "value": title, "suggested": False})

    _fill_browser_urls(out)
    return out


# ---- Windows ---------------------------------------------------------------
# executables (lowercase stem) that are browsers / never worth saving
WIN_BROWSERS = ("chrome", "msedge", "firefox", "brave", "vivaldi", "opera",
                "opera_gx", "chromium", "librewolf", "waterfox", "zen", "arc")
WIN_SKIP = ("explorer", "applicationframehost", "textinputhost", "shellexperiencehost",
            "searchhost", "startmenuexperiencehost", "systemsettings", "lockapp",
            "windowsterminal", "cmd", "powershell", "pwsh", "conhost", "openconsole",
            "taskmgr", "python", "pythonw", "pisi", "widgets", "gamebar",
            "nvidia overlay", "rtkuwp")


def _win_env_dirs() -> tuple[str, ...]:
    keys = ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "SystemRoot",
            "ProgramData", "LOCALAPPDATA", "APPDATA")
    return tuple(os.path.normcase(os.environ[k]) + os.sep
                 for k in keys if os.environ.get(k))


def _win_file_from_argv(argv: list[str]) -> str | None:
    """The document an app was launched with (e.g. `AcroRd32.exe C:\\x.pdf`)."""
    junk = _win_env_dirs()
    found: list[str] = []
    for arg in argv[1:]:
        p = arg.strip('"')
        if p.startswith("file:///"):
            p = unquote(p[8:]).replace("/", "\\")
        if len(p) < 3 or not (p[1:3] in (":\\", ":/") or p.startswith("\\\\")):
            continue                         # only absolute C:\… or \\server\… paths
        if not os.path.exists(p) or os.path.normcase(p).startswith(junk):
            continue
        found.append(p)
    files = [f for f in found if os.path.isfile(f)]
    return (files or found or [None])[-1]


def _snapshot_windows() -> list[dict]:
    from . import winapi
    out: list[dict] = []
    for w in winapi.top_windows():
        exe = w.get("exe") or ""
        stem = ntpath.splitext(ntpath.basename(exe))[0].lower()
        title = w["title"]
        if not stem or stem in WIN_SKIP:
            continue
        if stem in WIN_BROWSERS:
            variants = _title_variants(title)
            out.append({"kind": "url", "app": stem, "title": title,
                        "value": variants[0], "suggested": False,
                        "_variants": variants})
            continue
        path = _win_file_from_argv(winapi.process_cmdline(w["pid"]))
        if path:
            out.append({"kind": "file", "app": stem, "title": title,
                        "value": path, "suggested": True})
        else:
            # relaunching the exe is the best we can do for a plain app window
            out.append({"kind": "app", "app": f'"{exe}"', "title": title,
                        "value": title, "suggested": False})
    return out


# ---- macOS -------------------------------------------------------------------
# Scriptable browsers: AppleScript hands us each window's real, current URL.
MAC_TAB_EXPR = {
    "Safari": "URL of current tab of w",
    "Google Chrome": "URL of active tab of w",
    "Microsoft Edge": "URL of active tab of w",
    "Brave Browser": "URL of active tab of w",
    "Chromium": "URL of active tab of w",
    "Vivaldi": "URL of active tab of w",
    "Arc": "URL of active tab of w",
}
# Browsers without AppleScript: fall back to window title → history lookup
MAC_TITLE_BROWSERS = ("Firefox", "Firefox Developer Edition", "Zen", "LibreWolf",
                      "Opera", "Orion", "Waterfox")
MAC_SKIP = ("Finder", "PISI", "Python", "Terminal", "iTerm2", "Warp", "Ghostty",
            "System Settings", "System Preferences", "Activity Monitor", "Dock")

# One pass over the foreground apps. Window names/documents need Accessibility
# permission; without it those lines are simply missing (each step is in try).
_MAC_PROCS_SCRIPT = """
set out to ""
tell application "System Events"
    repeat with p in (every application process whose background only is false)
        set pname to name of p
        set ppath to ""
        try
            set ppath to POSIX path of (application file of p as alias)
        end try
        set out to out & "APP" & tab & pname & tab & ppath & linefeed
        try
            repeat with w in (every window of p)
                set t to ""
                set d to ""
                try
                    set t to name of w
                end try
                try
                    set d to value of attribute "AXDocument" of w
                end try
                if t is missing value then set t to ""
                if d is missing value then set d to ""
                set out to out & "WIN" & tab & pname & tab & t & tab & d & linefeed
            end repeat
        end try
    end repeat
end tell
return out
"""


def parse_mac_procs(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """-> ([(app, bundle_path)], [(app, window_title, document_file_url)])"""
    apps: list[tuple[str, str]] = []
    wins: list[tuple[str, str, str]] = []
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if parts[0] == "APP" and len(parts) >= 3:
            apps.append((parts[1], parts[2].rstrip("/")))
        elif parts[0] == "WIN" and len(parts) >= 4:
            wins.append((parts[1], parts[2], parts[3]))
    return apps, wins


def _mac_tab_urls(app: str) -> list[str]:
    from . import macapi
    src = (f"tell application {macapi.as_string(app)}\n"
           "    set out to \"\"\n"
           "    repeat with w in windows\n"
           f"        try\n            set out to out & ({MAC_TAB_EXPR[app]}) & linefeed\n"
           "        end try\n"
           "    end repeat\n"
           "    return out\n"
           "end tell")
    out = macapi.osascript(src, timeout=30) or ""
    urls = [u.strip() for u in out.splitlines()]
    return list(dict.fromkeys(u for u in urls if "://" in u and u != "missing value"
                              and not u.startswith(("favorites://", "chrome://newtab"))))


def _mac_doc_path(doc: str) -> str | None:
    if doc.startswith("file://"):
        p = unquote(doc[7:])
        if p.startswith("localhost/"):
            p = p[9:]
        return p if os.path.exists(p) else None
    return None


def _snapshot_mac() -> list[dict]:
    import shlex

    from . import macapi
    text = macapi.osascript(_MAC_PROCS_SCRIPT, timeout=60)
    if text is None:
        return []
    apps, wins = parse_mac_procs(text)
    out: list[dict] = []
    for name, path in apps:
        if name in MAC_SKIP:
            continue
        titles = [t for a, t, _ in wins if a == name and t]
        if name in MAC_TAB_EXPR:
            urls = _mac_tab_urls(name)
            for u in urls:
                out.append({"kind": "url", "app": name, "title": u,
                            "value": u, "suggested": True})
            if urls:
                continue
        if name in MAC_TAB_EXPR or name in MAC_TITLE_BROWSERS:
            for t in titles:                 # title hint → history lookup
                out.append({"kind": "url", "app": name, "title": t,
                            "value": _clean_browser_title(t), "suggested": False})
            continue
        docs = [p for a, _, d in wins if a == name for p in [_mac_doc_path(d)] if p]
        for p in dict.fromkeys(docs):
            out.append({"kind": "file", "app": name, "title": os.path.basename(p),
                        "value": p, "suggested": True})
        if not docs:
            out.append({"kind": "app", "app": f"open -a {shlex.quote(path or name)}",
                        "title": titles[0] if titles else name,
                        "value": titles[0] if titles else name, "suggested": False})
    return out


def _fill_browser_urls(rows: list[dict]) -> None:
    """Turn browser tab-title hints into real URLs by looking them up in the
    browsers' history (see browsers.resolve_titles). A tab we resolve becomes a
    pre-checked, ready-to-save link; unresolved ones stay editable hints."""
    hints = [v for r in rows if r["kind"] == "url"
             for v in r.get("_variants") or [r["value"]]]
    if not hints:
        return
    try:
        from .browsers import resolve_titles
        urls = resolve_titles(hints)
    except Exception:                       # noqa: BLE001 - best effort
        urls = {}
    for r in rows:
        variants = r.pop("_variants", None) or [r["value"]]
        if r["kind"] != "url":
            continue
        hit = next((urls[v] for v in variants if v in urls), None)
        if hit:
            r["value"] = hit
            r["suggested"] = True           # it's a real URL now — offer to keep it
