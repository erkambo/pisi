# PyInstaller spec for PISI.exe - run via windows\build.ps1 (on Windows).
# One-folder build (not --onefile): starts instantly and trips far fewer
# antivirus heuristics than a self-extracting single exe. No UPX for the same reason.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ASSETS = os.path.join(ROOT, "assets")


a = Analysis(
    [os.path.join(ROOT, "pisi.pyw")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ASSETS, "icon.png"), "assets"),
        (os.path.join(ROOT, "LICENSE"), "."),
        (os.path.join(ASSETS, "icon.ico"), "assets"),
        (os.path.join(ASSETS, "sounds"), os.path.join("assets", "sounds")),
        # the PISI browser extension ("Load unpacked" from Settings -> Web pages)
        (os.path.join(ROOT, "extension"), "extension"),
        # sample pets for Pet Studio (procedural genomes, no art)
        (os.path.join(ROOT, "companion", "creatures", "samples"),
         os.path.join("companion", "creatures", "samples")),
    ]
    + collect_data_files("tzdata"),
    hiddenimports=collect_submodules("companion")
    + collect_submodules("tzdata")
    + ["PyQt6.QtNetwork"],
    excludes=["tkinter", "PIL", "numpy", "pytest",
              "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtWebEngineCore",
              "PyQt6.QtMultimedia", "PyQt6.QtPdf", "PyQt6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PISI",
    icon=os.path.join(ASSETS, "icon.ico"),
    version=os.path.join(SPECPATH, "version_info.txt") if os.path.exists(
        os.path.join(SPECPATH, "version_info.txt")) else None,
    console=False,          # a tray app: no console window
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PISI", upx=False)
