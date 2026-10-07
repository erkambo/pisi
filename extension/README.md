# PISI browser extension

Lets your PISI desktop pet play inside the web pages you read, like a cat on
a bookshelf. Lines of text, pictures, buttons and fields are solid: the pet
stands only where it fits (on top of a paragraph, beside a short last line, on
a heading, a picture, a button or the search box), creeps through gaps that are
only crouching-high, leaps over buttons, climbs up the side of a column of text
to get to the top of the screen and naps up there. It rides along as you
scroll and drifts down onto the next ledge when its own scrolls away. Works in
Chrome, Brave, Edge, Vivaldi, Chromium and Firefox (121+).

Now and then it **knocks a word off the page**: it walks to the end of a
line, gives you a long look, and swats the last word over the edge. Once in a
while it digs into a paragraph instead and sends the words flying. Only what
you see changes. **Tidy up this page** (in the toolbar menu or on
right-click) or a reload puts every word back, and **Let PISI make a mess**
switches it off.

It also notices what you're doing on the page:

| You... | The cat... |
| --- | --- |
| select some text | creeps up, pounces on the highlight and swats it |
| play a video | sits beside it and watches; looks round when you pause, stretches at the end |
| play music | bobs its head |
| type for a while | sits on the box and watches |
| read slowly down a long page | curls up and sleeps on it |
| fling the page | hangs on; scroll on and on and it yawns at you |
| reach the end of a long page | stretches |
| zoom | jumps; close its tab and it leaps down just in time |
| open a login page | covers its eyes |
| hover your mouse near it | stalks your pointer and pounces |
| right-click | "Throw PISI a toy here" or "Shine the laser here" |

Pictures get a sniff and code blocks a knead. None of this happens during a
focus block.

It also guards your focus. Tick **Guard my focus here** in the toolbar menu on
a site that tends to eat your time (or right-click the page: **PISI, guard this
site**; or one click on YouTube, Reddit, X and the like in the menu or on the
welcome page that opens when you install it). During a focus block, open it and
the cat gets up from its nap, leaps onto the page and sits in the middle of it
until you leave (the icon says "hey"), and the page softly fades behind it
(**Fade the page while I guard** in the menu). Drag it off and you get five
minutes on that tab; do it again in the same block and you get three, then
one. Breaks leave those sites alone. If PISI can't reach a guarded page (it
isn't running, or web pages are off in its settings) the menu says so.

## Privacy, in one table

| | |
| --- | --- |
| Sites it runs on | Web pages, by default. Never on pages with a password or card-number field, never on mail, banks, payments or password managers (see `exclude_matches` in `manifest.json`). Switch it off per site or pause it from the toolbar button |
| What it sends | The page's shape: rectangles of lines, pictures, buttons and fields, which block each line belongs to and whether that's a paragraph, heading, list item, quote, code, image, video, button, field or search box; plus scroll position, zoom and where the browser window is on screen. And what's happening, as rectangles and yes/no: where your selection is, where a video is and whether it's playing, whether music is playing, which field you're typing in (not what), whether you're at the bottom of the page or offline, that a login page opened |
| What it never sends | The words on the page, the page address, anything you type (a field is only a rectangle). For a site you asked it to guard it adds a yes, not the site, and whether your list has anything on it; the list stays in the browser |
| Where it sends it | Only to the PISI app on this computer, through the browser's native messaging (no network) |
| What it changes | Only when PISI knocks a word off or digs: those words are hidden (their space stays) and a copy of each flies off. Never forms or editable text. Reload, or "Tidy up this page", to undo; "Let PISI make a mess" off to stop. While the cat guards a page, a see-through blur sits over it ("Fade the page while I guard" off to stop) |

## Set up (until it's in the stores)

1. In PISI: **Settings → Web pages → Set up browser bridge** (or
   `python3 -m companion --install-browser-bridge`). This registers the small
   relay program the browser talks to.
2. Load this folder into your browser:
   * **Chrome / Brave / Edge / Vivaldi:** open the extensions page, turn on
     **Developer mode**, click **Load unpacked**, pick this `extension` folder.
   * **Firefox:** open `about:debugging#/runtime/this-firefox`, click **Load
     Temporary Add-on…**, pick `manifest.json`. Firefox forgets it on restart
     until the add-on is signed.
3. Open any article. PISI hops on after a moment; move your mouse over the
   page once so it knows exactly where the page sits on screen.

## How it fits together

```
content.js + lines.js  -- the page's shape: lines per block, headings, pictures,
                          buttons, fields, the window
        | runtime.sendMessage
background.js          -- one native-messaging port to app.pisi.bridge
        | stdin/stdout (4-byte length + JSON)
companion/bridge.py    -- run_host(): the relay the browser starts
        | local socket (QLocalSocket), one JSON object per line
PISI (BridgeServer -> perch.WebSurfaces -> CatSprite)
```

In PISI, `perch.ledges` turns the boxes into the places the pet fits for its
current size (standing or crouched), `perch.hops` / `perch.climbs` into where it
can get to from there without going through anything, and `perch.plan` into
what it feels like doing. `python3 -m companion --web-overlay` draws all of it
over the screen.

PISI sends `{"type": "knock", "x", "y", "dir"}` (the end of the line it
swatted) and `{"type": "dig", "x", "y", "w", "dir"}` (the band under its
feet) in page coordinates; the content script finds those words, hides them
and throws copies (`content.js`, `knock` and `dig`). The page's signals
(`sel`, `video`, `playing`, `music`, `typing`, `end`, `offline`, `mess`)
ride along with each report and become behaviour in `companion/reactions.py`;
right-click menu picks arrive as `{"type": "play", "what", "x", "y"}`.

Coordinates: lines are reported in page (CSS) pixels, together with the
browser's own numbers (window position, screen size, pixel ratio, and a mouse
position over the page once there's been one). PISI places them on the real
screens itself (`perch.browser_map`): browsers can scale each monitor
differently from the desktop and number screens their own way, so this is
worked out per window from which screen's shape matches, that screen's real
pixels and the browser's pixel ratio (which also gives the page zoom).

## Tests

* `node --test extension/test/lines.test.mjs`: geometry (also run by pytest).
* `tests/test_web_perch.py`: manifest permissions, the surface model, the pet's
  leap/ride/fall, a real relay process, the installer.
* `python3 scripts/web_perch_e2e.py`: the whole chain in a headless Brave.

The extension ID `aghakdlloghojgociilficjhadgilnlh` is the Chrome Web Store's;
the `key` in `manifest.json` is the store's public key, so a copy loaded by
hand gets the same ID. The native host only accepts that ID (plus the one
copies loaded by hand had before the store, in `companion/bridge.py`) and
`pisi-pet@pisi.app` in Firefox.
