// Evaluate JS inside the app's WebView over the DevTools protocol (debug builds only).
// Usage: node cdp.mjs PORT "<js expression returning a value or promise>"   -> prints JSON result
const [port, expr] = process.argv.slice(2);
const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const t = targets.find((x) => x.type === 'page' && x.url.includes('appassets')) || targets[0];
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression: expr, awaitPromise: true, returnByValue: true } }));
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id !== 1) return;
  const r = d.result?.result;
  console.log(JSON.stringify(d.result?.exceptionDetails ? { error: d.result.exceptionDetails.text + ' ' + (d.result.exceptionDetails.exception?.description || '') } : r?.value ?? null));
  ws.close(); process.exit(0);
};
setTimeout(() => { console.log(JSON.stringify({ error: 'timeout' })); process.exit(1); }, 30000);
