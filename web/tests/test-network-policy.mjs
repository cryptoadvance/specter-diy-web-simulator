import assert from 'node:assert/strict';
import http from 'node:http';
import { chromium } from 'playwright';

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:8765/';
let hits = 0;
const endpoint = http.createServer((_req, res) => {
  hits++;
  res.writeHead(200, { 'Access-Control-Allow-Origin': '*' });
  res.end('unexpected');
});
await new Promise(resolve => endpoint.listen(0, '127.0.0.1', resolve));
const forbidden = `http://127.0.0.1:${endpoint.address().port}/collect`;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  const policy = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content');
  assert.match(policy, /connect-src 'self'/);
  assert.match(policy, /ws:\/\/127\.0\.0\.1:8788/);
  const result = await page.evaluate(url => new Promise(resolve => {
    const script = `fetch(${JSON.stringify(url)}).then(() => postMessage('allowed')).catch(() => postMessage('blocked'))`;
    const blobUrl = URL.createObjectURL(new Blob([script], { type: 'text/javascript' }));
    const worker = new Worker(blobUrl);
    worker.onmessage = event => {
      worker.terminate();
      URL.revokeObjectURL(blobUrl);
      resolve(event.data);
    };
    setTimeout(() => resolve('timeout'), 5000);
  }), forbidden);
  assert.equal(result, 'blocked');
  assert.equal(hits, 0, 'PR firmware worker attempted an outbound HTTP request');
  await page.close();
} finally {
  await browser.close();
  await new Promise(resolve => endpoint.close(resolve));
}
