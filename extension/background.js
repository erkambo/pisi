// The go-between: content scripts on web pages -> the PISI app on this
// computer (through the browser's native messaging, never the network), and
// PISI's "I landed here" back to the page you're looking at.
"use strict";

const api = globalThis.browser ?? globalThis.chrome;
if (typeof PisiLines === "undefined" && typeof importScripts === "function") importScripts("lines.js");
const HOST = "app.pisi.bridge";

let port = null;
let connected = false;
let lastError = "";
let heard = false;                       // a connection attempt has been answered
let retryAt = 0;
let focusTab = null;                     // the tab that last reported focus
const spots = new Map();                 // tab -> where you last right-clicked (page px)
const pageState = new Map();             // tab -> {state, why}: PISI's word on each page
let prefs = { paused: false, off: [], guard: [], fade: true };  // the popup's switches
const faded = new Set();                 // tabs whose page is blurred behind a guarding cat

// ---- the icon's badge: can the cat use this page? -----------------------------
// PISI tells us (it knows whether it found the page on screen, whether it's
// napping through a focus block...); we only add what PISI can't know.
const BADGES = {
  on:      { text: "\u2713", color: "#2e9e5b" },   // a tick: playing here
  finding: { text: "\u2026", color: "#e8943a" },   // an ellipsis: still finding the page
  napping: { text: "zz", color: "#7a6fd0" },        // a focus block: it stays down
  guarding: { text: "hey", color: "#d9534f" },      // ... and sits on this distracting site
  off:     { text: "off", color: "#8a8a8a" },
  down:    { text: "!", color: "#c0392b" },         // PISI isn't there
};

function hostOf(url) {
  try { return new URL(url).hostname; } catch (e) { return ""; }
}

// What the badge on a tab means, in words too (the popup and tooltip use it).
function tabStatus(tabId, url) {
  const host = hostOf(url || "");
  if (prefs.paused) return { state: "off", why: "Paused everywhere (in this menu)" };
  if (host && prefs.off.includes(host)) return { state: "off", why: "Switched off on " + host };
  if (!connected) {
    if (!heard) return { state: "", why: "" };   // still connecting: no alarm yet
    return { state: "down", why: lastError ? "PISI isn't reachable: " + lastError
                                           : "PISI isn't running" };
  }
  return pageState.get(tabId) || { state: "", why: "" };
}

async function badge(tabId) {
  let url = "";
  try { url = (await api.tabs.get(tabId)).url || ""; } catch (e) { return; }   // tab gone
  const s = tabStatus(tabId, url);
  const b = BADGES[s.state];
  const action = api.action || api.browserAction;
  if (!action) return;
  action.setBadgeText({ tabId, text: b ? b.text : "" }).catch(() => {});
  if (b) action.setBadgeBackgroundColor({ tabId, color: b.color }).catch(() => {});
  action.setTitle({ tabId, title: s.why ? "PISI: " + s.why : "PISI" }).catch(() => {});
}

async function badgeAll() {
  const tabs = await api.tabs.query({}).catch(() => []);
  for (const t of tabs) badge(t.id);
}

api.storage.local.get(["paused", "off", "guard", "fade"]).then(({ paused = false, off = [], guard = [], fade = true }) => {
  prefs = { paused, off, guard, fade: fade !== false };
  badgeAll();
  guardMenu();
});

// ---- guarding: fade the page behind the cat ---------------------------------
// Only while PISI says it's sitting on that tab, and only if the menu's
// "Fade the page while I guard" is on.
function syncFade(tab) {
  const want = prefs.fade && connected && (pageState.get(tab) || {}).state === "guarding";
  if (want === faded.has(tab)) return;
  if (want) faded.add(tab); else faded.delete(tab);
  api.tabs.sendMessage(tab, { type: "fade", on: want }).catch(() => {});
}
function syncFades() {
  for (const tab of new Set([...faded, ...pageState.keys()])) syncFade(tab);
}

// ---- pausing ------------------------------------------------------------------
// "Pause everywhere" or "off on this site" from the popup: tell open pages now
// (new pages read the setting themselves when they load).
api.storage.onChanged.addListener((changes) => {
  if (changes.guard) { prefs.guard = changes.guard.newValue || []; guardMenu(); }
  if (changes.fade) { prefs.fade = changes.fade.newValue !== false; syncFades(); }
  if (!changes.paused && !changes.off) return;
  api.storage.local.get(["paused", "off"]).then(async ({ paused, off }) => {
    prefs = { ...prefs, paused: !!paused, off: off || [] };
    badgeAll();
    const tabs = await api.tabs.query({});
    for (const t of tabs) {
      let host = "";
      try { host = new URL(t.url || "").hostname; } catch (e) { /* no url access */ }
      if (paused || (host && (off || []).includes(host))) {
        api.tabs.sendMessage(t.id, { type: "stop" }).catch(() => {});
      }
    }
  });
});

// ---- installed or reloaded: join the pages that are already open -------------
// Browsers only add content scripts to pages loaded from now on, and a reload of
// the extension cuts off the ones already running. So step into open tabs now,
// with the same exceptions as the manifest (mail, banks, password managers...).
api.runtime.onInstalled.addListener(async () => {
  const cs = api.runtime.getManifest().content_scripts[0];
  const { paused, off } = await api.storage.local.get(["paused", "off"]);
  if (paused) return;
  const tabs = await api.tabs.query({ url: cs.matches });
  for (const t of tabs) {
    if (!t.url || (cs.exclude_matches || []).some((p) => PisiLines.matchesPattern(t.url, p))) continue;
    let host = "";
    try { host = new URL(t.url).hostname; } catch (e) { continue; }
    if ((off || []).includes(host)) continue;
    api.scripting.executeScript({ target: { tabId: t.id }, files: cs.js }).catch(() => {});
  }
});

// ---- talking to PISI ---------------------------------------------------------
function connect() {
  if (port || Date.now() < retryAt) return port;
  try {
    port = api.runtime.connectNative(HOST);
  } catch (e) {
    lastError = String(e && e.message || e);
    heard = true;
    retryAt = Date.now() + 5000;
    badgeAll();
    return null;
  }
  port.onMessage.addListener((msg) => {
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "status") {
      connected = !!msg.connected;
      heard = true;
      if (!connected) pageState.clear();
      syncFades();
      badgeAll();
      return;
    }
    if (msg.type === "page" && typeof msg.tab === "number") {
      pageState.set(msg.tab, { state: String(msg.state || ""), why: String(msg.why || "") });
      syncFade(msg.tab);
      badge(msg.tab);
      return;
    }
    if ((msg.type === "dig" || msg.type === "knock") && focusTab !== null) {
      api.tabs.sendMessage(focusTab, { type: msg.type, x: msg.x, y: msg.y, w: msg.w, dir: msg.dir })
        .catch(() => {});
    }
  });
  port.onDisconnect.addListener(() => {
    const err = api.runtime.lastError;
    lastError = err ? String(err.message || err) : "PISI's bridge closed";
    port = null;
    connected = false;
    heard = true;
    pageState.clear();
    syncFades();
    retryAt = Date.now() + 5000;
    badgeAll();
  });
  return port;
}

function post(msg) {
  const p = connect();
  if (!p) return;
  try { p.postMessage(msg); } catch (e) { port = null; connected = false; }
}

api.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || typeof msg !== "object") return;
  if (msg.type === "status") {                      // from the popup
    connect();
    const page = typeof msg.tab === "number" ? tabStatus(msg.tab, msg.url) : null;
    reply({ connected, error: connected ? "" : lastError, host: HOST, page });
    return;
  }
  const tab = sender.tab && sender.tab.id;
  if (tab === undefined) return;
  if (msg.type === "lines") {
    if (msg.focused) focusTab = tab;
    // a distracting site (the popup's list) goes out as a yes/no, never the site
    const guard = PisiLines.onSite(hostOf(sender.tab.url || ""), prefs.guard);
    post({ type: "lines", tab, focused: !!msg.focused, geo: msg.geo, scroll: msg.scroll,
           kinds: msg.kinds, lines: msg.lines, guard, guards: prefs.guard.length > 0,
           sel: msg.sel, video: msg.video, playing: msg.playing, music: !!msg.music,
           typing: msg.typing, end: !!msg.end, offline: !!msg.offline, mess: msg.mess !== false });
  } else if (msg.type === "gone") {
    // "secret": a login or payment page you're looking at (the cat looks away)
    const why = msg.why === "secret" && msg.focused ? "secret" : "";
    post({ type: "gone", tab, why });
    if (focusTab === tab) focusTab = null;
  } else if (msg.type === "spot") {
    spots.set(tab, [msg.x, msg.y]);
  }
});

api.tabs.onRemoved.addListener((tab) => {
  post({ type: "gone", tab, why: "closed" });
  pageState.delete(tab);
  faded.delete(tab);
  spots.delete(tab);
  if (focusTab === tab) focusTab = null;
});
// a new page in a tab: its old badge (and fade) no longer applies
api.tabs.onUpdated.addListener((tab, info) => {
  if (info.status === "loading") { pageState.delete(tab); faded.delete(tab); badge(tab); }
  if (info.url) guardMenu();
});
if (api.tabs.onActivated) api.tabs.onActivated.addListener(() => guardMenu());

// ---- right-click: play right here ------------------------------------------------
const MENU = [["pisi-toy", "Throw PISI a toy here", "toy"], ["pisi-laser", "Shine the laser here", "laser"],
              ["pisi-tidy", "Tidy up what PISI dug", "tidy"]];
const CONTEXTS = ["page", "selection", "link", "image", "video"];
const PAGES = ["http://*/*", "https://*/*"];
function menus() {
  if (!api.contextMenus) return;
  api.contextMenus.removeAll(() => {
    for (const [id, title] of MENU) {
      api.contextMenus.create({ id, title, contexts: CONTEXTS, documentUrlPatterns: PAGES });
    }
    // ticked on the sites PISI guards (kept in step with the tab you're on)
    api.contextMenus.create({ id: "pisi-guard", title: "PISI, guard this site", type: "checkbox",
                              contexts: CONTEXTS, documentUrlPatterns: PAGES });
    guardMenu();
  });
}

async function guardMenu() {
  if (!api.contextMenus || !api.contextMenus.update) return;
  const [t] = await api.tabs.query({ active: true, currentWindow: true }).catch(() => []);
  const on = !!t && PisiLines.onSite(hostOf(t.url || ""), prefs.guard);
  try {
    const r = api.contextMenus.update("pisi-guard", { checked: on });
    if (r && r.catch) r.catch(() => {});
  } catch (e) { /* not made yet */ }
}

async function guardSite(t, on) {
  const host = hostOf(t.url || "");
  if (!host) return;
  const { guard = [], off = [] } = await api.storage.local.get(["guard", "off"]);
  const next = { guard: PisiLines.setGuard(guard, host, on) };
  if (on && off.includes(host)) {                   // it has to see the page to sit on it
    next.off = off.filter((h) => h !== host);
    api.scripting.executeScript({ target: { tabId: t.id }, files: ["lines.js", "content.js"] })
      .catch(() => {});
  }
  await api.storage.local.set(next);
}

// ---- first install: say hello, and help pick what to guard ------------------------
api.runtime.onInstalled.addListener((details) => {
  if (details && details.reason === "install" && api.tabs.create) {
    api.tabs.create({ url: api.runtime.getURL("welcome.html") }).catch(() => {});
  }
});
api.runtime.onInstalled.addListener(menus);
if (api.runtime.onStartup) api.runtime.onStartup.addListener(menus);
if (api.contextMenus) {
  api.contextMenus.onClicked.addListener((info, t) => {
    if (info.menuItemId === "pisi-guard") { if (t) guardSite(t, !!info.checked); return; }
    const item = MENU.find((m) => m[0] === info.menuItemId);
    if (!item || !t) return;
    if (item[2] === "tidy") { api.tabs.sendMessage(t.id, { type: "tidy" }).catch(() => {}); return; }
    const [x, y] = spots.get(t.id) || [null, null];
    post({ type: "play", tab: t.id, what: item[2], x, y });
  });
}
