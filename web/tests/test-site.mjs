import { chromium } from 'playwright';
import { PNG } from 'pngjs';
import { readFile, mkdir } from 'node:fs/promises';

const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:8765/';
await mkdir('test-results', { recursive: true });
const browser = await chromium.launch(process.env.CI ? { headless: true } : { channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 850, height: 1000 }, acceptDownloads: true });
const requests = [];
const errors = [];
page.on('request', request => requests.push(request.url()));
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(() => {
  window.inspectorMessages = [];
  const NativeWorker = window.Worker;
  window.Worker = class extends NativeWorker {
    postMessage(message, transfer) {
      if (typeof message?.type === 'string' && message.type.startsWith('inspector-')) {
        window.inspectorMessages.push({ type: message.type, enabled: message.enabled });
      }
      return super.postMessage(message, transfer);
    }
  };
});
await page.goto(base, { waitUntil: 'domcontentloaded' });
try { await page.locator('#st').getByText('Running locally').waitFor({ timeout: 45000 }); }
catch (error) {
  console.error(JSON.stringify({ status: await page.locator('#st').textContent(),
    debug: await page.locator('#debug-log').textContent(), errors,
    requests: requests.filter(url => /current\.json|build-info|micropython|browser\.js/.test(url)) }, null, 2));
  throw error;
}
// The under-device source link must identify the exact firmware revision,
// including on PR preview builds that have no optional PR metadata.
const underDevice = await page.evaluate(async () => {
  const pointer = await (await fetch(new URL('browser/current.json', location.href))).json();
  const build = await (await fetch(new URL(pointer.build + 'build-info.json', location.href))).json();
  const link = document.querySelector('#source-commit-link');
  return { label: link?.textContent, href: link?.href,
    repository: build.source.repository, commit: build.source.commit,
    version: build.firmware_version };
});
const expectedUnderDeviceVersion = underDevice.version ? `v${underDevice.version.replace(/^v/i, '')} · ` : '';
const expectedUnderDeviceRevision = `${expectedUnderDeviceVersion}${underDevice.commit.slice(0, 7)}`;
if (!underDevice.label?.includes(expectedUnderDeviceRevision) ||
    !underDevice.label.startsWith('GitHub · ') ||
    underDevice.href !== `https://github.com/${underDevice.repository}/commit/${underDevice.commit}`) {
  throw new Error(`Incorrect under-device firmware provenance footer: ${JSON.stringify(underDevice)}`);
}
if (await page.locator('#advanced-options').isChecked() || await page.locator('#developer-inspector').isVisible()) {
  throw new Error('Developer Options must be off by default');
}
await page.waitForTimeout(300);
if (await page.evaluate(() => window.inspectorMessages.length)) {
  throw new Error('The normal firmware boot must not start the Developer Options inspector');
}
await page.locator('#advanced-options').check();
await page.waitForFunction(() => {
  const text = document.querySelector('#inspector-state').textContent;
  try { return Boolean(JSON.parse(text).firmware?.keystoreObjects); } catch { return false; }
}, null, { timeout: 20000 });
const keystoreObjects = JSON.parse(await page.locator('#inspector-objects').textContent());
for (const name of ['keystore.mnemonic', 'keystore.root', 'keystore.enc_secret', 'bip39_seed']) {
  if (!(name in keystoreObjects)) throw new Error(`Runtime RAM inspection omitted ${name}`);
}
await page.locator('#inspector-baseline').click();
await page.locator('#inspector-changes').getByText('Baseline captured').waitFor();
const capturedBaseline = await page.locator('#inspector-changes').textContent();
await page.locator('#inspector-compare').click();
await page.waitForFunction(previous => document.querySelector('#inspector-changes').textContent !== previous,
  capturedBaseline);
const firmwareComparison = await page.locator('#inspector-changes').textContent();
if (/requestId/i.test(firmwareComparison)) {
  throw new Error(`A per-request firmware ID must not appear as a baseline change: ${firmwareComparison}`);
}
if (!await page.evaluate(() => window.inspectorMessages.some(message =>
  message.type === 'inspector-enable' && message.enabled === true))) {
  throw new Error('Enabling Developer Options did not activate the live firmware inspector');
}
if (await page.locator('#inspector-sensitive-values').isVisible()) {
  throw new Error('Sensitive keystore values must stay hidden until explicitly requested');
}
await page.locator('#advanced-options').uncheck();
if (await page.locator('#inspector-state').textContent() || await page.locator('#inspector-objects').textContent()) {
  throw new Error('Disabling Developer Options did not clear inspector output');
}
if (!await page.evaluate(() => window.inspectorMessages.some(message =>
  message.type === 'inspector-enable' && message.enabled === false))) {
  throw new Error('Disabling Developer Options did not stop the live firmware inspector');
}
if (!await page.locator('.phone-mockup').evaluate(img => img.complete && img.naturalWidth > 0)) {
  throw new Error('Specter Shield Metal device image did not load');
}
const isolated = await page.evaluate(() => crossOriginIsolated);
// GitHub Pages cannot set COOP/COEP; this build does not require SharedArrayBuffer.
const canvas = page.locator('#screen');
const before = await canvas.screenshot({ path: 'test-results/specter-screen.png' });
const png = PNG.sync.read(before);
const colors = new Set();
for (let i = 0; i < png.data.length; i += 4) {
  colors.add(`${png.data[i]},${png.data[i + 1]},${png.data[i + 2]}`);
}
if (colors.size < 12) throw new Error(`Specter canvas has only ${colors.size} colors`);
const box = await canvas.boundingBox();
await page.mouse.click(box.x + box.width * 0.17, box.y + box.height * 0.35);
await page.waitForTimeout(700);
const after = await canvas.screenshot();
if (before.equals(after)) throw new Error('Pointer input did not change the Specter screen');

await page.locator('#sd-toggle').click();
await page.locator('#sd-state').getByText('Inserted').waitFor();
await page.locator('#sd-picker').setInputFiles([
  { name: 'probe.bin', mimeType: 'application/octet-stream', buffer: Buffer.from([0, 1, 2, 255]) },
  { name: 'second.txt', mimeType: 'text/plain', buffer: Buffer.from('second file') },
]);
await page.locator('#sd-files').getByText('probe.bin', { exact: false }).waitFor();
await page.locator('#sd-files').getByText('second.txt', { exact: false }).waitFor();
await page.evaluate(() => {
  const clipboard = new DataTransfer();
  clipboard.items.add(new File(['pasted one'], 'pasted-one.txt', { type: 'text/plain' }));
  clipboard.items.add(new File(['pasted two'], 'pasted-two.txt', { type: 'text/plain' }));
  dispatchEvent(new ClipboardEvent('paste', { clipboardData: clipboard, bubbles: true, cancelable: true }));
});
await page.locator('#sd-files').getByText('pasted-one.txt', { exact: false }).waitFor();
await page.locator('#sd-files').getByText('pasted-two.txt', { exact: false }).waitFor();
const probeDownload = page.locator('#sd-files li').filter({ hasText: 'probe.bin' })
  .getByRole('button', { name: 'Download', exact: true });
const downloadPromise = page.waitForEvent('download');
await probeDownload.click();
const download = await downloadPromise;
if (!(await readFile(await download.path())).equals(Buffer.from([0, 1, 2, 255]))) {
  throw new Error('Virtual SD export bytes differ from imported bytes');
}

const previousCanvas = await canvas.elementHandle();
const beforeRestartMessages = await page.evaluate(() => window.inspectorMessages.length);
await page.locator('#restart-btn').click();
await page.waitForFunction(previous => document.querySelector('#screen') !== previous,
  previousCanvas, { timeout: 10000 });
await page.locator('#st').getByText('Running locally').waitFor({ timeout: 45000 });
await previousCanvas.dispose();
if (await page.evaluate(count => window.inspectorMessages.slice(count).length, beforeRestartMessages)) {
  throw new Error('A normal simulator restart must not reactivate Developer Options');
}
await page.locator('#sd-state').getByText('Inserted').waitFor();
await page.locator('#sd-files').getByText('probe.bin', { exact: false }).waitFor();
await canvas.screenshot({ path: 'test-results/specter-after-restart.png' });
await page.locator('#sd-toggle').click();
await page.locator('#sd-state').getByText('Ejected').waitFor();
const actionOrder = await page.locator('#sd-add, #sd-clear, #demo-network').evaluateAll(elements =>
  elements.map(element => ({ id: element.id, rect: element.getBoundingClientRect().toJSON() })));
if (actionOrder.map(item => item.id).join('|') !== 'sd-add|sd-clear|demo-network' ||
    actionOrder.some(item => Math.abs(item.rect.y - actionOrder[0].rect.y) > 2)) {
  throw new Error('Demo selector is not alongside Add files and Clear card');
}
await page.evaluate(() => {
  window.__demoCardInsertMessages = [];
  const postMessage = Worker.prototype.postMessage;
  Worker.prototype.postMessage = function (message, transfer) {
    if (message?.type === 'card-insert') window.__demoCardInsertMessages.push(message.slot);
    return postMessage.call(this, message, transfer);
  };
});
await page.locator('#demo-network').selectOption('testnet');
await page.locator('#demo-network:not(:disabled)').waitFor({ timeout: 30000 });
await page.locator('#sd-state').getByText('Inserted').waitFor();
await page.locator('#sd-files').getByText('testnet-multisig-unsigned.psbt', { exact: false }).waitFor();
if (await page.locator('#card-slots > div').first().locator('.card-status').isVisible()) {
  throw new Error('Selecting Testnet automatically inserted a Smartcard');
}
await page.locator('#card-slots > div').first().getByText('ghost-seed', { exact: false }).waitFor();
await page.locator('#demo-network').selectOption('mainnet');
await page.locator('#demo-network:not(:disabled)').waitFor({ timeout: 30000 });
await page.locator('#sd-files').getByText('mainnet-ghost-payment-high-fee.psbt', { exact: false }).waitFor();
await page.locator('#sd-files').getByText('mainnet-ghost-wallet.json', { exact: false }).waitFor();
if (await page.locator('#sd-files').getByText('testnet-ghost-payment-high-fee.psbt', { exact: false }).count()) {
  throw new Error('Switching to Mainnet kept stale Testnet transactions');
}
if (await page.locator('#demo-network').evaluate(select => select.title).then(title => !title.includes('Never send or store real funds'))) {
  throw new Error('Mainnet demo safety tooltip is missing');
}
await page.locator('#demo-network').selectOption('');
await page.locator('#demo-network:not(:disabled)').waitFor({ timeout: 30000 });
for (const name of ['01-ghost-PUBLIC-MAINNET-DEMO-SEED.txt', 'mainnet-ghost-payment-high-fee.psbt',
  'testnet-multisig-unsigned.psbt']) {
  if (await page.locator('#sd-files').getByText(name, { exact: false }).count()) {
    throw new Error(`Selecting None kept demo file ${name}`);
  }
}
if (!await page.locator('#sd-files').getByText('probe.bin', { exact: false }).count()) {
  throw new Error('Selecting None removed unrelated SD data');
}
if (await page.locator('#sd-toggle').getAttribute('aria-pressed') !== 'false') {
  throw new Error('Selecting None did not restore the SD card ejected state');
}
if (await page.locator('#card-slots .card-details').count()) {
  throw new Error('Selecting None kept demo Smartcard seeds');
}
for (let slot = 0; slot < 2; slot++) {
  const label = await page.locator('#card-slots > div').nth(slot).locator('.smartcard-graphic')
    .getAttribute('aria-label');
  if (!label?.includes('Not inserted')) throw new Error(`Selecting None left Smartcard ${slot + 1} inserted`);
}
if (await page.evaluate(() => window.__demoCardInsertMessages.length)) {
  throw new Error('Demo selection automatically inserted a Smartcard');
}
if (await page.locator('.smartcard-photo').count() !== 3 ||
    !await page.locator('.smartcard-photo').first().evaluate(img => img.complete && img.naturalWidth > 0)) {
  throw new Error('Smartcard artwork did not load');
}
if (await page.locator('.hardware-link').count()) throw new Error('Removed hardware purchase note is still present');
if (await page.locator('#camera-toggle').isVisible()) throw new Error('Backup camera control should stay hidden');
if (requests.some(url => /\/api\/(allocate|heartbeat)|\/novnc\//.test(url))) {
  throw new Error('Browser mode requested legacy VNC/session infrastructure');
}
if (errors.length) throw new Error(`Browser errors: ${errors.join('; ')}`);

const probe = await page.evaluate(async () => {
  const { build: relativeBuild, version } = await (await fetch(new URL('browser/current.json', location.href))).json();
  const build = new URL(relativeBuild, location.href).href;
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('browser/runtime-worker.js', location.href));
    const canvas = new OffscreenCanvas(480, 800);
    const logs = [];
    const timer = setTimeout(() => { worker.terminate(); reject(new Error(logs.join('\n'))); }, 10000);
    worker.onmessage = ({ data }) => {
      if (data.type === 'log') logs.push(data.message);
      if (data.type === 'abort') { clearTimeout(timer); worker.terminate(); reject(new Error(data.message)); }
      if (data.type === 'log' && data.message === 'SD_PROBE_WRITTEN') {
        worker.postMessage({ type: 'snapshot', requestId: 1 });
      }
      if (data.type === 'snapshot') {
        const file = data.files.find(file => file.path === 'sd/written-by-specter.txt');
        clearTimeout(timer); worker.terminate();
        resolve({ logs, written: file ? new TextDecoder().decode(file.bytes) : null });
      }
    };
    worker.onerror = error => { clearTimeout(timer); worker.terminate(); reject(new Error(error.message)); };
    worker.postMessage({ type: 'start', build, version, canvas, sdInserted: true, sdProbe: true,
      stateFiles: [{ path: 'sd/probe.bin', bytes: new Uint8Array([0, 1, 2, 255]) }] }, [canvas]);
  });
});
if (!probe.logs.includes('SD_PROBE_PRESENT True') ||
    !probe.logs.some(line => line.includes("b'\\x00\\x01\\x02\\xff'")) ||
    probe.written !== 'firmware-created file') {
  throw new Error(`Specter SD platform read/write failed: ${probe.logs.join('; ')}`);
}

const crashPage = await browser.newPage();
await crashPage.route('**/browser/runtime-worker.js*', route => route.abort());
await crashPage.goto(base);
await crashPage.locator('#st').getByText('Simulator error').waitFor({ timeout: 15000 });
await crashPage.close();

const mobile = await browser.newContext({ viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const mobilePage = await mobile.newPage();
await mobilePage.goto(base);
await mobilePage.locator('#st').getByText('Running locally').waitFor({ timeout: 45000 });
const mobileCanvas = mobilePage.locator('#screen');
const mobileBefore = await mobileCanvas.screenshot();
const mobileBox = await mobileCanvas.boundingBox();
await mobilePage.touchscreen.tap(mobileBox.x + mobileBox.width * 0.17,
  mobileBox.y + mobileBox.height * 0.35);
await mobilePage.waitForTimeout(700);
if (mobileBefore.equals(await mobileCanvas.screenshot())) {
  throw new Error('Scaled mobile touch did not reach Specter');
}
await mobile.close();

if (await page.locator('img[alt="ClavaStack"]').count() ||
    (await page.title()).includes('ClavaStack') ||
    !await page.locator('a[href="https://github.com/cryptoadvance/specter-diy"]').count() ||
    await page.locator('a[href="http://127.0.0.1:8788/settings"]').count() ||
    await page.getByText('Use public test seeds only', { exact: false }).count()) {
  throw new Error('Fork page branding or source link is incorrect');
}
console.log(JSON.stringify({ result: 'pass', canvasColors: colors.size,
  crossOriginIsolated: isolated,
  pointer: 'changed Specter screen', sd: 'multi-select/paste/export/restart/Specter platform read+write',
  mobileTouch: 'changed Specter screen', demo: 'files and Smartcards imported',
  workerCrash: 'handled', branding: 'Specter DIY',
  legacyRequestsInBrowserMode: 0 }, null, 2));
await browser.close();
