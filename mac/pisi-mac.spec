# PyInstaller spec for PISI.app - run via mac/build.sh (on a Mac).
import os
import re

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ASSETS = os.path.join(ROOT, "assets")
VERSION = re.search(r'__version__ = "([^"]+)"',
                    open(os.path.join(ROOT, "companion", "__init__.py")).read()).group(1)

a = Analysis(
    [os.path.join(ROOT, "pisi.pyw")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ASSETS, "icon.png"), "assets"),
        (os.path.join(ROOT, "LICENSE"), "."),
        (os.path.join(ASSETS, "sounds"), os.path.join("assets", "sounds")),
        # the PISI browser extension ("Load unpacked" from Settings -> Web pages)
        (os.path.join(ROOT, "extension"), "extension"),
        # sample pets for Pet Studio (procedural genomes, no art)
        (os.path.join(ROOT, "companion", "creatures", "samples"),
         os.path.join("companion", "creatures", "samples")),
    ],
    hiddenimports=collect_submodules("companion")
    + ["PyQt6.QtNetwork"],
    excludes=["tkinter", "PIL", "numpy", "pytest",
              "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtWebEngineCore",
              "PyQt6.QtMultimedia", "PyQt6.QtPdf", "PyQt6.Qt3DCore"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PISI",
          console=False, upx=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="PISI", upx=False)
app = BUNDLE(
    coll,
    name="PISI.app",
    icon=os.path.join(ASSETS, "icon.icns"),
    bundle_identifier="com.erkambo.pisi",
    version=VERSION,
    info_plist={
        "CFBundleName": "PISI",
        "CFBundleDisplayName": "PISI",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,                 # menu-bar app: no Dock icon
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription":
            "PISI reads your open browser tabs and windows when you use "
            "“From open windows”, so it can save them to a habit's setup.",
        "NSHumanReadableCopyright": "PISI by Erkam Boyacioglu. MIT licence.",
    },
)
