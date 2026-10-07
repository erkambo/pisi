// Pure geometry for the PISI page bridge: where are the lines of text, and
// where are they on the *screen*? No DOM access here, so Node can test it
// (tests/test_web_perch.py runs extension/test/lines.test.mjs).
"use strict";

const PisiLines = (() => {
  // Lines narrower or shorter than this aren't worth standing on.
  const MIN_W = 48, MIN_H = 8, MAX_H = 120;

  /** Merge per-node line fragments ({x, y, w, h} client rects) into whole
   *  visual lines: fragments on the same baseline with a small gap between
   *  them (a link, a bold word) become one line. */
  function mergeRects(rects, gap = 14) {
    const rs = rects
      .filter((r) => r.w > 0 && r.h > 0)
      .map((r) => ({ x: r.x, y: r.y, w: r.w, h: r.h }))
      .sort((a, b) => (a.y + a.h) - (b.y + b.h) || a.x - b.x);
    const lines = [];
    for (const r of rs) {
      const last = lines.length ? lines[lines.length - 1] : null;
      const sameRow = last && Math.abs((last.y + last.h) - (r.y + r.h)) <= 3
        && Math.abs(last.y - r.y) <= Math.max(4, 0.35 * Math.max(last.h, r.h));
      if (sameRow && r.x <= last.x + last.w + gap && r.x + r.w >= last.x - gap) {
        const x0 = Math.min(last.x, r.x), x1 = Math.max(last.x + last.w, r.x + r.w);
        const y0 = Math.min(last.y, r.y), y1 = Math.max(last.y + last.h, r.y + r.h);
        last.x = x0; last.w = x1 - x0; last.y = y0; last.h = y1 - y0;
      } else {
        lines.push({ ...r });
      }
    }
    return lines;
  }

  /** Keep lines a pet can stand on inside a viewport of vw x vh. */
  function usable(lines, vw, vh) {
    return lines.filter((l) => l.w >= MIN_W && l.h >= MIN_H && l.h <= MAX_H
      && l.y >= 0 && l.y < vh && l.x < vw && l.x + l.w > 0)
      .map((l) => {
        const x0 = Math.max(0, l.x), x1 = Math.min(vw, l.x + l.w);
        return { x: x0, y: l.y, w: x1 - x0, h: l.h };
      });
  }

  const ZOOMS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5,
                 1.75, 2, 2.5, 3, 4, 5];

  /** Page zoom from two mouse samples: screen moves zoom x as far as client.
   *  Snapped to the browser's zoom steps; null when the move is too small. */
  function zoomFrom(a, b) {
    const dc = b.clientX - a.clientX, ds = b.screenX - a.screenX;
    if (Math.abs(dc) < 30) return null;
    const z = ds / dc;
    let best = null;
    for (const s of ZOOMS) if (best === null || Math.abs(s - z) < Math.abs(best - z)) best = s;
    return Math.abs(best - z) < 0.06 ? best : null;
  }

  /** Where the page's (0, 0) sits relative to the window's own screenX/Y,
   *  measured exactly from a mouse event: screen = origin + client * zoom. */
  function originFromMouse(ev, zoom, win) {
    return { dx: ev.screenX - ev.clientX * zoom - win.screenX,
             dy: ev.screenY - ev.clientY * zoom - win.screenY };
  }

  /** Best guess before the mouse has moved over the page. All the height
   *  the page doesn't use is toolbars above it (that keeps lines at the right
   *  height, which is what the pet stands on); the width it doesn't use is a
   *  side panel or borders we can't place, so split it. The first mouse move
   *  over the page replaces this with an exact value. Firefox knows exactly. */
  function originGuess(win, zoom) {
    if (typeof win.mozInnerScreenX === "number") {
      return { dx: win.mozInnerScreenX - win.screenX, dy: win.mozInnerScreenY - win.screenY };
    }
    return { dx: Math.max(0, (win.outerWidth - win.innerWidth * zoom) / 2),
             dy: Math.max(0, win.outerHeight - win.innerHeight * zoom) };
  }

  /** Client rect -> screen rect (the units PISI's window uses). */
  function toScreen(l, origin, zoom, win) {
    const ox = win.screenX + origin.dx, oy = win.screenY + origin.dy;
    return [Math.round(ox + l.x * zoom), Math.round(oy + l.y * zoom),
            Math.round(l.w * zoom), Math.round(l.h * zoom)];
  }

  /** Screen point -> client point (inverse of toScreen). */
  function toClient(x, y, origin, zoom, win) {
    return { x: (x - win.screenX - origin.dx) / zoom, y: (y - win.screenY - origin.dy) / zoom };
  }

  /** [start, end) of the word around ``i`` in ``text``, or null. */
  function wordAt(text, i) {
    const isW = (c) => /[\p{L}\p{N}'’-]/u.test(c);
    if (i >= text.length) i = text.length - 1;
    if (i < 0) return null;
    if (!isW(text[i]) && i > 0 && isW(text[i - 1])) i -= 1;
    if (!isW(text[i])) return null;
    let s = i, e = i + 1;
    while (s > 0 && isW(text[s - 1])) s--;
    while (e < text.length && isW(text[e])) e++;
    return e - s >= 2 ? [s, e] : null;
  }

  /** The kind of block a tag starts: what the pet can do with it. */
  function kindOf(tag) {
    tag = String(tag || "").toUpperCase();
    if (/^H[1-6]$/.test(tag)) return "h";
    if (tag === "LI" || tag === "DT" || tag === "DD") return "li";
    if (tag === "PRE" || tag === "CODE") return "code";
    if (tag === "BLOCKQUOTE") return "quote";
    if (tag === "TD" || tag === "TH") return "cell";
    if (tag === "IMG" || tag === "PICTURE" || tag === "SVG" || tag === "CANVAS") return "img";
    if (tag === "VIDEO") return "video";
    if (tag === "BUTTON") return "button";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return "field";
    return "p";
  }

  // Smallest box worth reporting, per kind: pictures are something to nap on,
  // buttons and fields something to hop onto or over.
  const MIN_BOX = { img: [100, 60], video: [100, 60], button: [24, 14], field: [40, 14],
                    search: [60, 14], row: [200, 1] };

  /** The page's shape, no words: text fragments ({x, y, w, h, block}) are
   *  merged into lines per block; media and controls ({x, y, w, h, kind}:
   *  img, video, button, field, search, and table rows: the line along
   *  the top of each) are one box each. Returns {lines: [[x, y, w, h, blockIndex]...], kinds: [...]}
   *  with block indexes renumbered top to bottom. */
  function structure(frags, blockKinds, media, vw, vh) {
    const groups = new Map();
    for (const f of frags) {
      if (!groups.has(f.block)) groups.set(f.block, []);
      groups.get(f.block).push(f);
    }
    const blocks = [];
    for (const [b, fs] of groups) {
      const ls = usable(mergeRects(fs), vw, vh);
      if (ls.length) blocks.push({ kind: blockKinds[b] || "p", lines: ls });
    }
    for (const m of media) {
      const [mw, mh] = MIN_BOX[m.kind] || MIN_BOX.img;
      const tall = m.kind === "img" || m.kind === "video" ? Infinity : MAX_H;
      if (m.w >= mw && m.h >= mh && m.h <= tall && m.y + m.h > 0 && m.y < vh
          && m.x < vw && m.x + m.w > 0) {
        const x0 = Math.max(0, m.x), x1 = Math.min(vw, m.x + m.w);
        blocks.push({ kind: m.kind, lines: [{ x: x0, y: m.y, w: x1 - x0, h: m.h }] });
      }
    }
    blocks.sort((a, b) => a.lines[0].y - b.lines[0].y || a.lines[0].x - b.lines[0].x);
    const lines = [], kinds = [];
    blocks.forEach((bl, i) => {
      kinds.push(bl.kind);
      bl.lines.sort((a, b) => a.y - b.y || a.x - b.x);
      for (const l of bl.lines) lines.push({ ...l, b: i });
    });
    return { lines, kinds };
  }

  /** Does ``url`` match a manifest match pattern like "*://*.example.com/*"? */
  function matchesPattern(url, pattern) {
    let u;
    try { u = new URL(url); } catch (e) { return false; }
    const m = /^(\*|https?):\/\/([^/]+)(\/.*)$/.exec(pattern);
    if (!m) return false;
    const [, scheme, host, path] = m;
    if (scheme !== "*" ? u.protocol !== scheme + ":" : !/^https?:$/.test(u.protocol)) return false;
    const h = u.hostname;
    if (host.startsWith("*.")) {
      const base = host.slice(2);
      if (h !== base && !h.endsWith("." + base)) return false;
    } else if (host !== "*" && h !== host) return false;
    const re = new RegExp("^" + path.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");
    return re.test(u.pathname + u.search);
  }

  /** A site as the popup lists it: "www.youtube.com" -> "youtube.com". */
  function siteOf(host) {
    return String(host || "").toLowerCase().replace(/^www\./, "");
  }

  /** Is ``host`` one of ``sites`` (or a part of one, like m.youtube.com)? */
  function onSite(host, sites) {
    const h = siteOf(host);
    return !!h && (sites || []).some((s) => h === s || h.endsWith("." + s));
  }

  /** Guard ``host`` or stop guarding it: the new list. Stopping also lets go
   *  of a wider entry that covers it (youtube.com for m.youtube.com). */
  function setGuard(sites, host, on) {
    const site = siteOf(host);
    const next = (sites || []).filter((s) => s !== site && !onSite(host, [s]));
    if (on && site) next.push(site);
    return next.sort();
  }

  /** The usual distractions, one click each in the menu and the welcome page. */
  const DISTRACTIONS = [["YouTube", ["youtube.com"]], ["Reddit", ["reddit.com"]],
                        ["X", ["x.com", "twitter.com"]], ["Instagram", ["instagram.com"]],
                        ["TikTok", ["tiktok.com"]], ["Facebook", ["facebook.com"]],
                        ["Netflix", ["netflix.com"]], ["Twitch", ["twitch.tv"]]];

  /** Add or drop a quick pick's sites (all of them: X is x.com and twitter.com). */
  function pickSites(sites, pick, on) {
    const rest = (sites || []).filter((s) => !pick.includes(s));
    return (on ? rest.concat(pick) : rest).sort();
  }

  return { mergeRects, usable, zoomFrom, originFromMouse, originGuess, toScreen,
           toClient, wordAt, kindOf, structure, matchesPattern, siteOf, onSite,
           setGuard, pickSites, DISTRACTIONS, MIN_W };
})();

if (typeof module !== "undefined") module.exports = PisiLines;
