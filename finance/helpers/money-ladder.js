// Money Ladder: an interactive version of the r/personalfinance flowchart, fed
// from Actual. Served at grafana.<domain>/money-ladder via Caddy + Authentik.
//
//   GET /money-ladder              the page (money-ladder.html)
//   GET /money-ladder/api/data     snapshot of Actual (re-exported when older than
//                                  MAX_AGE, or always with ?refresh=1)
//   GET/PUT /money-ladder/api/config   settings Actual can't know (salary, 401k %,
//                                  APRs, ...), kept in /data/config.json
//
// The export runs money-ladder-export.js in a child process with its own Actual
// cache; concurrent requests share one run.
const http = require('http');
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');

const PORT = 8080;
const DATA = process.env.LADDER_DATA || '/data';
const SNAPSHOT = path.join(DATA, 'snapshot.json');
const CONFIG = path.join(DATA, 'config.json');
const PAGE = path.join(__dirname, 'money-ladder.html');
const MAX_AGE = 15 * 60e3;
let running = null;

function runExport() {
  running ??= new Promise((resolve) => {
    execFile('node', ['money-ladder-export.js'], { timeout: 180e3, env: { ...process.env, LADDER_SNAPSHOT: SNAPSHOT } },
      (err, stdout, stderr) => {
        running = null;
        const out = `${stdout}${stderr}`.trim().split('\n').slice(-20).join('\n');
        console.log(`${new Date().toISOString()} export ${err ? 'FAILED' : 'ok'}${err ? '\n' + out : ''}`);
        resolve(err ? out : null);
      });
  });
  return running;
}

const send = (res, code, body, type = 'application/json; charset=utf-8') =>
  res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store' }).end(body);

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (c) => { body += c; if (body.length > 1e5) req.destroy(); });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  try {
    if (req.method === 'GET' && (url.pathname === '/money-ladder' || url.pathname === '/money-ladder/')) {
      return send(res, 200, fs.readFileSync(PAGE), 'text/html; charset=utf-8');
    }
    if (req.method === 'GET' && url.pathname === '/money-ladder/api/data') {
      let age = Infinity;
      try { age = Date.now() - fs.statSync(SNAPSHOT).mtimeMs; } catch {}
      let error = null;
      if (url.searchParams.has('refresh') || age > MAX_AGE) error = await runExport();
      if (!fs.existsSync(SNAPSHOT)) return send(res, 502, JSON.stringify({ error: error || 'no snapshot' }));
      const snap = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8'));
      if (error) snap.exportError = error;   // serve the stale copy, but say so
      return send(res, 200, JSON.stringify(snap));
    }
    if (url.pathname === '/money-ladder/api/config') {
      if (req.method === 'GET') {
        return send(res, 200, fs.existsSync(CONFIG) ? fs.readFileSync(CONFIG) : '{}');
      }
      // JSON content type forces a CORS preflight, so other sites can't post here.
      if (req.method === 'PUT' && (req.headers['content-type'] || '').startsWith('application/json')) {
        const cfg = JSON.parse(await readBody(req));
        if (typeof cfg !== 'object' || Array.isArray(cfg) || !cfg) return send(res, 400, '{"error":"expected an object"}');
        fs.writeFileSync(CONFIG + '.tmp', JSON.stringify(cfg, null, 2));
        fs.renameSync(CONFIG + '.tmp', CONFIG);
        return send(res, 200, '{"ok":true}');
      }
    }
    send(res, 404, '{"error":"not found"}');
  } catch (e) {
    console.error(e);
    send(res, 500, JSON.stringify({ error: String(e.message || e) }));
  }
}).listen(PORT, () => console.log(`listening on :${PORT}`));
