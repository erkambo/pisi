"""Report a bug or get in touch: links to the right GitHub form (or an
email), with the details a bug report needs filled in for you.

The details are the version and the kind of computer: no names, no paths,
no window titles. They go nowhere unless you paste or send them.
"""
from __future__ import annotations

import os
import platform
import sys
from urllib.parse import quote, urlencode

from PyQt6.QtCore import QT_VERSION_STR, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from . import __version__

REPO = "https://github.com/erkambo/pisi"
EMAIL = "boyaciogluerkam@gmail.com"
SECURITY_URL = f"{REPO}/security/advisories/new"


def os_choice() -> str:
    """This computer, as the bug form's "Your computer" list names it."""
    if sys.platform == "win32":
        return "Windows 10/11"
    if sys.platform == "darwin":
        return "macOS (Apple Silicon)" if platform.machine() == "arm64" else "macOS (Intel)"
    if sys.platform.startswith("linux"):
        return "Linux"
    return "Other"


def details() -> str:
    """What a bug report needs to know about this copy of PISI."""
    lines = [f"PISI {__version__}",
             f"{platform.system()} {platform.release()} ({platform.machine()})",
             f"Qt {QT_VERSION_STR}, Python {platform.python_version()}"]
    if sys.platform.startswith("linux"):
        session = os.environ.get("XDG_SESSION_TYPE", "?")
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "?")
        lines.append(f"Desktop: {desktop} ({session})")
    return "\n".join(lines)


def bug_url() -> str:
    q = {"template": "bug_report.yml", "version": __version__, "os": os_choice()}
    return f"{REPO}/issues/new?{urlencode(q)}"


def idea_url() -> str:
    return f"{REPO}/issues/new?{urlencode({'template': 'idea.yml'})}"


def mail_url() -> str:
    body = f"\n\n\n({details()})"
    return f"mailto:{EMAIL}?subject={quote(f'PISI {__version__}')}&body={quote(body)}"


class FeedbackDialog(QDialog):
    def __init__(self, parent=None, open_url=None, clipboard=None):
        super().__init__(parent)
        self._open = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self._clip = clipboard or (lambda text: QGuiApplication.clipboard().setText(text))
        self.setWindowTitle("Report a bug or get in touch")
        lay = QVBoxLayout(self)
        intro = QLabel("Something not working, or an idea for the cat? I'd love to hear it.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.bug = QPushButton("\U0001F41E  Report a bug")
        self.bug.setToolTip("Opens the bug form on GitHub, with your PISI version filled in. "
                            "Your computer's details are copied, ready to paste.")
        self.bug.clicked.connect(self.report_bug)
        self.idea = QPushButton("\U0001F4A1  Suggest an idea")
        self.idea.clicked.connect(lambda: self._open(idea_url()))
        self.mail = QPushButton("✉  Email the developer")
        self.mail.setToolTip("Copies the address (not everyone has a mail app set up)")
        self.mail.clicked.connect(self.email)
        for b in (self.bug, self.idea, self.mail):
            lay.addWidget(b)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#2f7d4f;font-size:11px")
        self.note.setOpenExternalLinks(True)
        self.note.hide()
        lay.addWidget(self.note)

        info = QLabel(details().replace("\n", "<br>"))
        info.setStyleSheet("color:#888;font-size:11px")
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(info)
        sec = QLabel(f"Found a security problem? <a href='{SECURITY_URL}'>Report it privately</a>, "
                     "not in a public issue.")
        sec.setWordWrap(True)
        sec.setStyleSheet("font-size:11px")
        sec.setOpenExternalLinks(True)
        lay.addWidget(sec)
        self.setMinimumWidth(380)

    def email(self) -> None:
        """Copy the address rather than lean on mailto: plenty of computers
        have no mail app, or a broken one. Opening it is still a click away."""
        self._clip(EMAIL)
        self.note.setText(f"Copied <b>{EMAIL}</b>: paste it into your email. "
                          f"Or <a href='{mail_url()}'>open your mail app</a>.")
        self.note.show()

    def report_bug(self) -> None:
        self._clip(details())
        self._open(bug_url())
        self.note.setText("Your PISI details are copied: paste them into the form. "
                          "If something's really wrong, running PISI with --doctor "
                          "writes a fuller report (doctor.txt) you can attach too.")
        self.note.show()
