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
finalizer uses the token of a dedicated **non-collaborator machine user** to
create or update a single marked bot-owned preview comment in place, including
a collapsible build-provenance section, firmware link, simulator link, and
strong test-only warning. No token is exposed to an untrusted PR build.
Paired forks can build previews without the upstream bot credential and
therefore skip automatic upstream comments. A separate fork-only account
and secret are needed when testing comment writing on fork PRs.

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
