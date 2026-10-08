"""Browser bridge: lets the PISI browser extension tell the pet where the lines
and pictures are on the page you're reading — the page's shape, never its
words — so it can play on them.

Three pieces, all local to this computer:

    extension (extension/)  --native messaging-->  host  --local socket-->  PISI
                            <--------------------        <-----------------

* The **host** (``--browser-host``) is a tiny process the browser starts
  through its native-messaging channel. It only relays: browser frames
  (4-byte length + JSON) on stdin/stdout <-> one JSON object per line on a
  ``QLocalSocket`` (a Unix socket / Windows named pipe, never a network port).
* :class:`BridgeServer` lives inside PISI and receives ``lines`` / ``gone``
  messages and sends ``dig`` ("the pet is digging here") back.
* :func:`install` registers the host with every browser it finds
  (manifest files on Linux/macOS, registry keys on Windows).

Nothing here sees page text or addresses — only rectangles.
"""
from __future__ import annotations

import getpass
import json
import os
import queue
import struct
import sys
import threading
from pathlib import Path

from .log import get_logger
from .paths import IS_MAC, IS_WINDOWS, app_root, data_dir, private_socket

log = get_logger(__name__)

HOST_NAME = "app.pisi.bridge"
CHROME_EXTENSION_ID = "aghakdlloghojgociilficjhadgilnlh"   # the Chrome Web Store's (= the manifest "key")
OLD_CHROME_IDS = ("hdeebgmdflilpmcmkggmljeoaajaplbe",)      # copies loaded by hand before the store
FIREFOX_EXTENSION_ID = "pisi-pet@pisi.app"
STORE_URL = "https://chromewebstore.google.com/detail/pisi-desktop-pet/" + CHROME_EXTENSION_ID
MAX_MESSAGE = 1 << 20          # browsers cap host->extension messages at 1 MB


def server_name() -> str:
    override = os.environ.get("PISI_BRIDGE_NAME")
    if override:
        return override
    try:
        user = getpass.getuser()
    except Exception:                        # noqa: BLE001
        user = "user"
    return private_socket("pisi-bridge-" + "".join(c for c in user if c.isalnum()))


def _appimage() -> str | None:
    from .autostart import appimage              # noqa: PLC0415 - avoids an import cycle
    return appimage()


def extension_dir() -> Path:
    """The unpacked extension that ships with PISI ("Load unpacked" this).

    From an AppImage, PISI's own files live in a temporary mount with a new
    name every launch, and a browser keeps the folder it loaded: so it gets a
    copy in PISI's data folder that stays put (kept up to date)."""
    src = app_root() / "extension"
    if not _appimage():
        return src
    dst = data_dir() / "browser-extension"
    try:
        _sync_dir(src, dst)
    except OSError:
        log.warning("browser bridge: could not copy the extension", exc_info=True)
    return dst


def _sync_dir(src: Path, dst: Path) -> None:
    """Make ``dst`` an exact copy of ``src`` (only when they differ)."""
    import filecmp                               # noqa: PLC0415
    import shutil                                # noqa: PLC0415
    if dst.is_dir():
        cmp = filecmp.dircmp(src, dst)
        stack, same = [cmp], True
        while stack and same:
            c = stack.pop()
            if c.left_only or c.right_only or c.diff_files or c.funny_files:
                same = False
            stack.extend(c.subdirs.values())
        if same:
            return
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


# ---- native-messaging framing -------------------------------------------------
def read_native(stream) -> dict | None:
    """One browser message, or None at end of stream / on garbage."""
    head = stream.read(4)
    if len(head) < 4:
        return None
    (n,) = struct.unpack("<I", head)
    if n > MAX_MESSAGE * 64:
        return None
    body = stream.read(n)
    if len(body) < n:
        return None
    try:
        msg = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return msg if isinstance(msg, dict) else {}


def write_native(stream, obj: dict) -> None:
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_MESSAGE:
        return
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()


# ---- inside PISI: the server -----------------------------------------------------
try:
    from PyQt6.QtCore import QObject, QTimer, pyqtSignal
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
except ImportError:                          # pragma: no cover - Qt always present
    QObject = object                         # type: ignore[misc,assignment]


def _answering(name: str, wait_ms: int = 300) -> bool:
    """Whether a live server (another PISI) is listening on ``name``."""
    probe = QLocalSocket()
    probe.connectToServer(name)
    up = probe.waitForConnected(wait_ms)
    if up:
        probe.disconnectFromServer()
    return up


class BridgeServer(QObject):
    """Accepts browser hosts; emits each message they relay."""

    message = pyqtSignal(dict)

    def __init__(self, name: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.name = name or server_name()
        self._conns: list = []
        self._bufs: dict = {}
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if _answering(self.name):
            # another PISI has the bridge: never pull it out from under it
            # (removing its socket would leave browsers unable to reach it)
            self.listening = False
            log.warning("browser bridge: another PISI is already listening")
        else:
            QLocalServer.removeServer(self.name)      # clear a stale socket (Unix)
            self.listening = self._server.listen(self.name)
            if not self.listening:
                log.warning("browser bridge: %s", self._server.errorString())
        self._server.newConnection.connect(self._accept)

    @property
    def clients(self) -> int:
        return len(self._conns)

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            c = self._server.nextPendingConnection()
            self._conns.append(c)
            self._bufs[id(c)] = b""
            c.readyRead.connect(lambda c=c: self._read(c))
            c.disconnected.connect(lambda c=c: self._drop(c))
            log.info("browser bridge: a browser connected (%d)", len(self._conns))

    def _drop(self, c) -> None:
        if c in self._conns:
            self._conns.remove(c)
            self._bufs.pop(id(c), None)
            self.message.emit({"type": "host-gone", "conn": id(c)})
            c.deleteLater()

    def _read(self, c) -> None:
        buf = self._bufs.get(id(c), b"") + bytes(c.readAll())
        *lines, rest = buf.split(b"\n")
        if len(rest) > MAX_MESSAGE:               # a peer that never ends a line
            rest = b""
        self._bufs[id(c)] = rest
        for raw in lines:
            if not raw.strip():
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict):
                msg["conn"] = id(c)
                self.message.emit(msg)

    def send(self, obj: dict, conn: int | None = None) -> None:
        """To every connected browser, or just to connection ``conn``."""
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
        for c in list(self._conns):
            if conn is not None and id(c) != conn:
                continue
            c.write(data)
            c.flush()

    def close(self) -> None:
        for c in list(self._conns):
            c.disconnectFromServer()
        self._server.close()


# ---- the host the browser starts ------------------------------------------------
def _std_streams():
    """Binary stdin/stdout, also in a windowed Windows build (no sys.stdout)."""
    if sys.stdin is not None and sys.stdout is not None:
        return sys.stdin.buffer, sys.stdout.buffer
    import msvcrt                                   # noqa: PLC0415 - Windows only
    import ctypes                                   # noqa: PLC0415
    k32 = ctypes.windll.kernel32
    fin = msvcrt.open_osfhandle(k32.GetStdHandle(-10), os.O_RDONLY | os.O_BINARY)
    fout = msvcrt.open_osfhandle(k32.GetStdHandle(-11), os.O_WRONLY | os.O_BINARY)
    return os.fdopen(fin, "rb", buffering=0), os.fdopen(fout, "wb", buffering=0)


def run_host(stdin=None, stdout=None, name: str | None = None) -> int:
    """Relay between the browser (stdin/stdout) and a running PISI."""
    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    if stdin is None or stdout is None:
        stdin, stdout = _std_streams()
    name = name or server_name()
    inbox: queue.Queue = queue.Queue(maxsize=256)
    out_lock = threading.Lock()
    sock = QLocalSocket()
    state = {"connected": None, "buf": b""}

    def to_browser(obj: dict) -> None:
        with out_lock:
            try:
                write_native(stdout, obj)
            except (OSError, ValueError):
                app.quit()

    def status() -> None:
        up = sock.state() == QLocalSocket.LocalSocketState.ConnectedState
        if up != state["connected"]:
            state["connected"] = up
            to_browser({"type": "status", "connected": up})

    def reader() -> None:                       # browser -> inbox (own thread)
        while True:
            msg = read_native(stdin)
            if msg is None:
                inbox.put(None)
                return
            if msg:
                try:
                    inbox.put_nowait(msg)
                except queue.Full:              # PISI busy: drop, lines are re-sent
                    pass

    def pump() -> None:                         # inbox -> PISI (Qt thread)
        while True:
            try:
                msg = inbox.get_nowait()
            except queue.Empty:
                break
            if msg is None:
                app.quit()
                return
            if sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
                sock.write((json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8"))
        status()

    def from_pisi() -> None:                    # PISI -> browser
        state["buf"] += bytes(sock.readAll())
        *lines, state["buf"] = state["buf"].split(b"\n")
        for raw in lines:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict):
                to_browser(msg)

    def reconnect() -> None:
        if sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            sock.connectToServer(name)

    sock.readyRead.connect(from_pisi)
    sock.connected.connect(status)
    sock.disconnected.connect(status)
    threading.Thread(target=reader, daemon=True).start()
    t_pump = QTimer()
    t_pump.timeout.connect(pump)
    t_pump.start(15)
    t_retry = QTimer()
    t_retry.timeout.connect(reconnect)
    t_retry.start(2000)
    reconnect()
    QTimer.singleShot(300, status)
    app.exec()
    return 0


# ---- registering the host with browsers -------------------------------------------
def _home() -> Path:
    return Path(os.path.expanduser("~"))


def chrome_family_dirs() -> list[tuple[str, Path]]:
    """(browser, NativeMessagingHosts dir) for Chrome-family browsers on
    Linux/macOS — only browsers whose profile folder exists."""
    h = _home()
    if IS_MAC:
        base = h / "Library" / "Application Support"
        roots = [("Chrome", base / "Google" / "Chrome"), ("Chromium", base / "Chromium"),
                 ("Brave", base / "BraveSoftware" / "Brave-Browser"),
                 ("Edge", base / "Microsoft Edge"), ("Vivaldi", base / "Vivaldi")]
    else:
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or h / ".config")
        roots = [("Chrome", cfg / "google-chrome"), ("Chromium", cfg / "chromium"),
                 ("Brave", cfg / "BraveSoftware" / "Brave-Browser"),
                 ("Edge", cfg / "microsoft-edge"), ("Vivaldi", cfg / "vivaldi")]
    return [(b, r / "NativeMessagingHosts") for b, r in roots if r.is_dir()]


def firefox_dir() -> Path | None:
    h = _home()
    if IS_MAC:
        root = h / "Library" / "Application Support" / "Mozilla"
    else:
        root = h / ".mozilla"
    return root / "NativeMessagingHosts" if root.is_dir() else None


WINDOWS_KEYS = [
    ("Chrome", r"Software\Google\Chrome\NativeMessagingHosts", "chrome"),
    ("Chromium", r"Software\Chromium\NativeMessagingHosts", "chrome"),
    ("Brave", r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts", "chrome"),
    ("Edge", r"Software\Microsoft\Edge\NativeMessagingHosts", "chrome"),
    ("Firefox", r"Software\Mozilla\NativeMessagingHosts", "firefox"),
]


def host_dir() -> Path:
    d = data_dir() / "browser-host"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_launcher() -> Path:
    """The executable the browser starts (a manifest's "path" takes no args)."""
    ai = _appimage()
    if ai:                                       # the AppImage file, not its temporary insides
        cmd = [ai, "--browser-host"]
        root = Path(ai).parent
    elif getattr(sys, "frozen", False):
        cmd = [sys.executable, "--browser-host"]
        root = Path(sys.executable).parent
    else:
        cmd = [sys.executable, "-m", "companion", "--browser-host"]
        root = app_root()
    if IS_WINDOWS:
        p = host_dir() / "pisi-browser-host.bat"
        args = " ".join(f'"{c}"' if i == 0 else c for i, c in enumerate(cmd))
        p.write_text(f'@echo off\r\ncd /d "{root}"\r\n{args} %*\r\n', encoding="utf-8")
    else:
        p = host_dir() / "pisi-browser-host"
        args = " ".join(_sh_quote(c) for c in cmd)
        p.write_text(f"#!/bin/sh\ncd {_sh_quote(str(root))} || exit 1\nexec {args} \"$@\"\n",
                     encoding="utf-8")
        p.chmod(0o755)
    return p


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def manifest(kind: str, launcher: Path) -> dict:
    m = {"name": HOST_NAME, "description": "PISI desktop pet bridge",
         "path": str(launcher), "type": "stdio"}
    if kind == "firefox":
        m["allowed_extensions"] = [FIREFOX_EXTENSION_ID]
    else:
        m["allowed_origins"] = [f"chrome-extension://{i}/" for i in (CHROME_EXTENSION_ID, *OLD_CHROME_IDS)]
    return m


def install() -> list[str]:
    """Register the host with every browser found. Returns the browsers done."""
    launcher = write_launcher()
    done: list[str] = []
    if IS_WINDOWS:
        import winreg                                # noqa: PLC0415
        for browser, key, kind in WINDOWS_KEYS:
            mpath = host_dir() / f"{HOST_NAME}.{kind}.json"
            mpath.write_text(json.dumps(manifest(kind, launcher), indent=2), encoding="utf-8")
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}") as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(mpath))
                done.append(browser)
            except OSError:
                log.warning("browser bridge: could not register with %s", browser, exc_info=True)
        return done
    targets = [(b, d, "chrome") for b, d in chrome_family_dirs()]
    ff = firefox_dir()
    if ff is not None:
        targets.append(("Firefox", ff, "firefox"))
    for browser, d, kind in targets:
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{HOST_NAME}.json").write_text(json.dumps(manifest(kind, launcher), indent=2),
                                                 encoding="utf-8")
            done.append(browser)
        except OSError:
            log.warning("browser bridge: could not register with %s", browser, exc_info=True)
    return done


def rewrite_manifests(launcher: Path) -> None:
    """Bring the browsers already set up up to date (the extension IDs
    trusted, where the launcher is), without setting up any new ones."""
    if IS_WINDOWS:
        files = [(host_dir() / f"{HOST_NAME}.{kind}.json", kind) for _b, _k, kind in WINDOWS_KEYS]
    else:
        files = [(d / f"{HOST_NAME}.json", "chrome") for _b, d in chrome_family_dirs()]
        ff = firefox_dir()
        if ff is not None:
            files.append((ff / f"{HOST_NAME}.json", "firefox"))
    for path, kind in files:
        if path.exists():
            try:
                path.write_text(json.dumps(manifest(kind, launcher), indent=2), encoding="utf-8")
            except OSError:
                log.warning("browser bridge: could not update %s", path, exc_info=True)


def refresh() -> None:
    """At startup: if the bridge is set up, point it at this copy of PISI
    (an AppImage moved, or a new version installed somewhere else)."""
    if installed():
        launcher = write_launcher()
        rewrite_manifests(launcher)
        extension_dir()


def installed() -> list[str]:
    """Browsers the host is registered with right now."""
    if IS_WINDOWS:
        import winreg                                # noqa: PLC0415
        out = []
        for browser, key, _kind in WINDOWS_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}"):
                    out.append(browser)
            except OSError:
                pass
        return out
    out = [b for b, d in chrome_family_dirs() if (d / f"{HOST_NAME}.json").exists()]
    ff = firefox_dir()
    if ff is not None and (ff / f"{HOST_NAME}.json").exists():
        out.append("Firefox")
    return out


def uninstall() -> list[str]:
    removed: list[str] = []
    if IS_WINDOWS:
        import winreg                                # noqa: PLC0415
        for browser, key, _kind in WINDOWS_KEYS:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}")
                removed.append(browser)
            except OSError:
                pass
        return removed
    dirs = [(b, d) for b, d in chrome_family_dirs()]
    ff = firefox_dir()
    if ff is not None:
        dirs.append(("Firefox", ff))
    for browser, d in dirs:
        f = d / f"{HOST_NAME}.json"
        if f.exists():
            f.unlink()
            removed.append(browser)
    return removed
