"""PISI's corner, clickable through the desktop's panel.

Cinnamon and GNOME Shell draw their panels themselves and keep every click
inside them, so the corner's things, standing in the taskbar's strip, can't
be clicked or dragged there. A small shell extension (``extensions/``)
fixes that: it asks PISI where the things are, puts invisible click areas
over them in the shell's own layer, and passes clicks and drags back.

This is PISI's end: a D-Bus service on the session bus.

    name       io.github.pisi.Companion
    path       /io/github/pisi/Companion
    interface  io.github.pisi.Corner
      Hotspots() -> s          JSON: [{"id", "x", "y", "w", "h"}], real screen pixels
      Press(s id, i x, i y)    a button went down on a thing (real pixels)
      Move(i x, i y)           ... the pointer moved while it's down
      Release(i x, i y)        ... and came up: a click, or the end of a drag
      OpenShop()
      Attach(s name)           the extension (bus name ``name``) takes the clicks now:
                               the corner's window lets them through (until
                               Detach, or the extension's name leaves the bus)
      Detach()
      HotspotsChanged(s json)  signal: the things moved, appeared or went
      Version() -> i
"""
from __future__ import annotations

import json

from PyQt6.QtCore import QObject, pyqtClassInfo, pyqtSignal, pyqtSlot

from .log import get_logger

log = get_logger(__name__)

SERVICE = "io.github.pisi.Companion"
PATH = "/io/github/pisi/Companion"
INTERFACE = "io.github.pisi.Corner"
VERSION = 2

INTROSPECTION = f"""
<interface name="{INTERFACE}">
  <method name="Version"><arg direction="out" type="i"/></method>
  <method name="Hotspots"><arg direction="out" type="s"/></method>
  <method name="Press">
    <arg direction="in" type="s" name="id"/>
    <arg direction="in" type="i" name="x"/>
    <arg direction="in" type="i" name="y"/>
  </method>
  <method name="Move">
    <arg direction="in" type="i" name="x"/>
    <arg direction="in" type="i" name="y"/>
  </method>
  <method name="Release">
    <arg direction="in" type="i" name="x"/>
    <arg direction="in" type="i" name="y"/>
  </method>
  <method name="OpenShop"/>
  <method name="Attach"><arg direction="in" type="s" name="name"/></method>
  <method name="Detach"/>
  <signal name="HotspotsChanged"><arg type="s" name="json"/></signal>
</interface>
"""


class Corner(QObject):
    """What the extension can do with the corner (plain Qt, testable
    without a bus): ``home`` is the HomeCorner, ``open_shop`` a callable."""
    hotspots_changed = pyqtSignal(str)

    def __init__(self, home, open_shop) -> None:
        super().__init__()
        self.home = home
        self.open_shop = open_shop
        self._last = None
        self._watcher = None
        home.changed.connect(self._changed)

    def hotspots_json(self) -> str:
        return json.dumps(self.home.hotspots(), separators=(",", ":"))

    def _changed(self) -> None:
        js = self.hotspots_json()
        if js != self._last:
            self._last = js
            self.hotspots_changed.emit(js)

    def attach(self, name: str = "") -> None:
        """An extension takes the clicks: let them through the corner's
        window, until it detaches or its name leaves the bus."""
        self.home.set_click_through(True)
        if name and self._watcher is None:
            try:
                from PyQt6.QtDBus import QDBusConnection, QDBusServiceWatcher
                self._watcher = QDBusServiceWatcher(
                    name, QDBusConnection.sessionBus(),
                    QDBusServiceWatcher.WatchModeFlag.WatchForUnregistration, self)
                self._watcher.serviceUnregistered.connect(lambda _n: self.detach())
            except Exception:  # noqa: BLE001 - without a watcher, Detach still works
                log.warning("panel bridge: can't watch %s", name, exc_info=True)

    def detach(self) -> None:
        """The extension's gone: the corner takes its own clicks again."""
        if self._watcher is not None:
            self._watcher.deleteLater()
            self._watcher = None
        self.home.set_click_through(False)

    def press(self, x: int, y: int) -> None:
        self.home.press(self.home.from_real(x, y))

    def move(self, x: int, y: int) -> None:
        self.home.drag_to(self.home.from_real(x, y))

    def release(self, x: int, y: int) -> None:
        self.home.release(self.home.from_real(x, y))


def _adaptor_class():
    from PyQt6.QtDBus import QDBusAbstractAdaptor

    @pyqtClassInfo("D-Bus Interface", INTERFACE)
    @pyqtClassInfo("D-Bus Introspection", INTROSPECTION)
    class CornerAdaptor(QDBusAbstractAdaptor):
        HotspotsChanged = pyqtSignal(str)

        def __init__(self, parent: Corner) -> None:
            super().__init__(parent)
            self.corner = parent
            parent.hotspots_changed.connect(self.HotspotsChanged)

        @pyqtSlot(result=int)
        def Version(self) -> int:
            return VERSION

        @pyqtSlot(result=str)
        def Hotspots(self) -> str:
            return self.corner.hotspots_json()

        @pyqtSlot(str, int, int)
        def Press(self, _id: str, x: int, y: int) -> None:
            self.corner.press(x, y)

        @pyqtSlot(int, int)
        def Move(self, x: int, y: int) -> None:
            self.corner.move(x, y)

        @pyqtSlot(int, int)
        def Release(self, x: int, y: int) -> None:
            self.corner.release(x, y)

        @pyqtSlot()
        def OpenShop(self) -> None:
            self.corner.open_shop()

        @pyqtSlot(str)
        def Attach(self, name: str) -> None:
            self.corner.attach(name)

        @pyqtSlot()
        def Detach(self) -> None:
            self.corner.detach()

    return CornerAdaptor


def start(home, open_shop) -> Corner | None:
    """Offer the corner on the session bus (Linux only; None if there's no
    bus, or another PISI already has the name)."""
    try:
        from PyQt6.QtDBus import QDBusConnection
    except ImportError:
        return None
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    corner = Corner(home, open_shop)
    corner._adaptor = _adaptor_class()(corner)
    if not bus.registerObject(PATH, corner):
        log.warning("panel bridge: couldn't register %s", PATH)
        return None
    if not bus.registerService(SERVICE):
        log.info("panel bridge: %s is taken (another PISI?)", SERVICE)
        bus.unregisterObject(PATH)
        return None
    log.info("panel bridge: on the session bus as %s", SERVICE)
    return corner
