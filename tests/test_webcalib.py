"""The screen check: does ink sit where the browser said the lines are?"""
import pytest

from companion import webcalib
from companion.perch import WebSurfaces


def _font():
    """The same font on every system (the shift a check finds depends on where
    a font puts its ink in the line box; "Sans" is a different font on each
    OS). DejaVu Sans ships with the tests (free licence, see fonts/)."""
    from pathlib import Path
    from PyQt6.QtGui import QFont, QFontDatabase
    fid = QFontDatabase.addApplicationFont(str(Path(__file__).parent / "fonts" / "DejaVuSans.ttf"))
    fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    f = QFont(fams[0] if fams else "Sans")
    f.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
    return f

def test_corrections_need_two_agreeing_checks_and_reset_with_the_basis():
    s = WebSurfaces(lambda: 1.0)
    msg = {"type": "lines", "conn": 1, "tab": 1, "focused": True, "scroll": [0, 0],
           "exact": False, "zoom": 1, "kinds": ["p"], "lines": [[100, 200, 400, 20, 0]]}
    s.feed(msg)
    y0 = s.segments()[0].y
    s.nudge(0, 30)
    assert s.segments()[0].y == y0                 # one check isn't enough
    s.nudge(0, 32)
    assert s.segments()[0].y == y0 + 31            # two that agree: applied
    assert s.to_browser(100, 231) == (100, 200)
    s.feed(msg)
    assert s.segments()[0].y == y0 + 31            # holds while nothing changed
    s.feed({**msg, "exact": True})                 # the page measured itself exactly
    assert s.segments()[0].y == y0


def _page_image(qapp, off_x, off_y, w=1000, h=900):
    """A Qt-rendered 'article': a sidebar, a heading, paragraphs of uneven
    length. Returns (gray bytes, w, h, stride, the boxes the browser would
    report as if the page sat at (0, 0) of the image)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage, QPainter
    img = QImage(w, h, QImage.Format.Format_Grayscale8)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    f = _font()
    f.setPixelSize(16)
    p.setFont(f)
    p.setPen(QColor(20, 20, 20))
    boxes = []

    def text(x, y, wd, s, size=16):
        f.setPixelSize(size)
        p.setFont(f)
        p.drawText(x + off_x, y + off_y, wd, size + 6, Qt.AlignmentFlag.AlignLeft, s)
        boxes.append((x, y, p.fontMetrics().horizontalAdvance(s), size + 6))
    for i, s in enumerate(["Contents", "History", "Biology", "Behaviour", "See also"]):
        text(20, 120 + 30 * i, 150, s)
    text(220, 40, 600, "Domestic cat", size=30)
    y = 100
    import random
    rnd = random.Random(4)
    for para in range(5):
        n = rnd.randint(2, 5)
        for i in range(n):
            words = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do".split()
            s = " ".join(rnd.choice(words) for _ in range(rnd.randint(6, 11) if i == n - 1 else 12))
            text(220, y, 640, s)
            y += 26
        y += 24
    p.end()
    return bytes(img.constBits().asstring(img.sizeInBytes())), w, h, img.bytesPerLine(), boxes


def test_locates_a_whole_page_hidden_toolbar_and_all(qapp):
    """Measured: Brave on X11 said its page started at the window's top; it
    really started 81 px lower, under the tabs and toolbar."""
    gray, w, h, stride, boxes = _page_image(qapp, 0, 81)
    fix = webcalib.locate(gray, w, h, stride, 0, 0, boxes, 200)
    assert fix is not None and fix.dy == pytest.approx(81, abs=3) and abs(fix.dx) <= 4
    gray, w, h, stride, boxes = _page_image(qapp, 46, -30)
    fix = webcalib.locate(gray, w, h, stride, 0, 0, boxes, 200)
    # (within a few px: where a font puts its ink in the line box varies by
    # font, 0-2 px between Noto Sans and DejaVu Sans; 1 of the cat's art pixels)
    assert fix is not None and fix.dy == pytest.approx(-30, abs=3) and fix.dx == pytest.approx(46, abs=3)


def test_locate_says_nothing_about_a_blank_screen(qapp):
    _gray, w, h, stride, boxes = _page_image(qapp, 0, 0)
    assert webcalib.locate(bytes([255]) * (stride * h), w, h, stride, 0, 0, boxes, 200) is None


def _geo_msg(dpr=2.0, inner=(1920, 954), win=(0, 8, 1924, 956), tab=1, lines=None):
    return {"type": "lines", "conn": 1, "tab": tab, "focused": True, "scroll": [0, 0],
            "geo": {"screen": [1920, 1080], "win": list(win), "inner": list(inner), "dpr": dpr},
            "kinds": ["p"], "lines": lines or [[100, 200, 800, 20, 0]]}


def test_a_found_correction_belongs_to_the_window():
    """Zooming the page (110%: pixel ratio 2.2) kept the toolbar where it was;
    the correction used to be thrown away."""
    s = WebSurfaces(screens=lambda: [(0, 0, 1920, 1080, 2.0)])
    s.feed(_geo_msg())
    assert not s.located
    s.place(-5, 76)
    y = s.boxes()[0].y0
    s.feed(_geo_msg(dpr=2.2, inner=(1745, 867)))           # zoomed in
    assert s.located and s.correction == (-5, 76)
    s.feed(_geo_msg(tab=2))                                 # another tab, same window
    assert s.located and s.correction == (-5, 76) and s.boxes()[0].y0 == y
    s.unlocate()                                            # the screen check lost it
    assert not s.located and s.correction == (0, 0)
    s.feed(_geo_msg(tab=3))                                 # a new tab starts afresh too
    assert not s.located


def test_locates_a_page_shifted_sideways_with_other_text_beside_it(qapp):
    """A terminal's text to the left, the page 135 px further right than the
    browser said, and 78 px lower."""
    gray, w, h, stride, boxes = _page_image(qapp, 135, 78, w=1300)
    noisy = bytearray(gray)
    for y in range(0, h, 19):                                # 'terminal' text
        for yy in range(y, min(h, y + 9)):
            for x in range(0, 110):
                if (x // 3) % 2 == 0:
                    noisy[yy * stride + x] = 30
    fix = webcalib.locate(bytes(noisy), w, h, stride, 0, 0, boxes, 200)
    assert fix is not None and fix.dy == pytest.approx(78, abs=2) and fix.dx == pytest.approx(135, abs=4)


def test_lines_show_on_screen_or_not(qapp):
    """While you're in another window: is the page still to be seen? Ink in
    the lines, blank just above them, whatever is beside the column (the
    infobox's dark photos fooled the first try)."""
    gray, w, h, stride, boxes = _page_image(qapp, 0, 0)
    lines = [b for b in boxes if b[2] >= 120][3:9]
    assert webcalib._lines_show(gray, w, h, stride, 0, 0, lines)
    assert not webcalib._lines_show(bytes([30]) * (stride * h), w, h, stride, 0, 0, lines)
    assert not webcalib._lines_show(gray, w, h, stride, 0, 13, lines)    # not where we think


def _references_screen(qapp, off_y=78, w=1920, h=1080):
    """A screen like Brave on X11 showing Wikipedia's references: a dark tab
    strip and toolbar (78 px the browser doesn't report), then two columns of
    dense, evenly spaced reference lines and the contents sidebar. Returns the
    grab and the boxes the extension reports (as if the page started at 0)."""
    import random
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage, QPainter
    img = QImage(w, h, QImage.Format.Format_Grayscale8)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.fillRect(0, 0, w, off_y, QColor(40, 40, 40))                  # the browser's chrome
    f = _font()
    f.setPixelSize(15)
    p.setFont(f)
    p.setPen(QColor(220, 220, 220))
    for i, tab in enumerate(("meta lab1", "uw ece351", "Zoom", "Cat - Wikipedia", "Extensions")):
        p.drawText(40 + i * 240, 8, 200, 20, Qt.AlignmentFlag.AlignLeft, tab)
    p.drawText(380, 48, 400, 20, Qt.AlignmentFlag.AlignLeft, "en.wikipedia.org/wiki/Cat")
    p.setPen(QColor(25, 25, 25))
    rnd = random.Random(7)
    boxes = []

    def line(x, y, width, s):
        p.drawText(x, y + off_y, width, 20, Qt.AlignmentFlag.AlignLeft, s)
        boxes.append((x, y, p.fontMetrics().horizontalAdvance(s), 18))
    words = "Oxford English Dictionary Retrieved October Archived from the original Press".split()
    for i, s in enumerate(["Contents", "(Top)", "Etymology and naming", "Taxonomy", "Evolution",
                           "Characteristics", "Senses", "Behavior", "Notes", "References"]):
        line(320, 30 + i * 28, 200, s)
    for col, x in ((0, 590), (1, 1060)):
        y = 8
        while y < h - off_y - 30:
            n = rnd.randint(2, 4)
            for k in range(n):
                txt = " ".join(rnd.choice(words) for _ in range(rnd.randint(3, 7) if k == n - 1 else 7))
                line(x + (0 if k == 0 else 26), y, 420, (f"{rnd.randint(10, 150)}. " if k == 0 else "") + txt)
                y += 23
    p.end()
    return bytes(img.constBits().asstring(img.sizeInBytes())), w, h, img.bytesPerLine(), boxes


def test_locates_dense_references_under_the_hidden_toolbar(qapp):
    """Regression (seen twice live): on Wikipedia's references the line
    pattern repeats so evenly that wrong places ranked above the right one,
    and the page stayed 78 px too high. Must be found from scratch, and with
    the place remembered from before."""
    # (within a few px: how a font's letters sit in its line box differs a
    # little between this test's drawing and a browser's; the cat's feet
    # can't tell, a toolbar's height they can)
    gray, w, h, stride, boxes = _references_screen(qapp)
    fix = webcalib.locate(gray, w, h, stride, 0, 0, boxes, 200)
    assert fix is not None and fix.dy == pytest.approx(78, abs=4) and abs(fix.dx) <= 4
    fix = webcalib.locate(gray, w, h, stride, 0, 0, boxes, 200, prior=(0, 78))
    assert fix is not None and fix.dy == pytest.approx(78, abs=4)


def test_a_found_place_survives_a_restart(tmp_path):
    """Regression: restarting PISI forgot the 78 px it had found, and the
    page sat under the toolbar until (if ever) it was found again."""
    mem = tmp_path / "web-places.json"
    s = WebSurfaces(screens=lambda: [(0, 0, 1920, 1080, 2.0)], memory=mem)
    s.feed(_geo_msg())
    s.place(0, 78)
    again = WebSurfaces(screens=lambda: [(0, 0, 1920, 1080, 2.0)], memory=mem)   # a restart
    again.feed(_geo_msg())
    assert again.located and again.correction == (0, 78)
    assert again.take_verify_soon()                          # but it's checked soon
    assert again.prior() == (0, 78)


def test_on_x11_the_page_is_placed_from_its_window():
    """Measured: Brave's window 3840x2070 real px at (3072, 0) on a 2x
    monitor; its page 1920x954 (CSS, zoom 1); Brave says the page is at the
    window's top. The page really starts 81 px down (window bottom 1035 -
    954), on any page, text or not."""
    s = WebSurfaces(screens=lambda: [(3072, 0, 1920, 1080, 2.0), (0, 0, 1536, 960, 2.0)])
    s.feed({"type": "lines", "conn": 1, "tab": 1, "focused": True, "scroll": [0, 0],
            "geo": {"screen": [2560, 1440], "win": [0, 8, 1924, 956], "inner": [1920, 954],
                    "dpr": 2.0},
            "kinds": ["p"], "lines": [[100, 200, 800, 20, 0]]})
    fix = s.window_fix([(3072, 0, 3840, 2070), (0, 0, 3072, 1920)])   # + a laptop window
    assert fix is not None and fix[0] == pytest.approx(0) and s.view()[1] + fix[1] == pytest.approx(81)
    # two windows that both fit: can't tell, leave it to the screen check
    assert s.window_fix([(3072, 0, 3840, 2070), (3072, 0, 3840, 2070)]) is None
