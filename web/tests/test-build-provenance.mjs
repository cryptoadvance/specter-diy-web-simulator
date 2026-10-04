import assert from 'node:assert/strict';
import { validateBuildProvenance } from '../browser/build-provenance.js';

const commit = 'a'.repeat(40);
const artifactSet = 'b'.repeat(64);
const version = artifactSet.slice(0, 16);
const validate = (repository, variant = 'diy', pathRepository = repository, pathCommit = commit) =>
  validateBuildProvenance(`builds/${pathRepository}/${pathCommit}/`, { repository, commit },
    variant, artifactSet, version);

assert.doesNotThrow(() => validate('cryptoadvance/specter-diy'));
assert.doesNotThrow(() => validate('Schnuartz/specter-diy'));
assert.doesNotThrow(() => validate('randomcontributor/specter-diy'));
assert.throws(() => validate('randomcontributor'), /Invalid source repository/);
assert.throws(() => validate('random contributor/specter-diy'), /Invalid source repository/);
assert.throws(() => validate('../specter-diy'), /Invalid source repository/);
assert.throws(() => validate('randomcontributor/specter-diy', 'diy', 'someone-else/specter-diy'), /Build manifest mismatch/);
assert.throws(() => validate('randomcontributor/specter-diy', 'diy', 'randomcontributor/specter-diy', 'c'.repeat(40)), /Build manifest mismatch/);
assert.throws(() => validateBuildProvenance(
  `builds/randomcontributor/specter-diy/${commit.slice(1)}/`,
  { repository: 'randomcontributor/specter-diy', commit: commit.slice(1) },
  'diy', artifactSet, version), /Invalid source commit/);
assert.throws(() => validate('cryptoadvance/specter-playground'), /Wrong firmware variant/);
assert.throws(() => validate('k9ert/specter-playground', 'play', 'cryptoadvance/specter-diy'), /Build manifest mismatch/);
assert.doesNotThrow(() => validate('k9ert/specter-playground', 'play'));

console.log('Browser build provenance tests passed');
