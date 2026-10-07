// node scripts/cdp_eval.mjs <debug port> <target url substring> <js expression>
// Evaluates an expression in a Chrome DevTools target (used by web_perch_e2e.py).
const [port, sub, expr] = process.argv.slice(2);
const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const t = list.find((x) => x.url.includes(sub));
if (!t) { console.log("no target", list.map((x) => x.type + " " + x.url)); process.exit(1); }
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: expr, awaitPromise: true, returnByValue: true } }));
ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id === 1) { console.log(JSON.stringify(m.result.result.value ?? m.result)); process.exit(0); } });
