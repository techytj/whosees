const net = require('net'), { spawn } = require('child_process'), readline = require('readline');
const token = 'tok' + Date.now();
const AGENT = 'C:\\wiretrace\\desktop\\agent\\target\\release\\whosees-agent.exe';
const srv = net.createServer((sock) => {
  const rl = readline.createInterface({ input: sock }); let n = 0, authed = false;
  rl.on('line', (l) => {
    if (!authed) { authed = l.trim() === token; console.log('token ok:', authed); if (!authed) sock.destroy(); return; }
    const e = JSON.parse(l); n++;
    if (e.t === 'hello') console.log('hello mode=' + e.mode);
    if (n === 6) { console.log('events received:', n, '-> sending stop'); sock.write('{"cmd":"stop"}\n'); sock.end(); }
  });
  sock.on('close', () => { console.log('agent disconnected'); srv.close(); process.exit(0); });
});
srv.listen(0, '127.0.0.1', () => {
  const args = ['--geo', 'C:\\wiretrace\\shared\\geo\\world.wtgeo', '--deep', '--connect', '127.0.0.1:' + srv.address().port, '--token', token].map((a) => `"${a}"`).join(' ');
  const ps = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', 'try { Start-Process -FilePath $env:WT_AGENT -ArgumentList $env:WT_ARGS -Verb RunAs -WindowStyle Hidden -ErrorAction Stop; exit 0 } catch { exit 126 }'], { env: { ...process.env, WT_AGENT: AGENT, WT_ARGS: args } });
  ps.on('exit', (c) => console.log('powershell exit', c));
});
setTimeout(() => { console.log('timeout'); process.exit(1); }, 30000).unref();
