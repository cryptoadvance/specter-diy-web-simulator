import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:8765/';
const browser = await chromium.launch(process.env.CI ? { headless: true } : { channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 900, height: 1100 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(() => {
  window.inspectorRequests = [];
  window.inspectorFiles = [{ path: '/state/flash/network', size: 4, hash: 'hash1' }];
  window.inspectorPhrase = 'fake abandon test phrase only';
  window.Worker = class extends EventTarget {
    constructor(url, options) { super(); this.url = String(url); this.options = options; }
    postMessage(message) {
      window.inspectorRequests.push(message);
      const reply = data => queueMicrotask(() => {
        const event = new MessageEvent('message', { data });
        this.onmessage?.(event);
        this.dispatchEvent(event);
      });
      if (message.type === 'start') setTimeout(() => reply({ type: 'running' }), 10);
      if (message.type === 'inspector-state') {
        const phrase = window.inspectorPhrase;
        reply({ type: 'inspector-state', requestId: message.requestId,
          files: message.includeFiles ? window.inspectorFiles.map(file => ({ ...file })) : null, memoryBytes: 65536,
          scannerActive: false, qrQueued: 0, sdInserted: false, cardSlot: null,
          firmware: { requestId: message.requestId, allocatedBytes: 1024, freeBytes: 2048,
            screen: 'test', keystore: 'FlashKeyStore',
            keystoreObjects: { 'keystore.mnemonic': { present: true } },
            apps: ['test-app'] },
          sensitiveValues: message.includeSensitive ? { 'keystore.mnemonic': phrase } : undefined });
      }
      if (message.type === 'inspector-file') reply({ type: 'inspector-file', requestId: message.requestId,
        path: message.path, size: 4, bytes: new TextEncoder().encode('test') });
      if (message.type === 'inspector-memory') reply({ type: 'inspector-memory', address: message.address,
        bytes: new TextEncoder().encode('ram') });
      if (message.type === 'snapshot') reply({ type: 'snapshot', requestId: message.requestId, files: [] });
    }
    terminate() {}
  };
});

const sourceCommit = 'a'.repeat(40);
const simulatorCommit = 'b'.repeat(40);
const version = '1234567890abcdef';
const build = `builds/cryptoadvance/specter-diy/${sourceCommit}/`;
const manifest = { source: { repository: 'cryptoadvance/specter-diy', commit: sourceCommit },
  simulator: { repository: 'cryptoadvance/specter-diy-web-simulator', commit: simulatorCommit },
  artifact_set_sha256: version + '0'.repeat(48), capabilities: { smartcard: true } };
await page.route('**/browser/current.json', route => route.fulfill({ json: { build, version } }));
await page.route('**/build-info.json', route => route.fulfill({ json: manifest }));
await page.goto(base, { waitUntil: 'domcontentloaded' });
try { await page.locator('#st').getByText('Running locally').waitFor({ timeout: 12000 }); }
catch (error) {
  console.error(JSON.stringify({ status: await page.locator('#st').textContent(), debug: await page.locator('#debug-log').textContent(), errors }, null, 2));
  throw error;
}

assert.equal(await page.locator('#advanced-options').isChecked(), false);
assert.equal(await page.locator('#developer-inspector').isVisible(), false);
assert.equal(await page.locator('#technical-details').isVisible(), false);
assert.equal(await page.evaluate(() => window.inspectorRequests.some(message => message.includeSensitive)), false);

await page.locator('#advanced-options').check();
await page.locator('#inspector-state').getByText('memoryBytes').waitFor();
assert.equal(await page.locator('#inspector-sensitive-values').isVisible(), false);
assert.equal((await page.locator('#inspector-state').textContent()).includes('fake abandon test phrase only'), false);
assert.equal((await page.locator('#inspector-objects').textContent()).includes('keystore.mnemonic'), true);

await page.locator('#inspector-files').selectOption('/state/flash/network');
await page.locator('#inspector-content').getByText('test', { exact: false }).waitFor();
await page.locator('#inspector-read-memory').click();
await page.locator('#inspector-memory').getByText('ram', { exact: false }).waitFor();

await page.locator('#inspector-sensitive-panel summary').click();
await page.locator('#inspector-read-sensitive').click();
await page.locator('#inspector-sensitive-values').getByText('fake abandon test phrase only').waitFor();
assert.equal(await page.evaluate(() => window.inspectorRequests.some(message => message.includeSensitive === true)), true);
assert.equal((await page.locator('#inspector-state').textContent()).includes('fake abandon test phrase only'), false);
await page.locator('#inspector-sensitive-panel summary').click();
await page.waitForFunction(() => document.querySelector('#inspector-sensitive-values').textContent === '');
assert.equal(await page.evaluate(() => window.inspectorRequests.some(message => message.type === 'inspector-hide-sensitive')), true);

await page.locator('#inspector-baseline').click();
await page.locator('#inspector-changes').getByText('Baseline captured').waitFor();
await page.locator('#inspector-compare').click();
await page.locator('#inspector-changes').getByText('No file or firmware-state changes detected.').waitFor();
await page.evaluate(() => { window.inspectorFiles[0].hash = 'hash2'; });
await page.locator('#inspector-compare').click();
await page.locator('#inspector-changes').getByText('Changed: /state/flash/network').waitFor();
assert.doesNotMatch(await page.locator('#inspector-changes').textContent(), /^firmware:/m,
  'A new firmware request ID must not look like a baseline change');

await page.locator('#technical-details summary').click();
assert.equal(await page.locator('#build-repository-link').isVisible(), true);
await page.locator('#technical-details summary').click();
await page.locator('#advanced-options').uncheck();
assert.equal(await page.locator('#developer-inspector').isVisible(), false);
for (const id of ['inspector-state', 'inspector-objects', 'inspector-content', 'inspector-memory', 'inspector-changes', 'inspector-sensitive-values']) {
  assert.equal(await page.locator(`#${id}`).textContent(), '', `${id} should be cleared when Developer Options are disabled`);
}
assert.equal(errors.length, 0, `Browser errors: ${errors.join('; ')}`);
console.log(JSON.stringify({ result: 'pass', defaultOff: true, privateValueOptIn: true,
  hideClearsOutput: true, fileRead: true, wasmMemoryRead: true, baselineComparison: true,
  technicalDetailsNested: true }, null, 2));
await browser.close();
