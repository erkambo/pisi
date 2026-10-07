"""Tests for the interactive dialogs' logic: WorkspaceEditor's prefill/collect
and the snapshot picker. Headless Qt."""
from PyQt6.QtCore import Qt

from companion.dialogs import WorkspaceEditor, SnapshotDialog
import companion.dialogs as dialogs_mod


def test_workspace_editor_prefills_and_collects(qapp):
    ed = WorkspaceEditor(show_name=False,
                         paths=["/tmp/a.pdf", "/tmp/b.pdf"],
                         urls=["https://x"])
    assert ed.p_list.count() == 2 and ed.u_list.count() == 1
    ed._ok()
    assert ed.paths == ["/tmp/a.pdf", "/tmp/b.pdf"]
    assert ed.urls == ["https://x"]


def test_workspace_editor_empty_by_default(qapp):
    ed = WorkspaceEditor()
    assert ed.p_list.count() == 0 and ed.u_list.count() == 0
    ed._ok()
    assert ed.paths == [] and ed.urls == [] and ed.cmds == []


def test_workspace_editor_prefills_and_collects_commands(qapp):
    ed = WorkspaceEditor(show_name=False, cmds=["code ~/dev/x", "spotify"])
    assert ed.c_list.count() == 2
    ed._ok()
    assert ed.cmds == ["code ~/dev/x", "spotify"]


def test_workspace_editor_items_are_editable(qapp):
    ed = WorkspaceEditor(urls=["a title, not a url"])
    it = ed.u_list.item(0)
    assert it.flags() & Qt.ItemFlag.ItemIsEditable      # double-click to fix
    it.setText("https://example.com")                   # user edits it
    ed._ok()
    assert ed.urls == ["https://example.com"]


# ---- SnapshotDialog: never silently drop a ticked row ------------------
def test_snapshot_routes_every_ticked_item(qapp, monkeypatch):
    monkeypatch.setattr(dialogs_mod.windows, "snapshot", lambda: [
        {"kind": "file", "app": "xpdf", "title": "book.pdf",
         "value": "/tmp/book.pdf", "suggested": True},
        {"kind": "url", "app": "brave", "title": "Gemini",
         "value": "Baglama Learning - Gemini", "suggested": True},
        {"kind": "app", "app": "code", "title": "proj - VS Code",
         "value": "proj - VS Code", "suggested": True},
    ])
    d = SnapshotDialog()
    for cb, *_ in d._rows:
        cb.setChecked(True)
    d._ok()
    assert d.paths == ["/tmp/book.pdf"]                 # real file kept
    assert d.cmds == ["code"]                           # app → launch command
    assert d.urls == ["Baglama Learning - Gemini"]      # tab title kept, not dropped


def test_snapshot_skips_unticked(qapp, monkeypatch):
    monkeypatch.setattr(dialogs_mod.windows, "snapshot", lambda: [
        {"kind": "app", "app": "spotify", "title": "Spotify",
         "value": "Spotify", "suggested": False},
    ])
    d = SnapshotDialog()
    d._ok()                                             # nothing ticked
    assert d.paths == [] and d.urls == [] and d.cmds == []


def test_pet_studio_from_settings_is_not_blocked_by_settings(qapp):
    """Settings is modal: it closes (saving) before Pet Studio opens, or the
    studio's window couldn't be clicked."""
    from companion.dialogs import SettingsDialog
    from companion.store import Store
    opened = []
    d = SettingsDialog(Store(), open_pet_studio=lambda: opened.append(True))
    d.show()
    d._pet_studio()
    assert not d.isVisible() and d.result() == d.DialogCode.Accepted
    qapp.processEvents()
    assert opened == [True]


def test_settings_says_when_guarded_sites_cant_be_guarded(qapp):
    from companion.dialogs import SettingsDialog
    from companion.store import Store
    store = Store()
    up = [True]
    d = SettingsDialog(store, extension_connected=lambda: up[0])
    assert d.guard_warning() == ""                        # nothing guarded: nothing to say
    store.config["guard_sites"] = True
    assert d.guard_warning() == ""                        # guarded and reachable
    up[0] = False
    assert "isn't connected" in d.guard_warning()
    d.web_perch.setChecked(False)
    assert "switched off" in d.guard_warning()
    assert not d.guard_warn.isHidden()


def test_report_a_bug_fills_in_the_form_and_copies_the_details(qapp):
    from urllib.parse import parse_qs, urlparse

    from companion import __version__, feedback
    opened, copied = [], []
    d = feedback.FeedbackDialog(open_url=opened.append, clipboard=copied.append)
    d.bug.click()
    q = parse_qs(urlparse(opened[-1]).query)
    assert opened[-1].startswith(feedback.REPO + "/issues/new")
    assert q["template"] == ["bug_report.yml"] and q["version"] == [__version__]
    assert q["os"][0] in ("Windows 10/11", "macOS (Apple Silicon)", "macOS (Intel)", "Linux", "Other")
    assert copied == [feedback.details()] and not d.note.isHidden()
    d.idea.click()
    assert "template=idea.yml" in opened[-1]
    n = len(opened)
    d.mail.click()                                   # copies the address, opens nothing
    assert copied[-1] == feedback.EMAIL and len(opened) == n
    assert "mailto:" + feedback.EMAIL in d.note.text()
    # the details never carry who you are or where your files are
    home = __import__("os").path.expanduser("~")
    assert home not in feedback.details() and __import__("getpass").getuser() not in feedback.details()
