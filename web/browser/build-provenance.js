const repositoryPattern = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\/[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$/;
const commitPattern = /^[a-f0-9]{40}$/;

export function validateBuildProvenance(buildPath, source, variant, artifactSet, version) {
  if (typeof source.repository !== 'string' || !repositoryPattern.test(source.repository)) {
    throw new Error('Invalid source repository in build manifest');
  }
  if (typeof source.commit !== 'string' || !commitPattern.test(source.commit)) {
    throw new Error('Invalid source commit in build manifest');
  }
  if (buildPath !== `builds/${source.repository}/${source.commit}/` || artifactSet?.slice(0, 16) !== version) {
    throw new Error('Build manifest mismatch');
  }
  const project = source.repository.split('/')[1].toLowerCase();
  const expectedProject = variant === 'diy' ? 'specter-diy' : 'specter-playground';
  if (project !== expectedProject) throw new Error('Wrong firmware variant in build manifest');
}
