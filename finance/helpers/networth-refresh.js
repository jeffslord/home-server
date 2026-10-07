// "Refresh now" for the Grafana "Net worth" dashboard: GET /actual-refresh runs
// networth-export.js once and redirects back to the dashboard. Caddy routes the
// path on grafana.<domain> here, behind the same Authentik check as Grafana.
// Uses its own Actual cache dir so it never races the hourly Ofelia export;
// requests that arrive during a run wait for that run instead of starting another.
const http = require('http');
const { execFile } = require('child_process');

const PORT = 8080;
const DASHBOARD = '/d/actual-networth';
let running = null;

function runExport() {
  running ??= new Promise((resolve) => {
    execFile('node', ['networth-export.js'], { timeout: 120e3 }, (err, stdout, stderr) => {
      running = null;
      const out = `${stdout}${stderr}`.trim();
      console.log(`${new Date().toISOString()} export ${err ? 'FAILED' : 'ok'}\n${out}`);
      resolve({ ok: !err, out });
    });
  });
  return running;
}

http.createServer(async (req, res) => {
  if (req.method !== 'GET' || !req.url.startsWith('/actual-refresh')) {
    res.writeHead(404).end();
    return;
  }
  const { ok, out } = await runExport();
  if (ok) {
    res.writeHead(303, { Location: DASHBOARD }).end();
  } else {
    res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' })
      .end(`Net worth export failed:\n\n${out}\n`);
  }
}).listen(PORT, () => console.log(`listening on :${PORT}`));
