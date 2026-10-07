"""Arrange your corner: drag the things into the order you like.

They're shown in a row just as they stand on screen (the screen's corner
marked at its end), each drawn as it is in the corner. Drop one somewhere
else and the corner on screen rearranges at once.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListView,
                             QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

NAMES = {"bed": "Bed", "post": "Scratcher", "bowl": "Bowl", "basket": "Toy basket"}
LABEL_H = 22
MAX_H = 150                   # the tallest thing is drawn about this tall


def _zoom(spots) -> int:
    """One zoom for all of them (same scale, like on screen), crisp pixels."""
    tallest = max((s.r.h for s in spots), default=1)
    return max(1, min(4, MAX_H // tallest))


def _icon(spot, k: int, height: int, font) -> QPixmap:
    """The thing as it stands in the corner (back and front), standing on a
    shared floor line, with its name under it."""
    w = max(spot.r.w * k, 90) + 16
    img = QImage(w, height + LABEL_H, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    x, y = (w - spot.r.w * k) // 2, height - spot.r.h * k
    for data in (spot.r.back, spot.r.front):
        if data is None:
            continue
        art = QImage(data, spot.r.w, spot.r.h, spot.r.w * 4, QImage.Format.Format_RGBA8888)
        p.drawImage(QRect(x, y, spot.r.w * k, spot.r.h * k), art)
    p.setFont(font)
    p.setPen(QColor(120, 120, 120))
    p.drawText(QRect(0, height + 4, w, LABEL_H - 4), int(Qt.AlignmentFlag.AlignHCenter),
               NAMES.get(spot.kind, spot.kind))
    p.end()
    return QPixmap.fromImage(img)


class ArrangeDialog(QDialog):
    """``on_change(order)``: the kinds from the screen corner outwards (None:
    back to the usual order)."""

    def __init__(self, home, side: str, order: list[str], on_change, parent=None) -> None:
        super().__init__(parent)
        self.home, self.side, self.on_change = home, side, on_change
        self.setWindowTitle("Arrange the corner")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        title = QLabel("Arrange the corner")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        lay.addWidget(title)
        hint = QLabel("Drag the things into the order you like. "
                      "The corner on your screen changes as you go.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(6)
        edge = QLabel("screen\ncorner")
        edge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edge.setStyleSheet("color: palette(placeholder-text); font-size: 10px; "
                           "border-left: 3px solid palette(mid); padding: 0 6px;"
                           if side != "right" else
                           "color: palette(placeholder-text); font-size: 10px; "
                           "border-right: 3px solid palette(mid); padding: 0 6px;")
        self.list = QListWidget()
        self.list.setFlow(QListView.Flow.LeftToRight)
        self.list.setWrapping(False)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        spots = list(home.spots.values())
        self._k = _zoom(spots)
        self._h = max((sp.r.h for sp in spots), default=20) * self._k
        self.list.setIconSize(QSize(max((sp.r.w for sp in spots), default=30) * self._k + 16
                                    if spots else 96, self._h + LABEL_H))
        self.list.setSpacing(8)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setFixedHeight(self._h + LABEL_H + 40)
        self.list.setStyleSheet("QListWidget { background: palette(base); border: 1px solid "
                                "palette(midlight); border-radius: 10px; padding: 6px; }"
                                "QListWidget::item { border-radius: 8px; padding: 4px; }"
                                "QListWidget::item:selected { background: rgba(232,148,58,0.18);"
                                " color: palette(text); }")
        self.list.model().rowsMoved.connect(lambda *_: self._changed())
        if side == "right":
            row.addWidget(self.list, 1)
            row.addWidget(edge)
        else:
            row.addWidget(edge)
            row.addWidget(self.list, 1)
        lay.addLayout(row)

        buttons = QHBoxLayout()
        reset = QPushButton("Usual order")
        reset.clicked.connect(self._reset)
        done = QPushButton("Done")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(done)
        lay.addLayout(buttons)
        self._fill(order)
        width = sum(self.list.item(i).sizeHint().width() + 16 for i in range(self.list.count()))
        self.resize(max(440, width + 120), self.sizeHint().height())

    def _fill(self, order: list[str]) -> None:
        """The things left to right as they stand on screen."""
        self.list.clear()
        kinds = [k for k in order if k in self.home.spots]
        if self.side == "right":
            kinds = kinds[::-1]                          # the corner's on the right
        for k in kinds:
            pm = _icon(self.home.spots[k], self._k, self._h, self.font())
            it = QListWidgetItem(QIcon(pm), "")
            it.setToolTip(NAMES.get(k, k))
            it.setData(Qt.ItemDataRole.UserRole, k)
            it.setSizeHint(QSize(pm.width() + 8, pm.height() + 8))
            self.list.addItem(it)

    def order(self) -> list[str]:
        """From the screen corner outwards."""
        kinds = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        return kinds[::-1] if self.side == "right" else kinds

    def _changed(self) -> None:
        self.on_change(self.order())

    def _reset(self) -> None:
        from .things.layout import ORDER
        self.on_change(None)
        self._fill(list(ORDER))
