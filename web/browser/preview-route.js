const REPOSITORY_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const COMMIT_RE = /^[a-f0-9]{40}$/;

/** Parse isolated Specter PR preview URLs, including immutable commit routes. */
export function parsePreviewRoute(pathname) {
  if (typeof pathname !== 'string') return null;
  const match = pathname.match(/(?:^|\/)pr\/([1-9]\d*)\/(?:([a-f0-9]{40})\/)?$/);
  if (!match) return null;
  return { number: Number(match[1]), commit: match[2] || '' };
}

/** Only publisher-generated provenance may determine if a preview is a fork. */
export function getForkPreviewDetails(pathname, sourceRepository, sourceCommit, published) {
  const route = parsePreviewRoute(pathname);
  if (!route || !published || published.schema !== 1 ||
      !Number.isSafeInteger(published.pr_number) || published.pr_number !== route.number ||
      typeof published.base_repository !== 'string' || !REPOSITORY_RE.test(published.base_repository) ||
      typeof published.source_repository !== 'string' || !REPOSITORY_RE.test(published.source_repository) ||
      typeof published.source_sha !== 'string' || !COMMIT_RE.test(published.source_sha)) return null;

  const sourceOwner = published.source_repository.split('/')[0].toLowerCase();
  const baseOwner = published.base_repository.split('/')[0].toLowerCase();
  return {
    number: route.number, repository: published.source_repository, commit: published.source_sha,
    isFork: sourceOwner !== baseOwner,
    commitMismatch: Boolean(route.commit && route.commit !== published.source_sha),
    sourceMismatch: sourceRepository.toLowerCase() !== published.source_repository.toLowerCase() ||
      sourceCommit !== published.source_sha,
  };
}

/** Identify isolated Specter PR previews, including commit-specific URLs. */
export function isIsolatedPreviewRoute(pathname) {
  return parsePreviewRoute(pathname) !== null;
}
