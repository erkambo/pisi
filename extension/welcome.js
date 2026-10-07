// The page that opens when the extension is installed: what it does, and the
// usual distractions to guard in one click each.
"use strict";

const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);

async function showStatus() {
  const s = await api.runtime.sendMessage({ type: "status" }).catch(() => null);
  const el = $("status");
  el.textContent = s && s.connected ? "Connected to PISI" : "PISI isn't running yet";
  el.className = "status " + (s && s.connected ? "ok" : "bad");
  $("help").hidden = !!(s && s.connected);
}

async function showPicks() {
  const { guard = [] } = await api.storage.local.get("guard");
  $("picks").replaceChildren(...PisiLines.DISTRACTIONS.map(([name, pick]) => {
    const b = document.createElement("button");
    const on = pick.every((s) => guard.includes(s));
    b.type = "button";
    b.textContent = (on ? "✓ " : "+ ") + name;
    b.setAttribute("aria-pressed", String(on));
    b.addEventListener("click", async () => {
      const { guard: cur = [] } = await api.storage.local.get("guard");
      await api.storage.local.set({ guard: PisiLines.pickSites(cur, pick, !on) });
      showPicks();
    });
    return b;
  }));
}

async function init() {
  const { mess = true, fade = true } = await api.storage.local.get(["mess", "fade"]);
  $("mess").checked = mess !== false;
  $("fade").checked = fade !== false;
  $("mess").addEventListener("change", (ev) => api.storage.local.set({ mess: ev.target.checked }));
  $("fade").addEventListener("change", (ev) => api.storage.local.set({ fade: ev.target.checked }));
  showPicks();
  showStatus();
  setTimeout(showStatus, 800);         // the first check may still be connecting
  setInterval(showStatus, 3000);
}

init();
