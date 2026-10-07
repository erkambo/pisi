"""Bake PISI's Google OAuth client into a release build.

CI runs this before building the installers, from two repository secrets:

    PISI_GOOGLE_CLIENT_ID      ...apps.googleusercontent.com
    PISI_GOOGLE_CLIENT_SECRET  the client's secret

It writes companion/_google_client.py (git-ignored, never committed), which
companion/gcal.py picks up so friends can connect with one click. Without the
secrets it writes nothing, and that build uses the client ID in Settings, as
a copy run from source does.
"""
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "companion" / "_google_client.py"


def main() -> int:
    cid = os.environ.get("PISI_GOOGLE_CLIENT_ID", "").strip()
    secret = os.environ.get("PISI_GOOGLE_CLIENT_SECRET", "").strip()
    if not (cid and secret):
        print("no Google client secrets set: this build connects with your own client only")
        return 0
    if not cid.endswith(".apps.googleusercontent.com"):
        print("PISI_GOOGLE_CLIENT_ID doesn't look like an OAuth client ID", file=sys.stderr)
        return 1
    OUT.write_text('"""Written by scripts/stage_google_client.py at build time; never in git."""\n'
                   f"CLIENT_ID = {cid!r}\nCLIENT_SECRET = {secret!r}\n", encoding="utf-8")
    print(f"baked in the Google client {cid[:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
