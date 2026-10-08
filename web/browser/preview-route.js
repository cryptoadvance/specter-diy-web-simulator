/** Identify isolated Specter PR previews, including commit-specific URLs. */
export function isIsolatedPreviewRoute(pathname) {
  return /(?:^|\/)pr\/[1-9]\d*\/(?:[a-f0-9]{40}\/)?$/.test(pathname);
}
