# Specter DIY Web Simulator

This repository owns the browser simulator and the complete pull request preview
service for Specter DIY. It builds the requested exact Specter source revision,
builds matching firmware, runs firmware and browser tests, validates the
resulting artifacts, hosts PR previews on this repository's GitHub Pages site,
and keeps preview status and lifecycle state.

Specter DIY only validates and dispatches PR metadata to this paired
repository, then exits; it does not wait for a build, edit PR comments, or host
the browser preview. The Web Simulator publishes the immutable preview and
public status JSON. For upstream `cryptoadvance/specter-diy` PRs, its trusted
finalizer uses a short-lived, repository-scoped GitHub App token to post a
fresh preview comment before deleting the previous App-owned comment. Paired
forks can build previews without the upstream App credential and therefore
skip automatic PR comments.

Start with [the manual build and setup guide](docs/browser-simulator.md). It
covers local builds, paired forks, the narrow dispatch token, Pages setup, and
the build/publisher security boundary.

The simulator runs the actual `src/` application from
[`cryptoadvance/specter-diy`](https://github.com/cryptoadvance/specter-diy);
this repository contains the browser shell, device shims, and build/test
tooling, not another wallet implementation. For desktop integration use the
[`cryptoadvance/specter-virtual-host`](https://github.com/cryptoadvance/specter-virtual-host)
bridge at the immutable revision documented in `.preview-config/`.

**Experimental development build. Never enter a real seed phrase or use real
funds.** A PR preview contains code produced from an untrusted PR and executes
in the visitor's browser.
