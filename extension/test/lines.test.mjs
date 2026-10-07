// node --test extension/test/lines.test.mjs   (run by tests/test_web_perch.py)
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const L = createRequire(import.meta.url)("../lines.js");

test("fragments on one baseline merge into one line", () => {
  const lines = L.mergeRects([
    { x: 10, y: 100, w: 80, h: 18 },          // "Hello "
    { x: 92, y: 101, w: 40, h: 17 },          // "<a>world</a>"
    { x: 10, y: 124, w: 120, h: 18 },         // next line
  ]);
  assert.equal(lines.length, 2);
  assert.deepEqual(lines[0], { x: 10, y: 100, w: 122, h: 18 });
});

test("a far-away fragment on the same row stays separate (columns)", () => {
  const lines = L.mergeRects([{ x: 10, y: 100, w: 80, h: 18 }, { x: 400, y: 100, w: 80, h: 18 }]);
  assert.equal(lines.length, 2);
});

test("usable drops tiny, huge and off-screen lines and clips to the viewport", () => {
  const out = L.usable([
    { x: 0, y: 10, w: 20, h: 16 },            // too narrow
    { x: 0, y: 10, w: 200, h: 4 },            // too thin
    { x: 0, y: -30, w: 200, h: 16 },          // above the viewport
    { x: -50, y: 50, w: 300, h: 16 },         // clipped on the left
  ], 1000, 800);
  assert.deepEqual(out, [{ x: 0, y: 50, w: 250, h: 16 }]);
});

test("zoom is read from two mouse samples and snapped to browser steps", () => {
  const a = { screenX: 100, clientX: 50 }, b = { screenX: 225, clientX: 150 };
  assert.equal(L.zoomFrom(a, b), 1.25);
  assert.equal(L.zoomFrom(a, { screenX: 110, clientX: 60 }), null);   // too small a move
});

test("screen and client coordinates round-trip at any zoom", () => {
  const win = { screenX: 300, screenY: 40 };
  for (const zoom of [1, 1.25, 0.8]) {
    const ev = { screenX: 700, screenY: 500, clientX: 200 / zoom * 1, clientY: 300 };
    ev.clientX = 250; ev.screenX = 300 + 12 + 250 * zoom;
    ev.clientY = 300; ev.screenY = 40 + 90 + 300 * zoom;
    const origin = L.originFromMouse(ev, zoom, win);
    assert.ok(Math.abs(origin.dx - 12) < 1e-9 && Math.abs(origin.dy - 90) < 1e-9);
    const [sx, sy] = L.toScreen({ x: 40, y: 60, w: 100, h: 20 }, origin, zoom, win);
    const back = L.toClient(sx, sy, origin, zoom, win);
    assert.ok(Math.abs(back.x - 40) <= 1 && Math.abs(back.y - 60) <= 1);
  }
});

test("the first guess puts all unused height above the page (Brave's sidebar case)", () => {
  // measured: Brave at 300,200 with a 700x500 window and a 623x325 page
  const o = L.originGuess({ screenX: 300, screenY: 200, outerWidth: 700, outerHeight: 500,
                            innerWidth: 623, innerHeight: 325 }, 1);
  assert.equal(o.dy, 175);
  assert.equal(o.dx, 38.5);
});

test("firefox reports the page origin exactly", () => {
  const o = L.originGuess({ mozInnerScreenX: 310, mozInnerScreenY: 120, screenX: 300, screenY: 40 }, 1);
  assert.deepEqual(o, { dx: 10, dy: 80 });
});

test("wordAt finds whole words, including accents and apostrophes", () => {
  const t = "the café's door, ok";
  assert.deepEqual(L.wordAt(t, 6), [4, 10]);   // café's
  assert.deepEqual(L.wordAt(t, 10), [4, 10]);  // just after the word
  assert.deepEqual(L.wordAt(t, 15), [11, 15]); // caret right after "door"
  assert.equal(L.wordAt(t, 16), null);          // the ", " gap
  assert.equal(L.wordAt("a b", 0), null);       // one letter isn't worth it
});

test("kindOf maps tags to what the pet can do with them", () => {
  assert.equal(L.kindOf("h2"), "h");
  assert.equal(L.kindOf("LI"), "li");
  assert.equal(L.kindOf("blockquote"), "quote");
  assert.equal(L.kindOf("IMG"), "img");
  assert.equal(L.kindOf("DIV"), "p");
});

test("structure keeps blocks apart, numbers them top to bottom, adds media", () => {
  const frags = [
    { x: 40, y: 200, w: 500, h: 20, block: 0 },     // paragraph line 1
    { x: 40, y: 227, w: 300, h: 20, block: 0 },     // paragraph line 2
    { x: 40, y: 120, w: 300, h: 40, block: 1 },     // heading above it
    { x: 300, y: 200, w: 200, h: 20, block: 2 },    // a side column on the same row
  ];
  const media = [{ x: 40, y: 300, w: 400, h: 200, kind: "img" },
                 { x: 40, y: 600, w: 20, h: 20, kind: "img" }];   // an icon: too small
  const { lines, kinds } = L.structure(frags, ["p", "h", "p"], media, 1200, 800);
  assert.deepEqual(kinds, ["h", "p", "p", "img"]);
  assert.deepEqual(lines.map((l) => [l.b, l.y]), [[0, 120], [1, 200], [1, 227], [2, 200], [3, 300]]);
});

test("buttons, fields and search boxes are boxes to hop on; tiny ones aren't", () => {
  assert.equal(L.kindOf("BUTTON"), "button");
  assert.equal(L.kindOf("input"), "field");
  const media = [{ x: 40, y: 50, w: 60, h: 30, kind: "button" },
                 { x: 140, y: 50, w: 300, h: 32, kind: "search" },
                 { x: 500, y: 50, w: 16, h: 16, kind: "button" },        // an icon button: too small
                 { x: 40, y: -100, w: 400, h: 300, kind: "img" }];        // a picture half scrolled away
  const { kinds, lines } = L.structure([], [], media, 1200, 800);
  assert.deepEqual(kinds, ["img", "button", "search"]);
  assert.equal(lines[0].y, -100);           // still solid where it shows
});

test("manifest match patterns: the excluded sites stay excluded", () => {
  assert.ok(L.matchesPattern("https://mail.google.com/mail/u/0/#inbox", "*://mail.google.com/*"));
  assert.ok(L.matchesPattern("https://www.paypal.com/signin", "*://*.paypal.com/*"));
  assert.ok(L.matchesPattern("https://paypal.com/", "*://*.paypal.com/*"));
  assert.ok(!L.matchesPattern("https://notpaypal.com/", "*://*.paypal.com/*"));
  assert.ok(!L.matchesPattern("https://git.uwaterloo.ca/x", "*://*.td.com/*"));
  assert.ok(L.matchesPattern("http://example.org/a?b=1", "*://*/*"));
  assert.ok(!L.matchesPattern("file:///etc/passwd", "*://*/*"));
});

test("sites match their subdomains, not lookalikes", () => {
  const { onSite, siteOf } = L;
  assert.equal(siteOf("www.Reddit.com"), "reddit.com");
  assert.ok(onSite("old.reddit.com", ["reddit.com"]));
  assert.ok(onSite("www.reddit.com", ["reddit.com"]));
  assert.ok(!onSite("notreddit.com", ["reddit.com"]));
  assert.ok(!onSite("", ["reddit.com"]));
});

test("table rows are thin shelves, kept however short", () => {
  const { lines, kinds } = L.structure([], [], [
    { x: 10, y: 100, w: 600, h: 2, kind: "row" },
    { x: 10, y: 160, w: 120, h: 2, kind: "row" },        // too narrow to be a row of a table
  ], 1000, 800);
  assert.deepEqual(kinds, ["row"]);
  assert.equal(lines.length, 1);
  assert.deepEqual([lines[0].x, lines[0].y, lines[0].w, lines[0].h], [10, 100, 600, 2]);
});

test("guarding a site and letting it go, and the one-click picks", () => {
  const { setGuard, pickSites, DISTRACTIONS } = L;
  assert.deepEqual(setGuard(["reddit.com"], "www.youtube.com", true), ["reddit.com", "youtube.com"]);
  assert.deepEqual(setGuard(["youtube.com"], "m.youtube.com", false), []);   // the wider entry goes too
  assert.deepEqual(setGuard([], "", true), []);
  const x = DISTRACTIONS.find(([name]) => name === "X")[1];
  assert.deepEqual(pickSites(["reddit.com"], x, true), ["reddit.com", "twitter.com", "x.com"]);
  assert.deepEqual(pickSites(["reddit.com", "twitter.com", "x.com"], x, false), ["reddit.com"]);
  assert.deepEqual(pickSites(["x.com"], x, true), ["twitter.com", "x.com"]);   // no doubles
});
