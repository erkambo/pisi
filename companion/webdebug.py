"""Debug overlay: draws what the pet sees on web pages over the whole screen —
the page area (green), everything solid (grey outlines: text, pictures,
buttons, fields), the ledges that fit the pet (blue where it can stand,
yellow where it has to crouch, red where it can only squeeze through) and its feet (red). Click-through. Toggle
with `python3 -m companion --web-overlay`."""
from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget


def _overlay_flags(w: QWidget) -> None:
    """A click-through, always-on-top, translucent overlay."""
    w.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
        | Qt.WindowType.WindowTransparentForInput
        | Qt.WindowType.WindowDoesNotAcceptFocus
    )
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    w.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)



class WebOverlay(QWidget):
    def __init__(self, surfaces, sprite) -> None:
        super().__init__(None)
        _overlay_flags(self)
        self.surfaces = surfaces
        self.sprite = sprite
        self._t = QTimer(self)
        self._t.timeout.connect(self.update)

    def start(self) -> None:
        geo = QRect()
        for s in QApplication.screens():
            geo = geo.united(s.geometry())
        self.setGeometry(geo)
        self.show()
        self._t.start(150)

    def stop(self) -> None:
        self._t.stop()
        self.close()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        off = self.geometry().topLeft()
        view = self.surfaces.view()
        if view:
            p.setPen(QPen(QColor(40, 200, 90), 2))
            p.drawRect(int(view[0] - off.x()), int(view[1] - off.y()), int(view[2]), int(view[3]))
        p.setPen(QPen(QColor(120, 120, 120, 160), 1))
        for b in self.surfaces.boxes():
            p.drawRect(int(b.x0 - off.x()), int(b.y0 - off.y()), int(b.x1 - b.x0), int(b.y1 - b.y0))
        for s in self.sprite._segments():
            p.setPen(QPen(QColor(220, 60, 40) if s.tight else QColor(235, 170, 0) if s.low
                          else QColor(60, 120, 255), 3))
            p.drawLine(int(s.x0 - off.x()), int(s.y - off.y()), int(s.x1 - off.x()), int(s.y - off.y()))
        cx, feet = self.sprite._feet()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(230, 30, 30))
        p.drawEllipse(int(cx - off.x()) - 5, int(feet - off.y()) - 5, 10, 10)
        p.setPen(QColor(230, 30, 30))
        p.drawText(int(cx - off.x()) + 8, int(feet - off.y()) - 8,
                   f"{self.sprite.state}{' perched' if self.sprite._perched else ''}"
                   f"{' ' + self.sprite._mood if self.sprite._mood else ''}")
        p.end()
