// Runs on web pages (unless you switched PISI off for the site, paused it, or
// the page asks for a password or card number). Tells PISI the *shape* of the
// visible page (which lines of text belong to the same paragraph, heading,
// list item, quote or code block, and where images and videos are) so the
// pet can play on it, and what's going on there: a video playing, music, a
// selection, typing, the end of the page. Never the words or the address.
//
// Now and then PISI makes a mess: it knocks the last word off a line, or digs
// and sends the words under its paws flying. Only how the page looks changes,
// never forms or editable text; "Tidy up this page" or a reload puts every
// word back.
"use strict";

(() => {
  if (window.__pisiPet) return;            // injected twice (manifest + re-enable)
  window.__pisiPet = true;
  if (window.top !== window) return;       // top page only, not iframes

  const api = globalThis.browser ?? globalThis.chrome;
  const L = PisiLines;
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA", "INPUT", "SELECT",
                        "OPTION", "BUTTON", "SVG", "CANVAS", "IFRAME", "VIDEO"]);
  // pages where you type secrets: PISI steps off and stays off
  const SECRET = 'input[type="password"], input[autocomplete^="cc-"], ' +
                 'input[autocomplete="one-time-code"], input[name*="cardnumber" i]';
  const CONTROLS = 'button, [role="button"], [role="searchbox"], input:not([type="hidden"])' +
                   ':not([type="checkbox"]):not([type="radio"]):not([type="range"]), textarea, select';

  let lastMouse = null;
  let cached = null;                       // the page's shape as last read
  let dirty = true;                        // ...and whether it may have changed since
  let timerDue = 0;                    // [screenX, screenY, clientX, clientY]
  let lastSent = "";
  let sentAt = 0;
  let timer = null;
  let stopped = false;
  let quiet = false;                       // a secret field is on the page right now
  let typedAt = 0;                         // when you last typed in a field here
  let messOn = true;                       // the popup's "Let PISI make a mess" switch

  // ---- where the page sits on screen -----------------------------------
  // PISI works that out from the browser's own numbers (window position,
  // screen size, pixel ratio) and the real screens; a mouse position over the
  // page helps it place the page inside the window (side panels, toolbars).
  function onMouse(ev) {
    const first = lastMouse === null;
    lastMouse = [ev.screenX, ev.screenY, ev.clientX, ev.clientY];
    if (first) schedule(0);
  }

  function geometry() {
    return {
      screen: [screen.width, screen.height],
      // where that screen starts, in the browser's coordinates (Chrome has
      // screen.left/top; availLeft/Top is the fallback)
      left: screen.left ?? screen.availLeft ?? 0, top: screen.top ?? screen.availTop ?? 0,
      win: [window.screenX, window.screenY, window.outerWidth, window.outerHeight],
      inner: [window.innerWidth, viewHeight()],
      dpr: window.devicePixelRatio, mouse: lastMouse,
      moz: typeof window.mozInnerScreenX === "number" ? [window.mozInnerScreenX, window.mozInnerScreenY] : null,
    };
  }

  // ---- the shape of the page ------------------------------------------------
  function skipNode(el) {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      if (SKIP.has(e.tagName.toUpperCase()) || e.isContentEditable
          || e.getAttribute("aria-hidden") === "true" || e.hasAttribute("data-pisi-ignore")) return true;
    }
    return unseen(el);
  }

  // Things you can't see: transparent (a menu toggle at opacity 0 sits by
  // Wikipedia's logo), hidden, or clipped away for screen readers only. The
  // pet shouldn't perch on thin air.
  let seenCache = new Map();
  function unseen(el) {
    const path = [];
    let hidden = false;
    for (let e = el, i = 0; e && e !== document.documentElement && i < 12; e = e.parentElement, i++) {
      if (seenCache.has(e)) { hidden = seenCache.get(e); break; }
      path.push(e);
      const cs = getComputedStyle(e);
      if (parseFloat(cs.opacity) < 0.1 || cs.visibility === "hidden" || cs.visibility === "collapse"
          || /inset\(50%|circle\(0/.test(cs.clipPath) || /rect\(0(px)?,? 0(px)?,? 0/.test(cs.clip)) {
        hidden = true;
        break;
      }
    }
    for (const e of path) seenCache.set(e, hidden);
    return hidden;
  }

  /** The nearest block-level ancestor (paragraph, heading, list item...). */
  function blockOf(el, cache) {
    const path = [];
    let found = null;
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      if (cache.has(e)) { found = cache.get(e); break; }
      path.push(e);
      const tag = e.tagName.toUpperCase();
      if (/^(H[1-6]|LI|DT|DD|PRE|BLOCKQUOTE|TD|TH|P)$/.test(tag)) { found = e; break; }
      const d = getComputedStyle(e).display;
      if (d && !d.startsWith("inline") && d !== "contents") { found = e; break; }
    }
    for (const e of path) cache.set(e, found);
    return found;
  }

  /** How tall the page really is on screen. Brave's innerHeight can be short
   *  (when one of its bars shows or hides) though the page is drawn further
   *  down: ask the page itself what's at a few points below it. */
  function viewHeight() {
    let lo = window.innerHeight, hi = Math.round(window.innerHeight * 1.25);
    const x = Math.round(window.innerWidth / 2);
    if (!document.elementFromPoint(x, lo + 2)) return lo;
    while (hi - lo > 2) {
      const mid = (lo + hi) >> 1;
      if (document.elementFromPoint(x, mid)) lo = mid; else hi = mid;
    }
    return lo;
  }

  function collect() {
    seenCache = new Map();
    const vw = window.innerWidth, vh = viewHeight();
    const frags = [];
    const blockIds = new Map(), kinds = [], cache = new Map();
    const range = document.createRange();
    // Only what's on screen: whole sections above or below it are skipped
    // without looking inside (far down a long article, walking every line
    // from the top used up the time budget before reaching the visible ones).
    const offscreen = (el) => {
      const r = el.getBoundingClientRect();
      return (r.width > 0 || r.height > 0) && (r.bottom < -40 || r.top > vh + 40);
    };
    const walker = document.createTreeWalker(document.body || document.documentElement,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          if (node.nodeType === Node.TEXT_NODE) return NodeFilter.FILTER_ACCEPT;
          if (SKIP.has(node.tagName.toUpperCase())) return NodeFilter.FILTER_REJECT;
          return offscreen(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_SKIP;
        },
      });
    const t0 = performance.now();
    let n = 0;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (++n % 64 === 0 && performance.now() - t0 > 40) break;   // stay cheap
      if (!node.data.trim()) continue;
      const el = node.parentElement;
      if (!el) continue;
      const box = el.getBoundingClientRect();
      if (box.bottom < 0 || box.top > vh || box.right < 0 || box.left > vw) continue;
      if (skipNode(el)) continue;
      const blk = blockOf(el, cache) || el;
      if (!blockIds.has(blk)) { blockIds.set(blk, kinds.length); kinds.push(L.kindOf(blk.tagName)); }
      const b = blockIds.get(blk);
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) {
        if (r.bottom < 0 || r.top > vh) continue;
        frags.push({ x: r.left, y: r.top, w: r.width, h: r.height, block: b, el });
      }
    }
    // keep text that's really visible: not under a sticky header, modal, banner…
    const seen = new Map();
    const visible = (f) => {
      const k = f.block + ":" + Math.round(f.y);
      if (seen.has(k)) return seen.get(k);
      const hit = document.elementFromPoint(f.x + Math.min(f.w / 2, 40), f.y + f.h / 2);
      const ok = !!hit && (hit === f.el || f.el.contains(hit) || hit.contains(f.el));
      seen.set(k, ok);
      return ok;
    };
    const shown = frags.filter(visible);
    const media = [];
    const shows = (m, r) => {
      const hit = document.elementFromPoint(r.left + r.width / 2, Math.max(0, r.top) + Math.min(4, r.height / 2));
      return !!hit && (hit === m || m.contains(hit) || hit.contains(m));
    };
    for (const m of document.querySelectorAll("img, video, picture, canvas")) {
      if (media.length >= 40) break;
      const r = m.getBoundingClientRect();
      if (r.width < 100 || r.height < 60 || r.bottom < 0 || r.top > vh) continue;
      if (!shows(m, r) || unseen(m)) continue;
      media.push({ x: r.left, y: r.top, w: r.width, h: r.height, kind: L.kindOf(m.tagName) });
    }
    // buttons and fields: boxes to hop onto or over, search boxes to nap on.
    // Only where they are: never what's typed in them.
    let ctl = 0;
    for (const m of document.querySelectorAll(CONTROLS)) {
      if (ctl >= 40) break;
      const r = m.getBoundingClientRect();
      if (r.width < 24 || r.height < 14 || r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;
      if (m.closest("[data-pisi-ignore], [aria-hidden='true']") || !shows(m, r) || unseen(m)) continue;
      const search = m.type === "search" || m.getAttribute("role") === "searchbox"
        || m.getAttribute("role") === "combobox" && !!m.closest("form[role=search], [role=search]")
        || m.tagName === "INPUT" && !!m.closest("form[role=search], [role=search], form[action*=search i]");
      media.push({ x: r.left, y: r.top, w: r.width, h: r.height,
                   kind: search ? "search" : (m.tagName === "BUTTON" || m.getAttribute("role") === "button"
                         || /^(submit|button|reset)$/i.test(m.type || "")) ? "button" : "field" });
      ctl++;
    }
    // table rows: the line along the top of each is a shelf. In a grade
    // table or a spreadsheet the cells' text is mostly too short to stand
    // on, but a cat would hop up the rows like steps.
    let rows = 0;
    for (const tr of document.querySelectorAll("tr")) {
      if (rows >= 60) break;
      const r = tr.getBoundingClientRect();
      if (r.width < 200 || r.height < 16 || r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;
      if (tr.closest("[data-pisi-ignore], [aria-hidden='true']") || !shows(tr, r) || unseen(tr)) continue;
      media.push({ x: r.left, y: r.top, w: r.width, h: 2, kind: "row" });
      rows++;
    }
    return L.structure(shown, kinds, media, vw, vh);
  }

  function report() {
    timer = null;
    if (stopped) return;
    if (document.visibilityState !== "visible") { send({ type: "gone" }); return; }
    if (document.querySelector(SECRET)) {          // a login or payment page
      if (!quiet) { quiet = true; send({ type: "gone", why: "secret", focused: document.hasFocus() }); }
      schedule(1500);
      return;
    }
    quiet = false;
    // read the page again only when something changed (a scroll, a resize,
    // new content); the heartbeat resends what we have, so an unchanged page
    // reports the same lines every time instead of a slightly different cut
    if (dirty || !cached) { cached = collect(); dirty = false; }
    const page = cached;
    // in page (CSS) pixels: PISI places them on the real screen
    const r = Math.round;
    const lines = page.lines.slice(0, 220).map((l) => [r(l.x), r(l.y), r(l.w), r(l.h), l.b]);
    const msg = {
      type: "lines", focused: document.hasFocus(), geo: geometry(),
      scroll: [r(window.scrollX), r(window.scrollY)],
      kinds: page.kinds, lines, ...goingOn(), mess: messOn,
    };
    // changes go out at once; an unchanged page still says "still here"
    // every 1.5 s so PISI can tell a live page from a closed one
    const key = JSON.stringify([msg.focused, msg.scroll, msg.geo, lines, msg.sel, msg.video,
                                msg.playing, msg.music, msg.typing, msg.end, msg.offline, msg.mess]);
    const now = Date.now();
    if (key !== lastSent || now - sentAt > 1400) { lastSent = key; sentAt = now; send(msg); }
    schedule(1500);
  }

  function schedule(ms) {
    if (stopped) return;
    const due = Date.now() + ms;
    if (timer !== null) {
      if (due >= timerDue) return;               // already coming sooner
      clearTimeout(timer);
    }
    timerDue = due;
    timer = setTimeout(report, ms);
  }

  function send(msg) {
    try { api.runtime.sendMessage(msg).catch(() => {}); } catch (e) { stop(); }
  }

  // ---- what's going on in the page -----------------------------------------
  // Rectangles and yes/no only: where your selection is (not what it says),
  // whether a video or music is playing, where you're typing (not what).
  const box = (rc) => [Math.round(rc.left), Math.round(rc.top), Math.round(rc.width), Math.round(rc.height)];
  const onScreen = (rc) => rc.width > 0 && rc.height > 0 && rc.bottom > 0 && rc.top < window.innerHeight
    && rc.right > 0 && rc.left < window.innerWidth;

  function goingOn() {
    const out = {};
    const sel = document.getSelection();
    if (sel && !sel.isCollapsed && sel.rangeCount) {
      const a = sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement);
      const rc = sel.getRangeAt(0).getBoundingClientRect();
      if (a && !a.closest("input, textarea, [contenteditable]") && onScreen(rc)) out.sel = box(rc);
    }
    // the biggest video that's started, playing or not, and anything audible
    let best = null, area = 0, music = false;
    for (const m of document.querySelectorAll("video, audio")) {
      const live = !m.paused && !m.ended && m.readyState > 2;
      if (live && !m.muted && m.volume > 0) music = true;
      if (m.tagName !== "VIDEO" || (m.currentTime === 0 && !live)) continue;
      const rc = m.getBoundingClientRect();
      if (!onScreen(rc) || rc.width < 200 || rc.height < 110) continue;
      if (rc.width * rc.height > area) { area = rc.width * rc.height; best = { m, rc, live }; }
    }
    if (best) {
      out.video = box(best.rc);
      out.playing = best.m.ended ? "ended" : best.live ? "playing" : "paused";
    }
    if (music && !(best && best.live)) out.music = true;
    const f = document.activeElement;
    if (f && Date.now() - typedAt < 4000 && f.matches("input, textarea, [contenteditable]")) {
      const rc = f.getBoundingClientRect();
      if (onScreen(rc)) out.typing = box(rc);
    }
    const doc = document.scrollingElement || document.documentElement;
    if (doc.scrollHeight > window.innerHeight * 1.6
        && window.scrollY + window.innerHeight >= doc.scrollHeight - 8) out.end = true;
    if (navigator.onLine === false) out.offline = true;
    return out;
  }

  function onKey(ev) {
    if (ev.isTrusted && ev.target && ev.target.matches
        && ev.target.matches("input:not([type=password]), textarea, [contenteditable]")) {
      const first = Date.now() - typedAt > 3000;
      typedAt = Date.now();
      if (first) schedule(50);
    }
  }

  function onMedia() { schedule(50); }

  // ---- digging -------------------------------------------------------------
  // PISI digs at (x, y), the middle of its feet on top of a line, about w
  // wide, facing dir. The words there fly off behind its paws, one by one,
  // and leave a hole the width of the cat: the line it stood on is gone
  // there, so it drops through onto the next one.
  const DIG_MS = 900;
  const calm = matchMedia("(prefers-reduced-motion: reduce)");

  function caretAt(x, y) {
    if (document.caretPositionFromPoint) {
      const p = document.caretPositionFromPoint(x, y);
      return p ? [p.offsetNode, p.offset] : null;
    }
    if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(x, y);
      return r ? [r.startContainer, r.startOffset] : null;
    }
    return null;
  }

  /** The words on the line under the band x0..x1 just below y: [{node, s, e, rect}]. */
  function wordsUnder(x0, x1, y) {
    const line = collect().lines.find((l) => l.x <= x1 && l.x + l.w >= x0
                                             && Math.abs(l.y - y) <= Math.max(8, l.h * 0.6));
    if (!line) return [];
    const py = line.y + line.h / 2;
    const found = new Map();
    const range = document.createRange();
    for (let x = Math.max(x0, line.x + 1); x <= Math.min(x1, line.x + line.w - 1); x += 4) {
      const c = caretAt(x, py);
      if (!c) continue;
      const [node, off] = c;
      if (!node || node.nodeType !== Node.TEXT_NODE || !node.parentElement
          || skipNode(node.parentElement) || node.parentElement.closest("[data-pisi-dug]")) continue;
      const span = L.wordAt(node.data, Math.min(off, node.data.length - 1));
      if (!span) continue;
      range.setStart(node, span[0]);
      range.setEnd(node, span[1]);
      const rc = range.getBoundingClientRect();
      if (rc.right < x0 - 2 || rc.left > x1 + 2 || Math.abs(rc.top + rc.height / 2 - py) > line.h) continue;
      const key = span[0] + ":" + span[1];
      if (!found.has(node)) found.set(node, new Map());
      found.get(node).set(key, { node, s: span[0], e: span[1], rect: rc });
    }
    return [...found.values()].flatMap((m) => [...m.values()]);
  }

  /** Hide one word, keeping its space (so the hole stays a hole), and throw
   *  a copy of it off the page: kicked back behind the paws (a dig) or
   *  pushed over the edge (a knock). */
  function flick(w, dir, push = false) {
    if (!w.node.isConnected || w.e > w.node.data.length) return;
    const word = w.node.splitText(w.s);
    word.splitText(w.e - w.s);
    const hole = document.createElement("span");
    hole.dataset.pisiDug = "1";
    hole.style.visibility = "hidden";
    word.replaceWith(hole);
    hole.appendChild(word);
    if (calm.matches || document.visibilityState !== "visible") return;
    const cs = getComputedStyle(hole.parentElement);
    const fly = document.createElement("span");
    fly.append(word.data);                 // a copy, on this page only
    fly.setAttribute("aria-hidden", "true");
    fly.dataset.pisiIgnore = "1";
    Object.assign(fly.style, {
      position: "fixed", left: w.rect.left + "px", top: w.rect.top + "px", margin: "0", padding: "0",
      font: cs.font, color: cs.color, letterSpacing: cs.letterSpacing, textTransform: cs.textTransform,
      whiteSpace: "pre", lineHeight: w.rect.height + "px", pointerEvents: "none",
      zIndex: "2147483646", willChange: "transform, opacity", background: "none", border: "0",
    });
    document.documentElement.appendChild(fly);
    // a dig kicks it back behind the paws, up and over; a knock tips it
    // forward off the edge with a little hop; either way it spins and falls
    let vx = push ? dir * (110 + Math.random() * 90) : -dir * (90 + Math.random() * 190) + (Math.random() - 0.5) * 60;
    let vy = push ? -(90 + Math.random() * 90) : -(220 + Math.random() * 220);
    const spin = push ? dir * (160 + Math.random() * 260) : (Math.random() - 0.5) * 720;
    let x = 0, y = 0, a = 0, t0 = performance.now(), last = t0;
    const step = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      vy += 1700 * dt;
      vx *= 0.995;
      x += vx * dt; y += vy * dt; a += spin * dt;
      const age = (now - t0) / 1000;
      fly.style.transform = `translate(${x}px, ${y}px) rotate(${a}deg)`;
      fly.style.opacity = String(Math.max(0, Math.min(1, (1.7 - age) / 0.6)));
      if (age < 1.7 && w.rect.top + y < window.innerHeight + 60) requestAnimationFrame(step);
      else fly.remove();
    };
    requestAnimationFrame(step);
    setTimeout(() => fly.remove(), 2200);   // hidden mid-flight: no frames, no stragglers
  }

  /** Knock the word at the end of the line PISI stands on (at x, y, the
   *  edge it faces: dir) clean off the page. Only a word right there: never
   *  one further along the line. */
  function knock(x, y, dir) {
    if (quiet || !messOn) return;
    const words = dir > 0 ? wordsUnder(x - 140, x + 24, y) : wordsUnder(x - 24, x + 140, y);
    if (!words.length) return;
    const end = words.reduce((a, b) => (dir > 0 ? (b.rect.right > a.rect.right ? b : a)
                                                 : (b.rect.left < a.rect.left ? b : a)));
    flick(end, dir, true);
    dirty = true;
    schedule(0);
  }

  function dig(x, y, w, dir) {
    if (quiet || !messOn) return;
    const words = wordsUnder(x - w / 2, x + w / 2, y);
    if (!words.length) return;
    // from the outside in: the word under its middle goes last, and down it goes
    words.sort((a, b) => Math.abs(b.rect.left + b.rect.width / 2 - x)
                         - Math.abs(a.rect.left + a.rect.width / 2 - x));
    const gap = DIG_MS / words.length;
    words.forEach((wd, i) => setTimeout(() => {
      // offsets shift once an earlier word in the same text node is split off:
      // find this word again by its place on screen
      const fresh = wordsUnder(wd.rect.left + 1, wd.rect.right - 1, y)
        .find((f) => Math.abs(f.rect.left - wd.rect.left) < 2);
      if (fresh) flick(fresh, dir);
      dirty = true;
      schedule(i === words.length - 1 ? 0 : 120);
    }, i * gap));
  }

  function tidyPage() {
    for (const w of document.querySelectorAll("[data-pisi-dug]")) w.replaceWith(...w.childNodes);
    document.body && document.body.normalize();
    dirty = true;
    schedule(0);
  }

  // ---- guarding: the menu's "Fade the page while I guard" ---------------------
  // A soft blur over the page while the cat sits on it; clicks still go through.
  let veil = null;
  function fade(on) {
    if (on && !veil) {
      veil = document.createElement("div");
      veil.setAttribute("aria-hidden", "true");
      Object.assign(veil.style, {
        position: "fixed", inset: "0", zIndex: "2147483646", pointerEvents: "none",
        backdropFilter: "blur(7px) saturate(0.6)", webkitBackdropFilter: "blur(7px) saturate(0.6)",
        background: "rgba(245, 238, 226, 0.35)", opacity: "0", transition: "opacity 0.8s ease",
      });
      document.documentElement.append(veil);
      requestAnimationFrame(() => { if (veil) veil.style.opacity = "1"; });
    } else if (!on && veil) {
      const v = veil;
      veil = null;
      v.style.opacity = "0";
      setTimeout(() => v.remove(), 800);
    }
  }

  function stop() {
    stopped = true;
    fade(false);
    if (timer !== null) clearTimeout(timer);
    removeEventListener("scroll", onScroll, true);
    removeEventListener("resize", onScroll);
    removeEventListener("mousemove", onMouse, true);
    removeEventListener("keydown", onKey, true);
    document.removeEventListener("selectionchange", onScroll);
    for (const e of MEDIA_EVENTS) document.removeEventListener(e, onMedia, true);
    document.removeEventListener("visibilitychange", onScroll);
    removeEventListener("focus", onScroll);
    removeEventListener("blur", onScroll);
    try { api.runtime.sendMessage({ type: "gone" }).catch(() => {}); } catch (e) { /* gone */ }
  }

  function onScroll() { dirty = true; schedule(80); }
  const MEDIA_EVENTS = ["play", "pause", "ended", "volumechange"];

  function start() {
    api.runtime.onMessage.addListener((msg) => {
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "dig") dig(msg.x, msg.y, msg.w, msg.dir);
      else if (msg.type === "knock") knock(msg.x, msg.y, msg.dir);
      else if (msg.type === "tidy") tidyPage();
      else if (msg.type === "fade") fade(!!msg.on);
      else if (msg.type === "stop") { stop(); window.__pisiPet = false; }
      else if (msg.type === "ping") schedule(0);
    });
    addEventListener("scroll", onScroll, { capture: true, passive: true });
    addEventListener("resize", onScroll, { passive: true });
    addEventListener("mousemove", onMouse, { capture: true, passive: true });
    addEventListener("keydown", onKey, { capture: true, passive: true });
    document.addEventListener("selectionchange", onScroll);
    for (const e of MEDIA_EVENTS) document.addEventListener(e, onMedia, true);
    addEventListener("online", onScroll);
    addEventListener("offline", onScroll);
    addEventListener("contextmenu", (ev) => {
      // a right-click: where, in case you pick "Throw PISI a toy here"
      send({ type: "spot", x: Math.round(ev.clientX), y: Math.round(ev.clientY) });
    }, { capture: true, passive: true });
    api.storage.onChanged.addListener((ch) => {
      if (ch.mess) { messOn = ch.mess.newValue !== false; schedule(0); }
    });
    document.addEventListener("visibilitychange", onScroll);
    addEventListener("focus", onScroll);
    addEventListener("blur", onScroll);
    new MutationObserver(() => { dirty = true; schedule(400); }).observe(document.documentElement,
      { childList: true, subtree: true, characterData: true });
    addEventListener("pagehide", () => send({ type: "gone" }));
    schedule(0);
  }

  // switched off for this site, or paused everywhere? then do nothing at all
  api.storage.local.get(["off", "paused", "mess"]).then(({ off, paused, mess }) => {
    if (paused || (off || []).includes(location.hostname)) { window.__pisiPet = false; return; }
    messOn = mess !== false;
    start();
  });
})();
