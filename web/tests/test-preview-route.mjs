import assert from 'node:assert/strict';
import { isIsolatedPreviewRoute } from '../browser/preview-route.js';

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
console.log('Preview route isolation tests passed.');
