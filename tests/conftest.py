"""Shared test setup. Isolates each test's data dir so tests never touch your
real ~/.local/share/desktop-companion data, and gives GUI tests a headless Qt."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt tests must run headless in CI / over SSH. Set before any QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    yield


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (Qt allows only one)."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# An exception in a Qt callback (a timer, a signal) makes PyQt abort the whole
# run with no traceback (pytest's capture is lost). With an excepthook set,
# PyQt calls it instead: record it, and fail the test it happened in.
_QT_ERRORS: list[str] = []


def _qt_excepthook(etype, value, tb):
    import traceback
    _QT_ERRORS.append("".join(traceback.format_exception(etype, value, tb)))
    sys.__stderr__.write("\n[exception in a Qt callback]\n" + _QT_ERRORS[-1])


sys.excepthook = _qt_excepthook


@pytest.fixture(autouse=True)
def no_bake_left_running():
    """A test that starts a background bake (Pet Studio does) must not leave
    it running: Qt aborts the whole run if the thread object is destroyed
    mid-bake (it did, on CI's slower machines, tests later)."""
    yield
    from PyQt6.QtWidgets import QApplication
    from companion.creatures import qt as cq
    app = QApplication.instance()
    if app is not None:
        app.processEvents()             # (a timer due now may start one)
    assert cq.wait_all(20000), "a background bake didn't finish"
    if _QT_ERRORS:
        errs = "\n".join(_QT_ERRORS)
        _QT_ERRORS.clear()
        pytest.fail("an exception was raised in a Qt callback (timer/signal), "
                    "during or after this test:\n" + errs)
