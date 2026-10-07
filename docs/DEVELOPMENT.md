# Developing PISI

PISI is Python 3.10+ and PyQt6, nothing else at runtime. The code is in
`companion/`, tests in `tests/`.

## Run from source

| OS | Set up | Run again |
|---|---|---|
| Linux (Mint, Ubuntu, Debian) | `./install.sh` (PyQt6 from apt, optional `xprintidle`, start at login) | `./run.sh` |
| Windows | `windows\install.bat` (finds or installs Python, makes `.venv`) | `windows\run.bat` |
| macOS | `mac/install.sh` (needs Python 3.10+, e.g. `brew install python@3.12`) | `python3 -m companion` |

Uninstall a source install with `./uninstall.sh [--purge]`
(`windows\uninstall.bat` on Windows). Your data lives outside the source
folder (`companion/paths.py`), so moving or updating the code never wipes it.

Run with your **real** desktop only from a copy you aren't editing: PISI
imports some modules lazily, so switching branches under a running PISI mixes
versions. Scripts and sandboxes must set `XDG_DATA_HOME`, `PISI_BRIDGE_NAME` and
`PISI_INSTANCE_NAME` so they never touch your own data, browser bridge or
running cat.

## Everyday tasks

```bash
make test        # the test suite (headless Qt; never touches your data)
make lint        # ruff (CI runs it and it gates the builds)
make run         # launch PISI
make tail-log    # follow companion.log
```

## Building the apps

| OS | Command | Output |
|---|---|---|
| Windows | `windows\build.bat` | `dist\PISI\PISI.exe`, the zip, and `PISI-Setup-<ver>.exe` (with [Inno Setup 6](https://jrsoftware.org/isdl.php)) |
| macOS | `mac/build.sh` | `dist/PISI.app` and the `.dmg` |
| Linux | `linux/build-appimage.sh` | `dist/PISI-<ver>-x86_64.AppImage` |

One thing is baked in at build time and **never committed**: PISI's Google
OAuth client. `scripts/stage_google_client.py` writes the git-ignored
`companion/_google_client.py` from the `PISI_GOOGLE_CLIENT_ID` and
`PISI_GOOGLE_CLIENT_SECRET` repository secrets. Without it a build uses the
client typed into Settings. See [google-verification.md](google-verification.md).

## CI and releases

`.github/workflows/ci.yml` runs lint, then the tests on Linux, Windows and
macOS, for every pull request and every push to `main`. In the Actions tab,
**Run workflow** with **build** ticked also builds the installers.

To release:

1. Bump `__version__` in `companion/__init__.py` (and `extension/manifest.json`
   if the extension changed) and rewrite `RELEASE_NOTES.md`; add the same
   points to `CHANGELOG.md`.
2. Merge, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. CI builds every installer and publishes a GitHub Release with
   `RELEASE_NOTES.md` as its text, a `SHA256SUMS.txt`, and build provenance.
   Anyone can check a download with `gh attestation verify <file> --repo erkambo/pisi`.

## Where things are

- `app.py` wires everything together and builds the menu.
- `sprite.py`, `bubble.py`, `focus.py`: the cat, its speech bubble, focus.
- `creatures/`: the procedural cat engine ([pets/README.md](pets/README.md)).
- `things/`, `home.py`, `shop.py`, `shopwindow.py`, `unboxing.py`: the corner
  and the shop ([things/README.md](things/README.md)).
- `playtime.py`, `playground.py`: play.
- `perch.py`, `webcalib.py`, `bridge.py`, `pagestatus.py` and `extension/`:
  web pages and the browser extension.
- `panelbridge.py`, `shellext.py`, `extensions/`: the Cinnamon/GNOME panel
  extensions.
- `calendar.py` (iCal), `gcal.py` (Google), `planner.py` (suggestions).
- `store.py` (the JSON save file), `dialogs.py` (the windows).
- Platform glue: `sysinfo.py`, `windows.py`, `actions.py`, `browsers.py`,
  `autostart.py`, `winapi.py` (ctypes, no pywin32), `macapi.py` (ctypes and
  osascript, no PyObjC). Tests fake both, so Windows and Mac logic is tested
  on Linux too.

**CLI:** `--doctor [--quiet]`, `--install`, `--uninstall [--purge]`,
`--install-browser-bridge`, `--pet-studio`, `--open "<setup>"`,
`--web-debug`, `--version`. Starting a second copy calls the running cat over.
