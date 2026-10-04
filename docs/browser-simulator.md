# Browser simulator and PR preview service

The browser simulator runs the actual Specter DIY `src/` application under
MicroPython compiled to WebAssembly with Emscripten 3.1.74. This repository
provides the browser shell, simulated peripherals, build scripts, and tests; it
does not contain a second wallet implementation.

```text
specter-diy PR event
  └─ trusted dispatcher ── workflow_dispatch + exact PR metadata ──┐
                                                                  ▼
                                              specter-diy-web-simulator
                                                ├─ validate live PR
                                                ├─ untrusted runner: firmware + WASM/data + tests
                                                ├─ fresh trusted runner: JS from exact base SHA
                                                ├─ finalizer: validate and combine artifacts
                                                ├─ update Pages preview + state
                                                └─ publish status/pr/<N>.json
                                                                  │
                           Specter polls status + updates one PR comment ◀─┘
```

The official preview for PR 45 is hosted by this repository at
`https://cryptoadvance.github.io/specter-diy-web-simulator/pr/45/`. A paired
fork uses the matching owner, for example
`https://alice.github.io/specter-diy-web-simulator/pr/12/`.

**Experimental development build. Never enter a real seed phrase or use real
funds.** The firmware and browser build are not official releases. A preview
executes code from an untrusted PR in the visitor's browser.

## Manual build

Choose both a source repository and its exact full commit SHA. For a contributor
PR, use the contributor's source repository and the PR head SHA; the base
repository still determines which paired Web Simulator receives CI requests.

```sh
git clone https://github.com/bob/specter-diy.git
git -C specter-diy checkout --detach <40-character-source-sha>
git clone https://github.com/cryptoadvance/specter-diy-web-simulator.git
```

Install the native packages used by Specter, Nix, Python 3.11, Node.js 22, Go
1.22, and Emscripten 3.1.74. CI checks out the emsdk installer at the immutable
commit in `.preview-config/emsdk-commit`, then installs Emscripten 3.1.74 from
that pinned installer. From Linux or WSL:

```sh
sudo apt-get install build-essential libffi-dev libgmp-dev libreadline-dev \
  libsdl2-dev pkg-config python3
nix develop -c make disco
```

Build the browser simulator from the same checked-out Specter SHA:

```sh
SPECTER_SRC="$PWD/specter-diy" \
SPECTER_SOURCE_REPOSITORY="bob/specter-diy" \
SIMULATOR_REPOSITORY="cryptoadvance/specter-diy-web-simulator" \
SIMULATOR_COMMIT="$(git -C specter-diy-web-simulator rev-parse HEAD)" \
bash specter-diy-web-simulator/web/browser/build-browser.sh
```

The firmware is written to `specter-diy/bin/`. The browser files are written
under `specter-diy-web-simulator/web/builds/<owner>/<repo>/<source-sha>/` and
the current-build pointer is `web/browser/current.json`. The browser manifest
records the source repository/SHA, simulator repository/SHA, toolchain, and
SHA256 and size for each generated file.

Run the firmware and browser tests used by CI:

```sh
python3 -m pip install -r specter-diy/requirements.txt \
  -r specter-diy/test/integration/requirements.txt
python3 specter-diy/test/run_native_tests.py
make -C specter-diy test
npm ci --prefix specter-diy-web-simulator/web
npx --prefix specter-diy-web-simulator/web playwright install chromium
```

Start the static site from the Web Simulator repository and run the browser
checks from another terminal:

```sh
cd specter-diy-web-simulator/web
python3 -m http.server 8765
```

```sh
cd specter-diy-web-simulator/web
CI=true npm run test:browser
npm run test:provenance
node tests/test-network-policy.mjs
python3 tests/test-usb-vcp.py
```

For Virtual Host compatibility, use the exact commit in
`.preview-config/virtual-host-commit`, then run its Go tests and the browser USB
transport test:

```sh
git clone https://github.com/cryptoadvance/specter-virtual-host.git
git -C specter-virtual-host checkout --detach \
  "$(cat specter-diy-web-simulator/.preview-config/virtual-host-commit)"
(cd specter-virtual-host && go test ./...)
(cd specter-virtual-host && go run . --site http://127.0.0.1:8765 --no-open)
```

In another terminal, run `node tests/test-usb-transport.mjs` from the Web
Simulator `web/` directory. The required CI checkouts use the immutable
revision recorded in `.preview-config/virtual-host-commit`; they never use the
moving `main` branch. To update the pin, review a specific Virtual Host commit,
change both the pin file and the workflow's checkout SHA, then run the full
USB VCP and USB transport checks.

## Set up paired forks

Fork **both** repositories under the same GitHub account or organization:

1. Fork `cryptoadvance/specter-diy`.
2. Fork `cryptoadvance/specter-diy-web-simulator` under the same owner.
3. Enable GitHub Actions in both forks.
4. In the Web Simulator fork, set **Settings → Pages → Build and deployment →
   Source: GitHub Actions**.
5. Create a fine-grained personal access token. Choose the same resource owner,
   grant repository access to **only** `<owner>/specter-diy-web-simulator`, and
   grant **Actions: Read and write**. It does not need Contents, Administration,
   Issues, or Pull requests permissions.
6. Save the token in the Specter DIY fork as the Actions secret
   `WEB_SIMULATOR_DISPATCH_TOKEN`.

The default pairing is `${github.repository_owner}/specter-diy-web-simulator`.
If the paired service uses another repository name, set the Actions variable
`WEB_SIMULATOR_REPOSITORY` in the Specter DIY repository to `owner/repository`.
The PR source repository can still be a contributor fork; the paired service is
selected from the PR's base repository owner.

An organization that prefers GitHub Apps can replace the fine-grained PAT with
an installation token limited to the same single Web Simulator repository and
the ability to dispatch Actions workflows. A custom GitHub App is not required
for the basic setup.

## Request validation and lifecycle

Specter DIY's `pull_request_target` workflow handles PR open, synchronize,
reopen, ready-for-review, and close events. Same-repository and fork PRs both
start automatically after the dispatcher verifies the current PR and exact
head SHA. Closing a PR always dispatches cleanup. The workflow reads only
trusted event metadata and a script checked out from the protected default
branch; it does not check out or execute PR code. It dispatches a unique request
ID, base repository and exact base SHA/ref, head repository, PR number, exact
head SHA/ref, action, and source `updated_at`. Closing a PR sends
`action=delete`.

The dispatcher polls for up to 210 minutes. This covers the paired service's
5-minute validation, 180-minute build, and 10-minute finalizer, with a short
buffer; the caller workflow allows 240 minutes. The service cancels an older
build for the same PR when a newer request arrives, and its persistent state
prevents a stale finalizer from replacing a newer result.

This workflow uses `pull_request_target`. Repository or organization Actions
policy must permit that event for public repositories. A repository or
organization administrator should verify the policy before GitHub's announced
November 2, 2026 enforcement date.

The Web Simulator validates the paired base repository and compares the request
to the live GitHub PR before building. Build requests must match an open PR's
base, head repository, branch, number, and exact SHA. The source checkout is by
SHA, including submodules. The caller polls the public status JSON and accepts
only a matching request ID, PR number, and source SHA. It uses its own local
`GITHUB_TOKEN` to update one comment; this service never receives a credential
that can modify Specter DIY.

The service uses its workflow token with `pull-requests: read` to validate the
live PR. Published PR pages receive a stricter copy of the trusted shell's
Content Security Policy: `connect-src 'self'`. This blocks external network
requests and the local Virtual Host WebSocket from PR previews. The stable
simulator keeps the local Virtual Host allowance. Browser tests exercise both
policies.

Several PR previews coexist in `/pr/<N>/`. The trusted publisher serializes
updates and keeps `.preview-state/pr/<N>.json` on its persistent `gh-pages`
branch separately from the public preview. The state records the latest source
timestamp, SHA, request, action, and result. Older requests and late builds
cannot replace a newer preview. A close event removes the preview but leaves a
tombstone. A failed or cancelled build for the current source removes the old
executable preview and publishes a failure status instead of leaving an older
commit looking current. Every accepted request publishes
`status/pr/<N>.json` through GitHub Pages.

The untrusted job builds firmware and WebAssembly from the exact PR head SHA.
Its browser archive contains only `micropython.wasm` and `micropython.data`;
the PR-generated `micropython.js` is checked locally during that job but is
never included in the artifact. A separate fresh runner checks out the exact
live PR base SHA and trusted Web Simulator tooling, builds the browser runtime,
and uploads only `micropython.js` with its provenance. The trusted finalizer
checks both artifacts, binds them to the live base/head SHAs, then combines the
trusted JavaScript with the validated PR WebAssembly/data. It checks exact file
allowlists, paths, file types, hashes, manifests, and provenance; safe
extraction rejects traversal, absolute paths, symlinks, executables, malformed
archives, and unexpected files. Artifact contents are never executed during
publication. The final JavaScript and WebAssembly are loaded by the visitor's
browser as the preview.

## Security boundary and trade-off

The untrusted build job assumes the Specter PR controls all source, Makefiles,
Python, submodules, tests, generated files, and build artifacts. It has only
`contents: read`, no repository secrets, no Pages or Contents write permission,
and no `id-token: write`. PR-controlled code cannot read the dispatch token or
the Specter PR-comment token.

The trusted runtime job uses a separate fresh runner, has only `contents: read`,
and never checks out the PR head. It builds JavaScript from the validated base
commit and trusted Web Simulator code. The finalizer alone receives
`contents: write`, `pages: write`, and `id-token: write`, plus read access to
the workflow artifacts and PR metadata. It parses both artifacts as files and
publishes only the allowlisted WASM/data and trusted runtime JavaScript with
the default-branch shell. It does not run scripts, Python, or JavaScript from
an artifact. The `gh-pages` branch is the persistent complete tree; GitHub
Pages deploys it from a Pages artifact created by the trusted finalizer.

This makes the Web Simulator default branch a stronger trust root: a malicious
change merged there could publish deceptive previews, serve malicious browser
code, or report false test results. That service intentionally has no reverse
credential for Specter DIY, so its compromise does not grant access to Specter
PR comments or repository contents. Review Web Simulator changes with that
trust trade-off in mind.

The preview workflow pins third-party actions to immutable commit SHAs. Existing
general-purpose repository checks continue their established version-tag
convention. GitHub App tokens are an optional organization preference; there
is no custom server, database, callback credential, or second wallet logic
implementation.

## Developer Options

The optional **Developer Options** panel inspects browser simulator state, flash
and peripheral files, and the WebAssembly memory buffer. At normal startup its
firmware hook only retains the active device reference; it creates no inspector
task and performs no memory or filesystem reads. Enabling Developer Options
starts the inspector task, and disabling it cancels that task and clears pending
requests and displayed state. Firmware metadata reports only whether
`keystore.mnemonic` is present. It does not tokenize or encode the phrase; the
mnemonic value is read and transferred only after the explicit **Read mnemonic
from RAM** action. Closing the sensitive-values panel or disabling Developer
Options clears the displayed value and its temporary worker-side copy. This is a
debugging view into the browser build, not hardware RAM, and it must only be used
with public test phrases.

CI runs both the mocked inspector UI test and an integration test that builds the
current Specter-DIY WebAssembly runtime from source, then verifies inspection
activation, shutdown, request-ID-safe baseline comparison, and normal restart
with real firmware.

## Browser compatibility

GitHub Pages does not provide COOP/COEP response headers. This build does not
require SharedArrayBuffer. The DIY display has a Canvas pixel bridge for
browsers without transferable OffscreenCanvas. Chromium is covered by CI;
Firefox and WebKit should be checked when changing the display bridge. Test
on physical mobile devices and hardware before any release claim.
