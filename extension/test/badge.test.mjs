// node --test extension/test/badge.test.mjs   (run by tests/test_web_perch.py)
// background.js against a fake browser: what the icon's badge says.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const ext = new URL("../", import.meta.url);
const src = (f) => readFileSync(new URL(f, ext), "utf8");
const tick = () => new Promise((r) => setTimeout(r, 0));

function load({ storage = {}, tabs = [{ id: 7, url: "https://example.org/a" }] } = {}) {
  const badges = new Map(), titles = new Map(), listeners = {};
  const sent = [], created = [], menus = new Map();
  let port = null;
  const posted = [];
  const all = {};                          // a name can have several listeners: call them all
  const on = (name) => ({ addListener: (f) => {
    (all[name] = all[name] || []).push(f);
    listeners[name] = (...a) => { let r; for (const g of all[name]) r = g(...a); return r; };
  } });
  const chrome = {
    runtime: {
      lastError: null,
      getManifest: () => ({ content_scripts: [{ matches: [], js: [] }] }),
      getURL: (p) => "chrome-extension://pisi/" + p,
      onInstalled: on("installed"), onMessage: on("message"),
      connectNative: () => {
        port = { postMessage(m) { posted.push(m); }, onMessage: on("portMessage"), onDisconnect: on("disconnect") };
        return port;
      },
    },
    storage: {
      local: {
        get: async () => storage,
        set: async (v) => { Object.assign(storage, v); listeners.storage && listeners.storage(
          Object.fromEntries(Object.entries(v).map(([k, nv]) => [k, { newValue: nv }]))); },
      },
      onChanged: on("storage"),
    },
    tabs: {
      query: async () => tabs, get: async (id) => tabs.find((t) => t.id === id),
      sendMessage: async (tab, m) => { sent.push([tab, m]); }, onRemoved: on("removed"), onUpdated: on("updated"),
      onActivated: on("activated"), create: async (o) => { created.push(o.url); },
    },
    scripting: { executeScript: async () => {} },
    contextMenus: {
      removeAll: (cb) => cb && cb(), onClicked: on("menu"),
      create: (o) => { menus.set(o.id, { ...o }); },
      update: async (id, o) => { Object.assign(menus.get(id) || {}, o); },
    },
    action: {
      setBadgeText: async ({ tabId, text }) => { badges.set(tabId, text); },
      setBadgeBackgroundColor: async () => {},
      setTitle: async ({ tabId, title }) => { titles.set(tabId, title); },
    },
  };
  const ctx = vm.createContext({ chrome, globalThis: undefined, URL, Date, console, setTimeout });
  ctx.globalThis = ctx;
  vm.runInContext(src("lines.js"), ctx);
  vm.runInContext(src("background.js"), ctx);
  const fromPage = (msg, tab = 7) =>
    listeners.message(msg, { tab: tabs.find((t) => t.id === tab) || { id: tab } }, () => {});
  const fromPisi = (msg) => listeners.portMessage(msg);
  const popup = () => new Promise((r) => listeners.message({ type: "status", tab: 7, url: tabs[0].url }, {}, r));
  return { badges, titles, fromPage, fromPisi, popup, listeners, posted, sent, created, menus, storage };
}

test("no badge before anything is known, a tick when PISI plays on the page", async () => {
  const b = load();
  await tick();
  assert.equal(b.badges.get(7), "");                          // no alarm while connecting
  b.fromPage({ type: "lines", focused: true, lines: [] });    // a page speaks: connect
  b.fromPisi({ type: "status", connected: true });
  b.fromPisi({ type: "page", tab: 7, state: "on", why: "PISI can play on this page" });
  await tick();
  assert.equal(b.badges.get(7), "✓");
  assert.match(b.titles.get(7), /can play on this page/);
  const s = await b.popup();
  assert.equal(s.page.state, "on");
});

test("napping, finding, and PISI going away", async () => {
  const b = load();
  b.fromPage({ type: "lines", focused: true, lines: [] });
  b.fromPisi({ type: "status", connected: true });
  b.fromPisi({ type: "page", tab: 7, state: "napping", why: "napping" });
  await tick();
  assert.equal(b.badges.get(7), "zz");
  b.fromPisi({ type: "page", tab: 7, state: "finding", why: "finding" });
  await tick();
  assert.equal(b.badges.get(7), "…");
  b.fromPisi({ type: "status", connected: false });           // PISI quit
  await tick();
  assert.equal(b.badges.get(7), "!");
  assert.match(b.titles.get(7), /isn't running/);
});

test("switched off on this site or paused everywhere says so", async () => {
  const b = load({ storage: { off: ["example.org"] } });
  await tick(); await tick();
  assert.equal(b.badges.get(7), "off");
  const p = load({ storage: { paused: true } });
  await tick(); await tick();
  assert.equal(p.badges.get(7), "off");
  assert.match(p.titles.get(7), /Paused everywhere/);
});

test("a guarded site goes to PISI as a yes/no, never the address", async () => {
  const b = load({
    storage: { guard: ["youtube.com"] },
    tabs: [{ id: 7, url: "https://www.youtube.com/watch?v=x" }, { id: 8, url: "https://example.org/" }],
  });
  await tick();
  b.fromPage({ type: "lines", focused: true, lines: [] }, 7);
  b.fromPage({ type: "lines", focused: true, lines: [] }, 8);
  const [yt, other] = b.posted;
  assert.equal(yt.guard, true);
  assert.equal(other.guard, false);
  assert.ok(!JSON.stringify(b.posted).includes("youtube"));
  b.fromPisi({ type: "status", connected: true });
  b.fromPisi({ type: "page", tab: 7, state: "guarding", why: "PISI is guarding your focus block" });
  await tick();
  assert.equal(b.badges.get(7), "hey");
});

test("what's going on in the page goes along, and why a page went away", async () => {
  const b = load({ tabs: [{ id: 7, url: "https://example.org/a" }] });
  await tick();
  b.fromPage({ type: "lines", focused: true, lines: [], sel: [1, 2, 3, 4], video: [0, 0, 400, 225],
               playing: "paused", music: true, typing: [5, 6, 7, 8], end: true, mess: false });
  const m = b.posted[0];
  assert.deepEqual([m.sel, m.video, m.playing, m.music, m.typing, m.end, m.mess],
                   [[1, 2, 3, 4], [0, 0, 400, 225], "paused", true, [5, 6, 7, 8], true, false]);
  b.fromPage({ type: "gone", why: "secret", focused: true });
  b.fromPage({ type: "gone", why: "secret", focused: false });   // a login page in the background
  b.listeners.removed(7);
  assert.deepEqual(b.posted.slice(1).map((p) => p.why), ["secret", "", "closed"]);
});

test("right-click: a toy where you clicked, the laser, or tidying up", async () => {
  const b = load();
  await tick();
  b.fromPage({ type: "lines", focused: true, lines: [] });
  b.fromPage({ type: "spot", x: 120, y: 340 });
  b.listeners.menu({ menuItemId: "pisi-toy" }, { id: 7 });
  b.listeners.menu({ menuItemId: "pisi-laser" }, { id: 7 });
  const plays = b.posted.filter((p) => p.type === "play");
  assert.deepEqual(plays.map((p) => [p.what, p.x, p.y]), [["toy", 120, 340], ["laser", 120, 340]]);
});

test("PISI hears whether any site is guarded, as a yes/no", async () => {
  const none = load();
  await tick();
  none.fromPage({ type: "lines", focused: true, lines: [] });
  assert.equal(none.posted[0].guards, false);
  const some = load({ storage: { guard: ["reddit.com"] } });
  await tick();
  some.fromPage({ type: "lines", focused: true, lines: [] });
  assert.equal(some.posted[0].guards, true);
  assert.ok(!JSON.stringify(some.posted).includes("reddit"));
});

test("the page fades while the cat guards it, unless that's switched off", async () => {
  const b = load({ storage: { guard: ["example.org"] } });
  await tick();
  b.fromPage({ type: "lines", focused: true, lines: [] });
  b.fromPisi({ type: "status", connected: true });
  b.fromPisi({ type: "page", tab: 7, state: "guarding", why: "" });
  b.fromPisi({ type: "page", tab: 7, state: "guarding", why: "" });     // said again: no repeat
  b.fromPisi({ type: "page", tab: 7, state: "on", why: "" });            // dragged off
  const fades = () => b.sent.filter(([, m]) => m.type === "fade").map(([t, m]) => [t, m.on]);
  assert.deepEqual(fades(), [[7, true], [7, false]]);
  b.fromPisi({ type: "page", tab: 7, state: "guarding", why: "" });
  b.fromPisi({ type: "status", connected: false });                      // PISI quit: unfade
  assert.deepEqual(fades().slice(2), [[7, true], [7, false]]);
  await b.listeners.storage({ fade: { newValue: false } });
  b.fromPisi({ type: "status", connected: true });
  b.fromPisi({ type: "page", tab: 7, state: "guarding", why: "" });
  assert.equal(fades().length, 4);                                       // switched off: no fade
});

test("right-click to guard a site, ticked where it's guarded; a welcome page on install", async () => {
  const b = load({ storage: { guard: [], off: ["example.org"] } });
  await tick();
  b.listeners.installed({ reason: "install" });
  assert.deepEqual(b.created, ["chrome-extension://pisi/welcome.html"]);
  b.listeners.menu({ menuItemId: "pisi-guard", checked: true }, { id: 7, url: "https://example.org/a" });
  await tick(); await tick();
  assert.deepEqual(b.storage.guard, ["example.org"]);
  assert.deepEqual(b.storage.off, []);                                   // it has to see the page
  b.listeners.menu({ menuItemId: "pisi-guard", checked: false }, { id: 7, url: "https://example.org/a" });
  await tick(); await tick();
  assert.deepEqual(b.storage.guard, []);
  const u = load();
  await tick();
  u.listeners.installed({ reason: "update" });                           // a reload: no welcome
  assert.deepEqual(u.created, []);
});
