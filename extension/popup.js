// Toolbar popup: PISI plays on pages by default; switch it off for this site
// or pause it everywhere, mark the sites it guards during focus blocks, let it
// make a mess (or tidy up after it), see whether the PISI app is reachable.
"use strict";

const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);
let guardList = [];                     // the sites PISI guards, as last shown

async function currentTab() {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function hostOf(url) {
  try {
    const u = new URL(url);
    return /^https?:$/.test(u.protocol) ? u.hostname : null;
  } catch (e) { return null; }
}

async function refreshStatus() {
  const tab = await currentTab();
  const s = await api.runtime.sendMessage({ type: "status", tab: tab && tab.id, url: tab && tab.url })
    .catch(() => null);
  const el = $("status");
  if (s && s.connected) {
    el.textContent = "Connected"; el.className = "status ok"; $("help").hidden = true;
  } else {
    el.textContent = "PISI not found"; el.className = "status bad"; $("help").hidden = false;
  }
  // and this page: is the cat using it, and if not, why not
  const page = $("page");
  const p = s && s.page;
  page.textContent = p && p.why ? p.why : (s && s.connected ? "Waiting for this page…" : "");
  page.className = "pagestate " + (p && p.state ? p.state : "");
  page.hidden = !page.textContent;
  // guarded sites it can't get to: say so instead of failing quietly
  const warn = $("guardwarn");
  const here = $("guard").checked;
  if (here && (!s || !s.connected || (p && (p.state === "off" || p.state === "down")))) {
    warn.textContent = "PISI can't reach this page right now, so it can't guard it."
      + (p && p.why ? " (" + p.why + ")" : s && s.connected ? "" : " (PISI isn't running)");
  } else if (!here && guardList.length && !(s && s.connected)) {
    warn.textContent = "PISI isn't running, so it can't guard your sites.";
  } else {
    warn.textContent = "";
  }
  warn.hidden = !warn.textContent;
}

// One click to guard the usual distractions (shown while nothing's guarded).
function showPicks(sites) {
  $("picks").hidden = sites.length > 0;
  $("pickbtns").replaceChildren(...PisiLines.DISTRACTIONS.map(([name, pick]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = name;
    b.addEventListener("click", async () => {
      const { guard: cur = [] } = await api.storage.local.get("guard");
      const next = PisiLines.pickSites(cur, pick, true);
      await api.storage.local.set({ guard: next });
      showGuarded(next);
      const tab = await currentTab();
      $("guard").checked = PisiLines.onSite(hostOf((tab && tab.url) || ""), next);
    });
    return b;
  }));
}

// The guarded sites, each with a way to let it go.
function showGuarded(sites) {
  guardList = [...sites];
  showPicks(guardList);
  const ul = $("guarded");
  ul.replaceChildren(...[...sites].sort().map((s) => {
    const li = document.createElement("li");
    const x = document.createElement("button");
    x.type = "button";
    x.textContent = "\u00d7";
    x.title = "Stop guarding " + s;
    x.setAttribute("aria-label", x.title);
    x.addEventListener("click", async () => {
      const { guard: cur = [] } = await api.storage.local.get("guard");
      const next = cur.filter((g) => g !== s);
      await api.storage.local.set({ guard: next });
      showGuarded(next);
      const tab = await currentTab();
      $("guard").checked = PisiLines.onSite(hostOf((tab && tab.url) || ""), next);
    });
    li.append(s, x);
    return li;
  }));
}

async function init() {
  const tab = await currentTab();
  const host = tab && hostOf(tab.url || "");
  const { off = [], paused = false, mess = true, guard = [], fade = true } =
    await api.storage.local.get(["off", "paused", "mess", "guard", "fade"]);
  if (!host) {
    $("site").disabled = true; $("nosite").hidden = false;
    $("guard").disabled = true;
  } else {
    $("host").textContent = host;
    $("site").checked = !off.includes(host);
    $("guard").checked = PisiLines.onSite(host, guard);
  }
  showGuarded(guard);
  $("paused").checked = paused;
  $("mess").checked = mess !== false;
  $("fade").checked = fade !== false;

  $("site").addEventListener("change", async (ev) => {
    const { off: cur = [] } = await api.storage.local.get("off");
    const next = cur.filter((h) => h !== host);
    if (!ev.target.checked) next.push(host);
    await api.storage.local.set({ off: next });
    if (ev.target.checked) {
      await api.scripting.executeScript({ target: { tabId: tab.id }, files: ["lines.js", "content.js"] })
        .catch(() => {});
    }
  });
  $("paused").addEventListener("change", async (ev) => {
    await api.storage.local.set({ paused: ev.target.checked });
    if (!ev.target.checked && tab) {
      await api.scripting.executeScript({ target: { tabId: tab.id }, files: ["lines.js", "content.js"] })
        .catch(() => {});
    }
  });
  $("guard").addEventListener("change", async (ev) => {
    const { guard: cur = [] } = await api.storage.local.get("guard");
    const next = PisiLines.setGuard(cur, host, ev.target.checked);
    await api.storage.local.set({ guard: next });
    showGuarded(next);
    if (ev.target.checked && !$("site").checked) {   // it has to see the page to sit on it
      $("site").checked = true;
      $("site").dispatchEvent(new Event("change"));
    }
  });
  $("mess").addEventListener("change", (ev) => api.storage.local.set({ mess: ev.target.checked }));
  $("fade").addEventListener("change", (ev) => api.storage.local.set({ fade: ev.target.checked }));
  $("tidy").addEventListener("click", () => {
    if (tab) api.tabs.sendMessage(tab.id, { type: "tidy" }).catch(() => {});
  });
  refreshStatus();
  setTimeout(refreshStatus, 700);       // the first check may still be connecting
  setInterval(refreshStatus, 1500);     // follow it while the menu's open
}

init();
