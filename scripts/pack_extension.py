"""Zip the browser extension for the stores (dev tool).

    python3 scripts/pack_extension.py

Writes dist/pisi-extension-<version>-chrome.zip (Chrome Web Store) and
dist/pisi-extension-<version>-firefox.zip (addons.mozilla.org), each with only
what the extension runs on: no tests, no README. The manifest is cut to fit
each store:

* both drop "key" (the stores give their own; the Chrome Web Store refuses it)
* Chrome drops the Firefox-only parts ("browser_specific_settings",
  "background.scripts")
* Firefox drops "background.service_worker" and "minimum_chrome_version"

The zips come out the same byte for byte from the same files.
"""
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"
OUT = ROOT / "dist"
SKIP = {"test", "README.md"}
STAMP = (2026, 1, 1, 0, 0, 0)          # fixed times: the same files make the same zip


def files() -> list[Path]:
    return sorted(p for p in EXT.rglob("*")
                  if p.is_file() and p.relative_to(EXT).parts[0] not in SKIP
                  and p.name != "manifest.json" and not p.name.startswith("."))


def manifest(store: str) -> dict:
    m = json.loads((EXT / "manifest.json").read_text("utf-8"))
    m.pop("key", None)
    if store == "chrome":
        m.pop("browser_specific_settings", None)
        m["background"].pop("scripts", None)
    else:
        m["background"].pop("service_worker", None)
        m.pop("minimum_chrome_version", None)
    return m


def pack(store: str) -> Path:
    m = manifest(store)
    if len(m["description"]) > 132:                       # the Chrome Web Store's limit
        sys.exit(f"manifest description is {len(m['description'])} characters, the limit is 132")
    OUT.mkdir(exist_ok=True)
    out = OUT / f"pisi-extension-{m['version']}-{store}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def add(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        add("manifest.json", (json.dumps(m, indent=2) + "\n").encode())
        for p in files():
            add(p.relative_to(EXT).as_posix(), p.read_bytes())
    return out


def main() -> None:
    for store in sys.argv[1:] or ("chrome", "firefox"):
        out = pack(store)
        print(f"{out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
