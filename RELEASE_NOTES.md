## PISI, your desktop cat

PISI is a little pixel cat that lives on your desktop. It naps beside you while you focus (Pomodoro), plays with you on your breaks, climbs the web pages you read, and slowly fills its corner by the taskbar with things you buy using the treats you earn: 40 of them, from a crinkle ball to a teacup bed. Free, no account, no ads.

**PISI 1.0, the first public release.** Meet PISI's new cat, a chunky tuxedo with white socks (make it any cat you like in Pet Studio; if you already had the black cat, it stays). Plus a browser extension that makes the cat at home on the web:
- **It guards your focus.** Mark a site as distracting in the extension's menu. Open it during a focus block and the cat leaps onto the page, sits in the middle of it and the page softly fades. Drag it off for five minutes; do it again and you get less.
- **It knocks your words off the page.** The cat walks to the end of a line, gives you a long look, and swats the last word over the edge. **Tidy up this page** puts them back.
- **It notices the page.** It pounces on text you select, watches videos with you, bobs to music, naps on a slow read, leaps off a tab you close and covers its eyes on login pages.
- **Right-click on a page** to throw it a toy or shine the laser right there.

Had a friends' build (1.3)? Install this over it: your cat and its things stay.

Each file's checksum is in `SHA256SUMS.txt`, and `gh attestation verify <file> --repo erkambo/pisi` proves it was built from this repo's code.

### Download

| Your computer | File |
|---|---|
| Windows 10 / 11 | `PISI-Setup-….exe` |
| Mac with Apple Silicon (M1 or newer) | `PISI-…-mac-apple-silicon.dmg` |
| Mac with Intel | `PISI-…-mac-intel.dmg` |
| Linux (Mint, Ubuntu, Fedora, Arch…) | `PISI-…-x86_64.AppImage` |

### Installing

**Windows.** Run `PISI-Setup-….exe`. PISI isn't signed with a paid certificate, so Windows may say *"Windows protected your PC"*. Click **More info → Run anyway**. PISI starts at sign-in. Find its paw icon under the **^** by the clock.

**Mac.** Open the `.dmg` and drag **PISI** into **Applications**. The first time, macOS says it can't be opened: go to **System Settings → Privacy & Security** and click **Open Anyway** (older macOS: right-click PISI → **Open** → **Open**). PISI lives in the menu bar.

**Linux.** Save the `.AppImage` somewhere it can stay (e.g. your home folder). Make it runnable: right-click → **Properties → Permissions → Allow executing**, or `chmod +x PISI-*.AppImage`. Then double-click it. On its first run it adds itself to your app menu and to start at sign-in, and on Cinnamon or GNOME it adds a small panel extension so you can click its corner on the taskbar. On Ubuntu 24.04 and newer, if it won't open, run `sudo apt install libfuse2t64` once.

### Using it

Right-click the cat for everything: **Focus**, **Play**, **Shop**, settings. Each focus block you finish earns a treat. For the cat on web pages, add the browser extension from **Settings → Web pages**.

Something not right? Run PISI with `--doctor` and send the `doctor.txt` it writes.

PISI is free and open source (MIT). Its cats are drawn by its own engine, inspired by carysaurus's Black Cat Sprites. Privacy policy: https://erkamboyacioglu.com/pisi/privacy/
