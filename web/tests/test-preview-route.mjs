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

const sourceCommit = 'b'.repeat(40);
const sourceRepository = 'schnuartz-ai/specter-diy';
const published = {
  schema: 1, pr_number: 440, base_repository: 'cryptoadvance/specter-diy',
  source_repository: sourceRepository, source_sha: sourceCommit,
};
const read = (path, repo = sourceRepository, commit = sourceCommit, provenance = published) =>
  getForkPreviewDetails(path, repo, commit, provenance);
const expected = {
  number: 440, repository: sourceRepository, commit: sourceCommit,
  isFork: true, commitMismatch: false, sourceMismatch: false,
};

assert.deepEqual(read(`/pr/440/${sourceCommit}/`), expected);
assert.deepEqual(read('/pr/440/'), expected, 'mutable PR paths are also recognized');

assert.deepEqual(read(`/pr/440/${sourceCommit}/`,
  'cryptoadvance/specter-diy', sourceCommit,
  { ...published, source_repository: 'cryptoadvance/specter-diy' }), {
  ...expected, repository: 'cryptoadvance/specter-diy', isFork: false,
}, 'same-owner PRs are hidden only with verified publisher data');

assert.deepEqual(read(`/pr/440/${sha}/`), { ...expected, commitMismatch: true },
  'a mismatched URL commit must preserve the warning');
assert.deepEqual(read(`/pr/440/${sourceCommit}/`, 'mallory/specter-diy'),
  { ...expected, sourceMismatch: true },
  'a build manifest must not override publisher-verified repository identity');
assert.deepEqual(read(`/pr/440/${sourceCommit}/`, sourceRepository, sha),
  { ...expected, sourceMismatch: true },
  'a build manifest must not override publisher-verified commit identity');

assert.equal(read(`/pr/440/${sourceCommit}/`, sourceRepository, sourceCommit, null), null,
  'missing publisher provenance is unverified');
assert.equal(read(`/pr/440/${sourceCommit}/`, sourceRepository, sourceCommit,
  { ...published, pr_number: 441 }), null,
  'the publisher PR number must match the URL');
assert.equal(read(`/pr/440/${sourceCommit}/`, sourceRepository, sourceCommit,
  { ...published, source_sha: 'invalid' }), null,
  'invalid publisher provenance must not be trusted');
assert.equal(read('/', sourceRepository, sourceCommit, published), null,
  'the normal firmware page does not use PR provenance');

console.log('Preview route and trusted fork provenance tests passed.');
