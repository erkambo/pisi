# PyInstaller spec for PISI on Linux - run via linux/build-appimage.sh.
# One folder (the AppImage wraps it): starts fast, no self-extracting step.
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
        (os.path.join(ASSETS, "sounds"), os.path.join("assets", "sounds")),
        # the PISI browser extension ("Load unpacked" from Settings -> Web pages)
        (os.path.join(ROOT, "extension"), "extension"),
        # the Cinnamon / GNOME panel extensions (installed on first run)
        (os.path.join(ROOT, "extensions"), "extensions"),
        # sample pets for Pet Studio (procedural genomes, no art)
        (os.path.join(ROOT, "companion", "creatures", "samples"),
         os.path.join("companion", "creatures", "samples")),
    ]
    + collect_data_files("tzdata"),
    hiddenimports=collect_submodules("companion")
    + collect_submodules("tzdata")
    + ["PyQt6.QtNetwork", "PyQt6.QtDBus"],
    excludes=["tkinter", "PIL", "numpy", "pytest",
              "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtWebEngineCore",
              "PyQt6.QtMultimedia", "PyQt6.QtPdf", "PyQt6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PISI", console=False,
          upx=False, strip=False)
coll = COLLECT(exe, a.binaries, a.datas, name="PISI", upx=False)
