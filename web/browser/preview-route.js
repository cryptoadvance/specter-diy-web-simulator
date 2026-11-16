const REPOSITORY_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const COMMIT_RE = /^[a-f0-9]{40}$/;

/** Parse isolated Specter PR preview URLs, including immutable commit routes. */
export function parsePreviewRoute(pathname) {
  if (typeof pathname !== 'string') return null;
  const match = pathname.match(/(?:^|\/)pr\/([1-9]\d*)\/(?:([a-f0-9]{40})\/)?$/);
  if (!match) return null;
  return { number: Number(match[1]), commit: match[2] || '' };
}

/** Identify a fork PR preview using the paired simulator's trusted repository owner. */
export function getForkPreviewDetails(pathname, sourceRepository, simulatorRepository, sourceCommit) {
  const route = parsePreviewRoute(pathname);
  if (!route || !REPOSITORY_RE.test(sourceRepository) ||
      !REPOSITORY_RE.test(simulatorRepository) || !COMMIT_RE.test(sourceCommit)) return null;

  const sourceOwner = sourceRepository.split('/')[0];
  // The paired-service validator requires the base repository to share this owner.
  const baseOwner = simulatorRepository.split('/')[0];
  if (sourceOwner.toLowerCase() === baseOwner.toLowerCase()) return null;
  if (route.commit && route.commit !== sourceCommit) return null;

  return { number: route.number, repository: sourceRepository, commit: sourceCommit };
}

/** Identify isolated Specter PR previews, including commit-specific URLs. */
export function isIsolatedPreviewRoute(pathname) {
  return parsePreviewRoute(pathname) !== null;
}
