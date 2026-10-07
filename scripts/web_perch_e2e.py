"""End-to-end check of the browser bridge in a real (headless) browser.

    python3 -m companion --install-browser-bridge     # once
    python3 scripts/web_perch_e2e.py [--browser PATH] [--show]

Starts a throwaway-profile Chromium-family browser (Brave by default) with the
extension loaded and a local test page open, then checks the whole chain:

    page -> content script -> background -> native host -> PISI's BridgeServer
    BridgeServer "dig" -> host -> background -> page: the words there fly
    off and leave a hole (unless "Let PISI dig" is off); "tidy" puts them back

Needs node (for the DevTools helper). Quit PISI first: this script takes the
bridge's socket for itself and refuses to run while a PISI owns it (or run it
with PISI_BRIDGE_NAME=pisi-e2e to use a socket of its own).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtNetwork import QLocalSocket  # noqa: E402

from companion import bridge  # noqa: E402

PAGE = """<!doctype html><html><body style="font:18px/1.6 serif;margin:40px">
<h1>PISI test page</h1>
<p>The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog.</p>
<p>Second paragraph with <a href="#">a link</a> and <b>bold words</b> on one line.</p>
<ul><li>First item of a list</li><li>Second item of the list</li></ul>
<img alt="" width="320" height="120" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='120'%3E%3Crect width='320' height='120' fill='%23c8742c'/%3E%3C/svg%3E">
<input value="secret-ish words"><textarea>typed words</textarea></body></html>"""
LOGIN = """<!doctype html><html><body style="font:18px/1.6 serif;margin:40px">
<h1>Sign in</h1><p>Lots of text here that would be fun to walk on, but not on this page.</p>
<input type="password"></body></html>"""
DEBUG_PORT = 9334


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default=shutil.which("brave-browser") and "/opt/brave.com/brave/brave"
                    or shutil.which("chromium") or "google-chrome")
    ap.add_argument("--show", action="store_true", help="open a real window, not headless")
    args = ap.parse_args()
    app = QCoreApplication([])

    probe = QLocalSocket()
    probe.connectToServer(bridge.server_name())
    if probe.waitForConnected(300):
        print("A running PISI owns the bridge — quit it first.")
        return 2
    if not bridge.installed():
        print("Run `python3 -m companion --install-browser-bridge` first.")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="pisi-e2e-"))
    site = tmp / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE)
    (site / "login.html").write_text(LOGIN)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_a):
            pass
    handler = functools.partial(Quiet, directory=str(site))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"

    ext = tmp / "ext"
    shutil.copytree(ROOT / "extension", ext, ignore=shutil.ignore_patterns("test"))
    if not args.show:                  # headless pages never have focus
        c = ext / "content.js"
        c.write_text(c.read_text().replace("focused: document.hasFocus()", "focused: true"))

    server = bridge.BridgeServer()
    got: list[dict] = []
    server.message.connect(got.append)
    prof = tmp / "profile"
    cmd = [args.browser, *([] if args.show else ["--headless=new"]), f"--user-data-dir={prof}",
           f"--disable-extensions-except={ext}", f"--load-extension={ext}", "--no-first-run",
           "--window-size=1200,900", f"--remote-debugging-port={DEBUG_PORT}", url]
    browser = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait(secs: float, pred=lambda: False) -> bool:
        end = time.time() + secs
        while time.time() < end and not pred():
            app.processEvents()
            time.sleep(0.02)
        return pred()

    def cdp(target: str, expr: str) -> str:
        r = subprocess.run(["node", str(ROOT / "scripts" / "cdp_eval.mjs"), str(DEBUG_PORT),
                            target, expr], capture_output=True, text=True, timeout=20)
        return r.stdout.strip()

    ok = True
    try:
        if not wait(40, lambda: any(g.get("type") == "lines" for g in got)):
            print("FAIL: no lines reached PISI. Extension state:",
                  cdp("background.js", "JSON.stringify({port: !!port, connected, lastError})"))
            return 1
        page = [g for g in got if g.get("type") == "lines"][-1]
        lines, kinds = page["lines"], page["kinds"]
        shape = [kinds[r[4]] for r in lines]
        print(f"ok   {len(lines)} surfaces reached PISI:", shape)
        want = ["h", "p", "p", "li", "li", "img", "field", "field"]
        print(("ok  " if shape == want else "FAIL"), "page shape", shape, "expected", want)
        ok &= shape == want
        sent = json.dumps(got)
        private = not any(w in sent for w in ("secret-ish", "typed words", "quick brown", "127.0.0.1"))
        print(("ok  " if private else "FAIL"), "fields are boxes only: no typed words, no page text, no address")
        ok &= private
        geo = page.get("geo") or {}
        good = all(k in geo for k in ("screen", "win", "inner", "dpr"))
        print(("ok  " if good else "FAIL"), "browser geometry reported", geo)
        ok &= good
        line = sorted(lines, key=lambda r: r[1])[1]
        dig = {"type": "dig", "x": line[0] + 60, "y": line[1], "w": 60, "dir": 1}

        cdp("background.js", "api.storage.local.set({dig: false}).then(() => 1)")
        wait(0.5)
        server.send(dig)
        wait(1.5)
        off = cdp(url, "document.querySelectorAll('[data-pisi-dug]').length")
        print(("ok  " if off == "0" else "FAIL"), "digging off: nothing changes", off)
        ok &= off == "0"

        cdp("background.js", "api.storage.local.set({dig: true}).then(() => 1)")
        wait(0.5)
        server.send(dig)
        wait(2.0)
        words = cdp(url, "JSON.stringify([...document.querySelectorAll('[data-pisi-dug]')]"
                         ".map(e => e.textContent))")
        print(("ok  " if "quick" in words else "FAIL"), "digging on: the words there fly off", words)
        ok &= "quick" in words
        cdp("background.js", "api.tabs.query({}).then(ts => Promise.all(ts.map(t => "
                             "api.tabs.sendMessage(t.id, {type: 'tidy'}).catch(() => 0)))).then(() => 1)")
        wait(0.5)
        intact = cdp(url, "document.body.innerText.includes("
                          "'The quick brown fox jumps over the lazy dog.')"
                          " && !document.querySelector('[data-pisi-dug]')")
        print(("ok  " if intact == "true" else "FAIL"), "tidied up: page text intact", intact)
        ok &= intact == "true"

        # a page with a password field: PISI steps off and stays off
        got.clear()
        cdp(url, "location.href = 'login.html'; 1")
        wait(4)
        leaked = [g for g in got if g.get("type") == "lines" and g.get("lines")]
        stepped_off = any(g.get("type") == "gone" for g in got)
        good = not leaked and stepped_off
        print(("ok  " if good else "FAIL"), "password page: PISI steps off, nothing reported",
              {"lines": len(leaked), "gone": stepped_off})
        ok &= good
    finally:
        browser.terminate()
        subprocess.run(["pkill", "-f", f"[u]ser-data-dir={prof}"])
        server.close()
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
