import assert from 'node:assert/strict';
import net from 'node:net';
import { chromium } from 'playwright';

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:8765/';
const browser = await chromium.launch({ headless: true });
let host;
try {
  const page = await browser.newPage();
  const url = new URL(base);
  url.searchParams.set('virtual-host', '1');
  await page.goto(url.href, { waitUntil: 'domcontentloaded' });
  await page.locator('#virtual-host-bridge-status').getByText('Running', { exact: true })
    .waitFor({ timeout: 30000 });
  host = net.createConnection({ host: '127.0.0.1', port: 8789 });
  await new Promise((resolve, reject) => {
    host.once('connect', resolve);
    host.once('error', reject);
  });
  await page.locator('#virtual-host-wallet-status').getByText('Connected', { exact: true })
    .waitFor({ timeout: 10000 });

  // Unknown protocol bytes must pass unchanged in both directions.
  const outbound = Buffer.from([0, 255, 129, 66, 0, 17]);
  const receivedByHost = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Virtual Host received no binary frame')), 10000);
    host.once('data', data => { clearTimeout(timer); resolve(data); });
  });
  await page.evaluate(bytes => dispatchEvent(new CustomEvent('specter-virtual-host-send',
    { detail: Uint8Array.from(bytes) })), [...outbound]);
  assert.deepEqual(await receivedByHost, outbound);

  const inbound = Buffer.from([254, 1, 0, 128, 35]);
  await page.evaluate(() => {
    window.__usbFrames = [];
    addEventListener('specter-virtual-host-frame', event => {
      window.__usbFrames.push([...event.detail]);
    });
  });
  host.write(inbound);
  await page.waitForFunction(() => window.__usbFrames.length > 0, null, { timeout: 10000 });
  assert.deepEqual(await page.evaluate(() => window.__usbFrames[0]), [...inbound]);
  await page.close();
} finally {
  host?.destroy();
  await browser.close();
}
