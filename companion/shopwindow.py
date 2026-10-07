"""The shop window: everything PISI can have, drawn for *your* cat, with
your cat using it.

Each card shows the thing with the cat in it (it comes alive when you
point at it), what it's called, what it costs, and one button that says
what you can do: buy it (two clicks, so a stray click never spends
anything), put it in the corner, or that it's already there. Things you
can't afford yet show how many focus blocks away they are.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from . import shop
from .home import pixmap
from .things import catalog
from .things.kinds import KINDS

ACCENT = "#e8943a"
ACCENT_DARK = "#d9822b"
SURE = "#c8551f"
GREEN = "#3a9d5d"
TILE = QColor(246, 239, 228)          # the preview's backdrop: a warm floor, any theme
TILE_FLOOR = QColor(232, 221, 204)
TILE_LINE = QColor(214, 200, 178)
CONFIRM_S = 3.0                       # "Sure?" waits this long for the second click
COLS = 3
STILL = {"eat": 0.5, "pickup": 0.55}   # one-shots that start from a sit: show them mid-way

QSS = f"""
QFrame#card {{ background: palette(base); border: 2px solid palette(midlight);
              border-radius: 12px; }}
QFrame#card[placed="true"] {{ border: 2px solid {GREEN}; }}
QLabel#name {{ font-size: 13px; font-weight: 600; }}
QLabel#blurb {{ color: palette(placeholder-text); font-size: 11px; }}
QLabel#price {{ font-size: 12px; font-weight: 600; }}
QLabel#done {{ color: {GREEN}; font-weight: 600; font-size: 12px; }}
QLabel#arriving {{ color: {ACCENT_DARK}; font-weight: 600; font-size: 12px; }}
QLabel#togo {{ color: palette(placeholder-text); font-size: 11px; }}
QLabel#section {{ font-size: 15px; font-weight: 600; padding-top: 6px; }}
QLabel#count {{ color: palette(placeholder-text); font-size: 11px; padding-top: 9px; }}
QLabel#title {{ font-size: 20px; font-weight: 700; }}
QLabel#subtitle {{ color: palette(placeholder-text); font-size: 12px; }}
QLabel#pill {{ background: rgba(232, 148, 58, 0.16); border-radius: 15px;
              padding: 5px 14px; font-size: 17px; font-weight: 700; }}
QLabel#goal {{ font-size: 12px; padding: 2px 0 4px 0; }}
QPushButton#buy {{ background: {ACCENT}; color: white; border: none; border-radius: 8px;
                  padding: 6px 14px; font-weight: 600; }}
QPushButton#buy:hover {{ background: {ACCENT_DARK}; }}
QPushButton#buy[sure="true"] {{ background: {SURE}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid palette(mid); border-radius: 8px;
                    padding: 5px 12px; }}
QPushButton#ghost:hover {{ border-color: {ACCENT}; }}
QPushButton#chip {{ background: palette(base); border: 1px solid palette(midlight);
                   border-radius: 13px; padding: 4px 12px; font-size: 12px; }}
QPushButton#chip:hover {{ border-color: {ACCENT}; }}
QPushButton#link {{ background: transparent; border: none; color: palette(placeholder-text);
                   font-size: 11px; padding: 2px 4px; }}
QPushButton#link:hover {{ color: palette(text); text-decoration: underline; }}
"""


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


class Preview(QWidget):
    """The thing for this cat, with the cat using it, on a warm floor tile.
    Still until you point at it, then the cat moves."""
    W, H = 216, 132

    def __init__(self, sheet, item, rendered, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.sheet, self.item, self.r = sheet, item, rendered
        self.state = "carrysit" if item.kind == "toy" else rendered.cat_state
        if self.state not in sheet.anims:
            self.state = sheet.resolve("sit") or next(iter(sheet.anims))
        self.n = max(1, len(sheet.frames(self.state, 1)))
        self.fps = sheet.fps_for(self.state)
        self._imgs: dict[int, QImage] = {}
        self._t0 = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._back = pixmap(rendered.back, rendered.w, rendered.h, 1)
        self._front = pixmap(rendered.front, rendered.w, rendered.h, 1) if rendered.front else None

    def enterEvent(self, _e) -> None:
        self._t0 = time.monotonic()
        self._timer.start(int(1000 / max(1.0, self.fps)))

    def leaveEvent(self, _e) -> None:
        self._timer.stop()
        self.update()

    def _frame(self) -> int:
        if not self._timer.isActive():
            return self._still()
        return int((time.monotonic() - self._t0) * self.fps) % self.n

    def _still(self) -> int:
        return int(self.n * STILL.get(self.state, 0.0)) % self.n

    def _scene(self, i: int) -> QImage:
        """The scene at 1x: the thing, the cat in it (or carrying it)."""
        img = self._imgs.get(i)
        if img is not None:
            return img
        r, sh = self.r, self.sheet
        cat = sh.frames(self.state, 1)[i % self.n].toImage()
        fw, fh = cat.width(), cat.height()
        if self.item.kind == "toy":
            from .things.kinds.toy import held_at
            an = sh.anchor(self.state, i, 1)
            mouth = an.get("mouth") if an else None
            img = QImage(fw, fh, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.drawImage(0, 0, cat)
            if mouth:
                tx, ty = held_at(r, mouth, 1)
                p.drawPixmap(tx, ty, self._back)
            p.end()
            img = img.copy(self._tight(img))
        else:
            cx, cy = r.cat_at_facing(1, fw)
            x0, y0 = min(0, cx), min(0, cy)
            x1, y1 = max(r.w, cx + fw), max(r.h, cy + fh)
            img = QImage(x1 - x0, y1 - y0, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.drawPixmap(-x0, -y0, self._back)
            p.drawImage(cx - x0, cy - y0, cat)
            if self._front is not None:
                p.drawPixmap(-x0, -y0, self._front)
            p.end()
            img = img.copy(self._tight(img))
        self._imgs[i] = img
        return img

    @staticmethod
    def _tight(img: QImage) -> QRect:
        w, h = img.width(), img.height()
        xs, ys = [], []
        for y in range(h):
            for x in range(w):
                if img.pixelColor(x, y).alpha() > 8:
                    xs.append(x)
                    ys.append(y)
        return QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) if xs else img.rect()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.W - 1, self.H - 1, 9, 9)
        p.fillPath(path, TILE)
        p.setClipPath(path)
        floor = self.H - 22
        p.fillRect(0, floor, self.W, self.H - floor, TILE_FLOOR)
        p.fillRect(0, floor, self.W, 1, TILE_LINE)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        img = self._scene(self._frame())
        first = self._scene(self._still())             # size the zoom on the still frame
        z = max(1, min(4, (self.W - 24) // max(1, first.width()), (floor - 8) // max(1, first.height())))
        w, h = img.width() * z, img.height() * z
        x = (self.W - w) // 2
        y = floor + 2 * z - h if self.item.kind != "toy" else floor - h + z
        p.drawImage(QRect(x, y, w, h), img)
        p.end()


class Card(QFrame):
    """One thing in the shop."""

    def __init__(self, win: ShopWindow, item, rendered) -> None:
        super().__init__()
        self.win, self.item = win, item
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        lay.addWidget(Preview(win.sheet, item, rendered), 0, Qt.AlignmentFlag.AlignHCenter)
        name = QLabel(item.name)
        name.setObjectName("name")
        lay.addWidget(name)
        blurb = QLabel(item.blurb or " ")
        blurb.setObjectName("blurb")
        blurb.setWordWrap(True)
        blurb.setFixedWidth(Preview.W)
        blurb.setFixedHeight(blurb.fontMetrics().lineSpacing() * 2 + 2)   # two lines, every card
        blurb.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(blurb)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.price = QLabel()
        self.price.setObjectName("price")
        self.status = QLabel()
        self.status.setMinimumHeight(30)                # as tall as a button: rows line up
        self.button = QPushButton()
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._clicked)
        self.link = QPushButton("Put away")
        self.link.setObjectName("link")
        self.link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.link.clicked.connect(lambda: self.win.put_away(self.item))
        row.addWidget(self.price)
        row.addWidget(self.status)
        row.addStretch(1)
        row.addWidget(self.link)
        row.addWidget(self.button)
        lay.addLayout(row)
        self._sure_until = 0.0
        self._sure_timer = QTimer(self)
        self._sure_timer.setSingleShot(True)
        self._sure_timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        st, it, treat = self.win.store, self.item, self.win.treat
        owned = shop.owns(st, it.id)
        placed = owned and it.kind != "toy" and shop.is_placed(st, it)
        arriving = it.id in self.win.arriving
        sure = time.monotonic() < self._sure_until
        self.setProperty("placed", "true" if placed and not arriving else "false")
        _repolish(self)
        self.price.setVisible(not owned)
        self.price.setText(f"{treat} {it.price}")
        self.link.setVisible(placed and it.kind in shop.OPTIONAL and not arriving)
        self.status.setVisible(False)
        self.button.setVisible(True)
        self.button.setEnabled(True)
        self.button.setProperty("sure", "false")
        if arriving:
            self._show_status("📦  On its way", "arriving")
        elif placed:
            self._show_status("In the corner ✓", "done")
        elif owned and it.kind == "toy":
            self._show_status("In the toy basket ✓", "done")
        elif owned:
            self.button.setObjectName("ghost")
            self.button.setText("Put in the corner")
        elif shop.can_afford(st, it):
            self.button.setObjectName("buy")
            self.button.setText(f"Sure? {treat} {it.price}" if sure else "Buy")
            self.button.setProperty("sure", "true" if sure else "false")
        else:
            n = shop.short_by(st, it)
            self._show_status(f"{n} more block{'s' if n != 1 else ''}", "togo")
        _repolish(self.button)

    def _show_status(self, text: str, kind: str) -> None:
        self.button.setVisible(False)
        self.status.setObjectName(kind)
        self.status.setText(text)
        self.status.setVisible(True)
        _repolish(self.status)

    def _clicked(self) -> None:
        st, it = self.win.store, self.item
        if shop.owns(st, it.id):
            self.win.put_in_corner(it)
            return
        if time.monotonic() < self._sure_until:        # the second click: buy it
            self._sure_until = 0.0
            self.win.buy(it)
            return
        self._sure_until = time.monotonic() + CONFIRM_S
        self._sure_timer.start(int(CONFIRM_S * 1000))
        self.refresh()


class ShopWindow(QDialog):
    """``on_buy(item) -> bool`` pays and sends the parcel; ``on_place(kind,
    item_id | None)`` changes the corner."""

    def __init__(self, store, sheet, fit, treat: str, on_buy, on_place, parent=None) -> None:
        super().__init__(parent)
        self.store, self.sheet, self.fit, self.treat = store, sheet, fit, treat
        self.on_buy, self.on_place = on_buy, on_place
        self.arriving: set[str] = set()
        self.setWindowTitle("PISI's shop")
        self.setStyleSheet(QSS)
        card_w = Preview.W + 2 * 10 + 4
        self.setMinimumWidth(card_w * COLS + 12 * (COLS - 1) + 2 * 18 + 28)
        self.resize(QSize(self.minimumWidth(), 760))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("PISI's shop")
        title.setObjectName("title")
        sub = QLabel(f"Every focus block you finish earns a treat {treat}. Spend them on things "
                     "for PISI. It's all made to fit your cat.")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        self.pill = QLabel()
        self.pill.setObjectName("pill")
        self.pill.setToolTip("Treats saved")
        head.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(head)
        self.goal = QLabel()
        self.goal.setObjectName("goal")
        outer.addWidget(self.goal)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for kind in shop.KINDS:
            if catalog.of_kind(kind):
                chip = QPushButton(shop.KIND_TITLES[kind])
                chip.setObjectName("chip")
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.clicked.connect(lambda _=False, k=kind: self.jump_to(k))
                chips.addWidget(chip)
        chips.addStretch(1)
        outer.addLayout(chips)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.body_lay = QVBoxLayout(body)
        self.body_lay.setContentsMargins(0, 0, 6, 0)
        self.body_lay.setSpacing(10)
        self.cards: list[Card] = []
        self.counts: dict[str, QLabel] = {}
        self.sections: dict[str, QLabel] = {}
        self.scroll = scroll
        self._glide = QPropertyAnimation(scroll.verticalScrollBar(), b"value", self)
        self._glide.setDuration(320)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        for kind in shop.KINDS:
            items = catalog.of_kind(kind)
            if not items:
                continue
            row = QHBoxLayout()
            sec = QLabel(shop.KIND_TITLES[kind])
            sec.setObjectName("section")
            self.sections[kind] = sec
            cnt = QLabel()
            cnt.setObjectName("count")
            self.counts[kind] = cnt
            row.addWidget(sec)
            row.addWidget(cnt)
            row.addStretch(1)
            self.body_lay.addLayout(row)
            grid = QGridLayout()
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)
            for k, it in enumerate(sorted(items, key=lambda it: (it.price, it.name))):
                card = Card(self, it, KINDS[kind].render(it.design, fit))
                self.cards.append(card)
                grid.addWidget(card, k // COLS, k % COLS,
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            grid.setColumnStretch(COLS, 1)
            self.body_lay.addLayout(grid)
        self.body_lay.addStretch(1)
        foot = QLabel("No loot boxes, no timers, nothing to buy with money. Treats never run out.")
        foot.setObjectName("subtitle")
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_lay.addWidget(foot)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.refresh()

    # ---- state -------------------------------------------------------------------
    def refresh(self) -> None:
        st = self.store
        n = st.treats()
        self.pill.setText(f"{self.treat} {n}")
        goal = shop.next_goal(st)
        can = [it for it in catalog.ITEMS if not shop.owns(st, it.id) and shop.can_afford(st, it)]
        if can:
            best = max(can, key=lambda it: it.price)
            self.goal.setText(f"You can get the <b>{best.name}</b> now"
                              + (f", or keep saving for the <b>{goal.name}</b>"
                                 f" ({shop.short_by(st, goal)} more)." if goal else "."))
        elif goal:
            k = shop.short_by(st, goal)
            self.goal.setText(f"Next up: the <b>{goal.name}</b>, {k} more focus "
                              f"block{'s' if k != 1 else ''}.")
        else:
            self.goal.setText("PISI has everything. Spoiled cat. 🐾")
        for kind, lab in self.counts.items():
            items = catalog.of_kind(kind)
            lab.setText(f"{sum(shop.owns(st, it.id) for it in items)} of {len(items)}")
        for c in self.cards:
            c.refresh()

    def jump_to(self, kind: str) -> None:
        """Glide down (or up) to that section."""
        sec = self.sections.get(kind)
        if sec is None:
            return
        bar = self.scroll.verticalScrollBar()
        y = sec.mapTo(self.scroll.widget(), QPoint(0, 0)).y() - 4
        self._glide.stop()
        self._glide.setStartValue(bar.value())
        self._glide.setEndValue(max(bar.minimum(), min(bar.maximum(), y)))
        self._glide.start()

    def buy(self, item) -> None:
        if self.on_buy(item):
            self.arriving.add(item.id)
        self.refresh()

    def arrived(self, item_id: str) -> None:
        self.arriving.discard(item_id)
        self.refresh()

    def put_in_corner(self, item) -> None:
        self.on_place(item.kind, item.id)
        self.refresh()

    def put_away(self, item) -> None:
        self.on_place(item.kind, None)
        self.refresh()

    def showEvent(self, e) -> None:
        self.refresh()
        super().showEvent(e)


_ = QPixmap
