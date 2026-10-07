"""The extension icon's badge: PISI's word on whether the cat can use a page."""
from types import SimpleNamespace

from companion import pagestatus as PS


def _web(active_key=(1, 7), active=True, located=True):
    return SimpleNamespace(_active=active_key, active=active, located=located)


def test_the_state_says_why_the_cat_is_or_isnt_on_the_page():
    assert PS.state(_web(), focusing=False, perch_on=True) == "on"
    assert PS.state(_web(located=False), False, True) == "finding"
    assert PS.state(_web(), focusing=True, perch_on=True) == "napping"   # a focus block
    assert PS.state(_web(active=False), False, True) == "away"
    assert PS.state(_web(), False, perch_on=False) == "off"
    assert PS.state(_web(active_key=None), False, True) is None          # no page yet
    assert set(PS.WHY) == {"on", "finding", "napping", "guarding", "away", "off"}


def test_sent_to_its_tab_on_change_repeated_now_and_then_and_the_old_tab_told():
    t = [0.0]
    sent = []
    web = _web()
    st = PS.PageStatus(web, lambda msg, conn: sent.append((conn, msg["tab"], msg["state"])),
                       clock=lambda: t[0])
    st.update(False, True)
    st.update(False, True)                       # nothing new: quiet
    assert sent == [(1, 7, "on")]
    st.update(True, True)                        # a focus block starts
    assert sent[-1] == (1, 7, "napping")
    t[0] += PS.RESEND_S + 0.1
    st.update(True, True)                        # a reloaded extension catches up
    assert sent[-1] == (1, 7, "napping") and len(sent) == 3
    web._active = (1, 9)                         # another tab has the cat's eye now
    st.update(False, True)
    assert sent[-2:] == [(1, 7, "away"), (1, 9, "on")]


def test_the_bridge_can_send_to_one_browser(qapp):
    from companion.bridge import BridgeServer

    class Conn:
        def __init__(self):
            self.data = b""

        def write(self, d):
            self.data += d

        def flush(self):
            pass
    srv = BridgeServer(name="pisi-test-status-only")
    a, b = Conn(), Conn()
    srv._conns = [a, b]
    srv.send({"type": "page", "tab": 7}, id(b))
    assert a.data == b"" and b'"tab":7' in b.data
    srv.send({"type": "dig"})
    assert b'"dig"' in a.data
    srv._conns = []
    srv.close()


def test_a_second_pisi_never_takes_the_bridge_from_a_running_one(qapp):
    from companion.bridge import BridgeServer
    first = BridgeServer(name="pisi-test-two-of-us")
    assert first.listening
    second = BridgeServer(name="pisi-test-two-of-us")      # e.g. a second copy started
    assert not second.listening
    assert first._server.isListening()                       # the running one keeps it
    second.close()
    first.close()
