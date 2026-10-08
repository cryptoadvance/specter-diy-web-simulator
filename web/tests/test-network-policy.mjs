import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import http from 'node:http';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(here, '..');
const toolsDir = resolve(webDir, 'tools');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const stableShell = await readFile(resolve(webDir, 'index.html'), 'utf8');
const previewShell = execFileSync(python, [
  '-c',
  'import sys; sys.path.insert(0, sys.argv[1]); from preview_csp import restrict_preview_csp; sys.stdout.write(restrict_preview_csp(sys.stdin.read()))',
  toolsDir,
], { input: stableShell, encoding: 'utf8' });

function policyFrom(html) {
  const match = html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/i);
  assert.ok(match, 'trusted shell must define a CSP meta policy');
  return match[1];
}

function policyPage(policy) {
  return `<!doctype html><meta http-equiv="Content-Security-Policy" content="${policy}"><title>Network policy test</title>`;
}

let externalHits = 0;
let websocketHandshakes = 0;
const external = http.createServer((_req, res) => {
  externalHits++;
  res.writeHead(200, { 'Access-Control-Allow-Origin': '*' });
  res.end('unexpected');
});
const websocket = http.createServer();
websocket.on('upgrade', (request, socket) => {
  const key = request.headers['sec-websocket-key'];
  if (typeof key !== 'string') {
    socket.destroy();
    return;
  }
  websocketHandshakes++;
  const accept = createHash('sha1')
    .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
    .digest('base64');
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
    'Upgrade: websocket\r\n' +
    'Connection: Upgrade\r\n' +
    `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  setTimeout(() => socket.destroy(), 250);
});
const site = http.createServer((request, response) => {
  response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  response.end(request.url === '/preview/'
    ? policyPage(policyFrom(previewShell))
    : policyPage(policyFrom(stableShell)));
});

const listen = (server, port = 0) => new Promise((resolveListen, reject) => {
  server.once('error', reject);
  server.listen(port, '127.0.0.1', () => {
    server.removeListener('error', reject);
    resolveListen(server.address().port);
  });
});
const close = server => new Promise(resolveClose => server.close(() => resolveClose()));

let browser;
try {
  const externalPort = await listen(external);
  await listen(websocket, 8788);
  const sitePort = await listen(site);
  const forbidden = `http://127.0.0.1:${externalPort}/collect`;
  browser = await chromium.launch({ headless: true });

  async function check(path) {
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${sitePort}${path}`, { waitUntil: 'domcontentloaded' });
    const script = `
        (async () => {
          let fetchResult;
          try { await fetch(${JSON.stringify(forbidden)}); fetchResult = 'fetch-allowed'; }
          catch { fetchResult = 'fetch-blocked'; }
          const socketResult = await new Promise(resolve => {
            const socket = new WebSocket('ws://127.0.0.1:8788');
            socket.onopen = () => { socket.close(); resolve('ws-allowed'); };
            socket.onerror = () => resolve('ws-blocked');
            setTimeout(() => resolve('ws-timeout'), 4000);
          });
          postMessage(fetchResult + ',' + socketResult);
        })().catch(() => postMessage('worker-error'));
      `;
    return page.evaluate(workerSource => new Promise(resolveResult => {
      const blobUrl = URL.createObjectURL(new Blob([workerSource], { type: 'text/javascript' }));
      const worker = new Worker(blobUrl);
      const timeout = setTimeout(() => finish('timeout'), 7000);
      function finish(result) {
        clearTimeout(timeout);
        worker.terminate();
        URL.revokeObjectURL(blobUrl);
        resolveResult(result);
      }
      worker.onmessage = event => finish(event.data);
    }), script).finally(() => page.close());
  }

  assert.equal(await check('/'), 'fetch-blocked,ws-allowed',
    'stable site must block external requests while allowing Virtual Host WebSocket');
  assert.equal(externalHits, 0, 'stable shell worker reached an external HTTP endpoint');
  assert.equal(websocketHandshakes, 1, 'stable shell did not open the Virtual Host WebSocket');

  assert.equal(await check('/preview/'), 'fetch-blocked,ws-blocked',
    'PR preview must block external requests and Virtual Host WebSocket');
  assert.equal(externalHits, 0, 'PR preview worker reached an external HTTP endpoint');
  assert.equal(websocketHandshakes, 1, 'PR preview opened the Virtual Host WebSocket');
} finally {
  if (browser) await browser.close();
  await Promise.all([close(site), close(websocket), close(external)]);
}
