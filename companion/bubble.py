"""A speech bubble that floats near the cat. Persistent bubbles stay until the
user clicks them (that click is the 'acknowledgement' — nothing is lost if you
were away from the screen)."""
from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

MAX_W = 280
PAD = 12
TAIL = 10


class Bubble(QWidget):
    clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # macOS hides "tool" windows whenever another app is active — keep it up
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._text = ""
        self._font = QFont()
        self._font.setPointSize(10)
        self._tail_down = True  # tail points down (bubble above the cat)
        self._tail_x = 0        # tail tip x (local), tracks the cat when clamped

    def _measure(self, text: str) -> QRect:
        fm = QFontMetrics(self._font)
        inner = MAX_W - 2 * PAD
        r = fm.boundingRect(QRect(0, 0, inner, 1000),
                            int(Qt.TextFlag.TextWordWrap), text)
        return r

    def show_message(self, text: str, anchor: QRect, tail_down: bool = True) -> None:
        """anchor = the cat's window geometry (global coords)."""
        self._text = text
        self._tail_down = tail_down
        r = self._measure(text)
        w = min(MAX_W, r.width() + 2 * PAD)
        h = r.height() + 2 * PAD + TAIL
        self.resize(w, h)

        cx = anchor.center().x()
        x = cx - w // 2
        y = anchor.top() - h + 4 if tail_down else anchor.bottom() - 4
        # keep on-screen; if clamped, the tail still points at the cat.
        # Use the monitor the *cat* is on (anchor), not the one this widget
        # happens to sit on — otherwise the bubble snaps back to the primary
        # screen on multi-monitor setups.
        scr = (QApplication.screenAt(anchor.center())
               or self.screen() or QApplication.primaryScreen())
        screen = scr.availableGeometry() if scr else None
        if screen:
            x = max(screen.left() + 4, min(x, screen.right() - w - 4))
            if y < screen.top() + 4:            # no room above → flip below
                y = anchor.bottom() - 4
                self._tail_down = False
            elif y + h > screen.bottom() - 4 and not tail_down:
                y = anchor.top() - h + 4        # no room below → flip above
                self._tail_down = True
            y = max(screen.top() + 4, min(y, screen.bottom() - h - 4))
        self._tail_x = int(max(14, min(w - 14, cx - x)))
        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.update()

    def reposition(self, anchor: QRect) -> None:
        if self.isVisible() and self._text:
            self.show_message(self._text, anchor, self._tail_down)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        body = QRect(0, TAIL if not self._tail_down else 0, w, h - TAIL)

        path = QPainterPath()
        path.addRoundedRect(float(body.x()), float(body.y()),
                            float(body.width()), float(body.height()), 12, 12)
        # tail — tip tracks the cat (self._tail_x), stays attached to the body
        cx = max(14, min(w - 14, self._tail_x or w // 2))
        if self._tail_down:
            path.moveTo(cx - 9, body.bottom())
            path.lineTo(cx, body.bottom() + TAIL)
            path.lineTo(cx + 9, body.bottom())
        else:
            path.moveTo(cx - 9, body.top())
            path.lineTo(cx, body.top() - TAIL)
            path.lineTo(cx + 9, body.top())

        p.setPen(QPen(QColor(60, 60, 70), 1.5))
        p.setBrush(QColor(255, 253, 245, 245))
        p.drawPath(path)

        p.setFont(self._font)
        p.setPen(QColor(40, 40, 45))
        text_rect = QRect(body.x() + PAD, body.y() + PAD,
                          body.width() - 2 * PAD, body.height() - 2 * PAD)
        flags = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        p.drawText(text_rect, flags, self._text)
        p.end()

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit()
        self.hide()
