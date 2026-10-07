"""Run PISI:            python3 -m companion
Open a habit's setup:  python3 -m companion --open "Projects"
Health check:          python3 -m companion --doctor [--quiet]
Add launchers:         python3 -m companion --install   (start at sign-in + Start menu)
Remove launchers:      python3 -m companion --uninstall [--purge]
Make your pet:         python3 -m companion --pet-studio
Browser bridge:        python3 -m companion --install-browser-bridge [--remove]
Panel extension:       python3 -m companion --install-panel-extension   (Cinnamon / GNOME)
Framework self-test:   python3 -m companion --self-test [--json]

The --open one-shot opens a habit's files/links/apps and exits — bind it to a
keyboard shortcut or a desktop launcher to start a project in one press,
without touching the tray menu (works whether or not PISI is already running).

Only one PISI runs at a time: launching it again just calls the running cat
over to your cursor (handy on Windows, where the tray icon hides in the ^
overflow and people click the Start-menu entry again).
"""
from __future__ import annotations

import getpass
import os
import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .log import get_logger, setup_logging

IS_WINDOWS = sys.platform == "win32"


def _server_name() -> str:
    """The single-instance socket (PISI_INSTANCE_NAME gives a sandbox its own,
    so it never pokes, or clears, the PISI you're running)."""
    if os.environ.get("PISI_INSTANCE_NAME"):
        return os.environ["PISI_INSTANCE_NAME"]
    try:
        user = getpass.getuser()
    except Exception:                        # noqa: BLE001
        user = "user"
    from .paths import private_socket
    return private_socket("pisi-companion-" + "".join(c for c in user if c.isalnum()))


def _poke_running(message: bytes) -> bool:
    """Send `message` to an already-running PISI. True if one answered."""
    try:
        from PyQt6.QtNetwork import QLocalSocket
    except ImportError:
        return False
    sock = QLocalSocket()
    for name in dict.fromkeys((_server_name(), os.path.basename(_server_name()))):
        sock.connectToServer(name)            # (the bare name: a PISI from before 1.0)
        if sock.waitForConnected(400):
            break
    else:
        return False
    sock.write(message)
    sock.flush()
    sock.waitForBytesWritten(1000)
    # wait for the running copy's "ok" before hanging up: on Windows (named
    # pipes) hanging up straight away can drop the message unread
    sock.waitForReadyRead(2000)
    sock.disconnectFromServer()
    return True


def _listen(on_message):
    """Become the single running instance; returns the server (keep a ref)."""
    try:
        from PyQt6.QtNetwork import QLocalServer
    except ImportError:
        return None
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # only this user
    QLocalServer.removeServer(_server_name())      # clear a stale socket (Linux)
    if not server.listen(_server_name()):
        get_logger(__name__).warning("single-instance server: %s", server.errorString())
        return None

    def accept():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            # the message is a few bytes, already sent by the time we get here —
            # read it synchronously rather than juggling readyRead signals
            msg = ""
            if conn.bytesAvailable() or conn.waitForReadyRead(1000):
                msg = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            conn.write(b"ok")                # lets the caller hang up safely
            conn.flush()
            conn.waitForBytesWritten(500)
            conn.disconnectFromServer()
            conn.deleteLater()
            if msg:
                on_message(msg)
    server.newConnection.connect(accept)
    return server


def _out(text: str) -> None:
    if sys.stdout is not None:               # None in a windowed .exe
        print(text)


def _open_setup(name: str) -> int:
    """One-shot: open the named habit's setup, then quit."""
    from . import actions
    from .store import Store
    store = Store()
    h = next((x for x in store.habits if x["name"].lower() == name.strip().lower()),
             None)
    if h is None:
        _out(f"No habit named {name!r}. Habits: "
             + ", ".join(x["name"] for x in store.habits))
        return 2
    ws = store.habit_workspace(h["id"])
    if not ws:
        _out(f"“{h['name']}” has no setup yet. Add one in Manage → 🗂 Setup.")
        return 1
    app = QApplication(sys.argv)             # QDesktopServices needs an app
    actions.open_workspace(ws)
    # give openUrl/openLocalFile a moment to dispatch, then exit
    QTimer.singleShot(800, app.quit)
    app.exec()
    return 0


def _pet_studio(path: str | None) -> int:
    """Standalone Pet Studio; "Use as my pet" also updates a running PISI."""
    from .petstudio import PetStudio
    from .store import Store
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("PISI Pet Studio")
    st = PetStudio(Store())
    st.use_pet.connect(lambda *_: _poke_running(b"reload-pet"))
    st.use_original.connect(lambda: _poke_running(b"reload-pet"))
    if path:
        st.load_path(path)
    st.show()
    return app.exec()


def _uninstall(purge: bool) -> int:
    from . import autostart
    app = QApplication(sys.argv)             # QLocalSocket wants an app object
    if _poke_running(b"quit"):
        QTimer.singleShot(1500, app.quit)    # let it save and exit first
        app.exec()
    done = autostart.uninstall(purge=purge)
    from . import bridge, shellext
    if shellext.uninstall():
        done.append("panel extension")
    if bridge.uninstall():
        done.append("browser bridge")
    _out("Removed: " + (", ".join(done) if done else "nothing to remove"))
    return 0


def prefer_x11(env=None) -> bool:
    """On a Wayland desktop (GNOME and KDE by default), run through
    XWayland: Wayland doesn't let an app place its own windows, and the cat
    and its corner are nothing but windows placed just so. Unless you chose
    a platform yourself (QT_QPA_PLATFORM). True if it switched."""
    import os
    env = os.environ if env is None else env
    if not sys.platform.startswith("linux") or env.get("QT_QPA_PLATFORM"):
        return False
    if env.get("WAYLAND_DISPLAY") and env.get("DISPLAY"):
        env["QT_QPA_PLATFORM"] = "xcb"
        return True
    return False


def main() -> int:
    argv = sys.argv[1:]
    prefer_x11()
    if IS_WINDOWS:
        from . import winapi
        winapi.set_app_id()                  # our icon/name in the taskbar, not python's
    if argv and argv[0] == "--browser-host":
        # started by the browser: stdout is its message channel, so this runs
        # before anything could print to it
        from .bridge import run_host
        return run_host()
    if argv and argv[0] in ("--version", "-V"):
        from . import __version__
        _out(f"PISI {__version__}")
        return 0
    if argv and argv[0] == "--doctor":
        from .doctor import run
        return run(quiet="--quiet" in argv)
    setup_logging()
    if argv and argv[0] == "--open":
        if len(argv) < 2:
            _out('usage: python3 -m companion --open "<habit name>"')
            return 2
        return _open_setup(argv[1])
    if argv and argv[0] == "--install":
        from . import autostart
        ok = autostart.enable()
        lnk = autostart.ensure_start_menu_shortcut() if IS_WINDOWS else None
        _out(f"start at sign-in: {'on' if ok else 'FAILED'}"
             + ("" if lnk is None else f"; Start menu shortcut: {'ok' if lnk else 'FAILED'}"))
        from . import shellext
        if shellext.needed(shellext.desktop()):
            _out("panel extension: " + shellext.install())
        return 0 if ok and lnk is not False else 1
    if argv and argv[0] == "--install-panel-extension":
        from . import shellext
        _out(shellext.install())
        return 0
    if argv and argv[0] == "--uninstall":
        return _uninstall(purge="--purge" in argv)
    if argv and argv[0] == "--self-test":
        from .creatures.selftest import main as selftest
        return selftest(as_json="--json" in argv)
    if argv and argv[0] == "--install-browser-bridge":
        from . import bridge
        if "--remove" in argv:
            done = bridge.uninstall()
            _out("Removed from: " + (", ".join(done) if done else "no browser"))
            return 0
        done = bridge.install()
        _out("Browser bridge set up for: " + (", ".join(done) if done else "no browser found"))
        _out(f"Now load the extension: {bridge.extension_dir()}")
        return 0 if done else 1
    if argv and argv[0] in ("--web-debug", "--web-overlay"):
        app = QApplication(sys.argv)                 # noqa: F841 - QLocalSocket wants one
        ok = _poke_running(argv[0][2:].encode())
        if ok and argv[0] == "--web-debug":
            from .paths import data_dir
            _out(f"wrote {data_dir() / 'web-debug.json'}")
        return 0 if ok else 1
    if argv and argv[0] == "--pet-studio":
        return _pet_studio(argv[1] if len(argv) > 1 else None)

    log = get_logger(__name__)
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # allow Ctrl-C from a terminal
    app = QApplication(sys.argv)
    app.setApplicationName("Desktop Companion")
    app.setApplicationDisplayName("PISI")
    app.setQuitOnLastWindowClosed(False)   # live in the tray, not tied to a window
    if sys.platform == "darwin":
        from . import macapi
        macapi.hide_dock_icon()            # a menu-bar app (PISI.app sets LSUIElement)

    if _poke_running(b"show"):
        log.info("PISI is already running — called it over instead")
        return 0
    log.info("PISI starting")

    from .app import Companion
    companion = Companion(app)

    def on_message(msg: str):
        if msg == "quit":
            app.quit()
        elif msg == "reload-pet":
            companion.reload_pet()
        elif msg == "web-debug":
            companion.web_debug()
        elif msg == "web-overlay":
            companion.toggle_web_overlay()
        else:
            companion.summon()
    _server = _listen(on_message)          # noqa: F841 - keep alive for app lifetime
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
