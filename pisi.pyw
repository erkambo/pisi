"""Windows launcher: double-click (or `pythonw pisi.pyw`) to start PISI with no
console window. Also the entry point PyInstaller freezes into PISI.exe.
Any arguments are passed through (e.g. `--doctor`, `--open "Projects"`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from companion.__main__ import main  # noqa: E402

raise SystemExit(main())
