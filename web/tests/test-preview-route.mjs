import assert from 'node:assert/strict';
import { getForkPreviewDetails, isIsolatedPreviewRoute } from '../browser/preview-route.js';

const sha = 'a'.repeat(40);
for (const path of [
  '/pr/4/', `/pr/4/${sha}/`, '/specter-diy-web-simulator/pr/11/',
  `/specter-diy-web-simulator/pr/11/${sha}/`,
]) {
  assert.equal(isIsolatedPreviewRoute(path), true, `Expected isolated preview: ${path}`);
}
for (const path of [
  '/', '/pr/0/', '/pr/4/not-a-sha/', '/pr/4/abc/',
  `/pr/4/${sha}/extra/`, '/pr/4', '/something/pr/4/another',
]) {
  assert.equal(isIsolatedPreviewRoute(path), false, `Unexpected isolated preview: ${path}`);
}

const simulatorRepository = 'cryptoadvance/specter-diy-web-simulator';
const sourceCommit = 'b'.repeat(40);
assert.deepEqual(getForkPreviewDetails(`/pr/440/${sourceCommit}/`,
  'schnuartz-ai/specter-diy', simulatorRepository, sourceCommit), {
  number: 440, repository: 'schnuartz-ai/specter-diy', commit: sourceCommit,
  commitMismatch: false,
});
assert.equal(getForkPreviewDetails(`/pr/440/${sourceCommit}/`,
  'cryptoadvance/specter-diy', simulatorRepository, sourceCommit), null,
'same-owner PR previews from cryptoadvance must not be labeled as forks');
assert.equal(getForkPreviewDetails('/', 'schnuartz-ai/specter-diy',
  simulatorRepository, sourceCommit), null,
'the normal firmware page must not show a fork preview warning');
assert.deepEqual(getForkPreviewDetails(`/pr/440/${sha}/`, 'schnuartz-ai/specter-diy',
  simulatorRepository, sourceCommit), {
  number: 440, repository: 'schnuartz-ai/specter-diy', commit: sourceCommit,
  commitMismatch: true,
}, 'a preview with a mismatched URL commit must retain its fork warning');

console.log('Preview route and fork warning tests passed.');
