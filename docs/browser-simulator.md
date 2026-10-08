# Browser simulator and PR preview service

The browser simulator runs the actual Specter DIY `src/` application under
MicroPython compiled to WebAssembly with Emscripten 3.1.74. This repository
provides the browser shell, simulated peripherals, build scripts, and tests; it
does not contain a second wallet implementation.

```text
specter-diy PR event
  └─ short trusted dispatcher ── workflow_dispatch + exact PR metadata ──┐
                                                                         ▼
                                                     specter-diy-web-simulator
                                                       ├─ validate live PR
                                                       ├─ untrusted runner: firmware + WASM/data + tests
                                                       ├─ fresh trusted runner: JS from exact base SHA
                                                       ├─ finalizer: validate and combine artifacts
                                                       ├─ publish immutable Pages preview + trusted state
                                                       └─ GitHub App reposts the final PR comment
```

The official preview URL for a PR includes its full source commit SHA, for
example `https://cryptoadvance.github.io/specter-diy-web-simulator/pr/45/<sha>/`.
A paired fork uses the matching owner, for example
`https://alice.github.io/specter-diy-web-simulator/pr/12/<sha>/`.

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

After a successful dispatch, the Specter workflow exits. It does not wait for
the firmware or browser build. The simulator finalizer validates the live PR
again before publication and before reporting. Its persistent state prevents a
stale finalizer from replacing a newer result or comment.

This workflow uses `pull_request_target`. Repository or organization Actions
policy must permit that event for public repositories. A repository or
organization administrator should verify the policy before GitHub's announced
November 2, 2026 enforcement date.

The Web Simulator validates the paired base repository and compares the request
to the live GitHub PR before building. Build requests must match an open PR's
base, head repository, branch, number, and exact SHA. The source checkout is by
SHA, including submodules. The trusted finalizer validates the exact request,
run identity, monotonic state, and live PR again before it reports the result.

The trusted simulator finalizer uses a short-lived GitHub App installation
token to manage one marked PR conversation comment. Install the App on **only**
`cryptoadvance/specter-diy` and grant only the **Pull requests: Read and write**
repository permission. For each accepted result, it deletes only comments from
that App identity containing `<!-- specter-web-simulator-preview -->`, then
posts the refreshed comment at the bottom. A closed PR removes all its previews
and matching App comments.

Configure these Web Simulator repository settings:

- Repository variable `SPECTER_PREVIEW_APP_ID`: the GitHub App ID.
- Repository secret `SPECTER_PREVIEW_APP_PRIVATE_KEY`: the App private key.

The workflow resolves the installation ID and scopes each short-lived token to
the single repository; it uses the App slug returned by the token action to
verify the expected comment author. The App needs no Contents, Actions, Issues,
or Administration permission. Keep `WEB_SIMULATOR_DISPATCH_TOKEN` separately in
the Specter DIY repository; it only dispatches the Web Simulator workflow and
is never exposed to the untrusted build job.

The trusted finalizer's `GITHUB_TOKEN` also has `Actions: write` in the Web
Simulator repository solely to delete superseded firmware artifacts. The App
token remains limited to writing PR conversation comments in
`cryptoadvance/specter-diy`; the untrusted build job has no Actions write
permission.

Fork-source PRs targeting `cryptoadvance/specter-diy` use this App reporter and
remain supported. A paired Web Simulator fork can still build and publish its
own previews, but it does not receive the upstream App credential and therefore
does not write comments on its forked Specter repository.

The service uses its workflow token with `pull-requests: read` to validate the
live PR. Published PR pages receive a stricter copy of the trusted shell's
Content Security Policy: `connect-src 'self'`. This blocks external network
requests and the local Virtual Host WebSocket from PR previews. The stable
simulator keeps the local Virtual Host allowance. Browser tests exercise both
policies.

The main simulator page has an expandable **Virtual USB Connection** panel
with a link to the latest Specter Virtual Host release, setup steps, and live
local bridge status. The release link follows GitHub's latest-release redirect
instead of pinning a version or asset filename. It opens the localhost WebSocket
only when the visitor expands the panel (or explicitly enables
`?virtual-host=1`). PR previews keep the panel visible but explain that the local
connection is disabled there; their stricter CSP remains in force.

Successful PR previews use commit-specific paths `/pr/<N>/<full-head-sha>/`.
After a newer preview has been built successfully, the trusted publisher removes
the older browser pages for that PR, so only its latest successful preview URL
remains online. A failed or cancelled build keeps the last successful page.
The publisher retains its provenance and firmware link in
`.preview-state/pr/<N>.json` on the persistent `gh-pages` branch. Each PR has
one current firmware artifact after a successful publication, retained for up
to 90 days. After a newer preview is published and its PR report succeeds, the
finalizer deletes the replaced firmware artifacts for that PR.

Before deployment, the workflow measures the public Pages files. It does not
remove pages for other PRs during normal publishing. If the public tree exceeds
its 950 MB safety budget, it evicts previews from the least recently updated
PRs until the tree is under budget, while protecting the PR currently being
published. Evicted PR comments are updated to explain that their browser page
was removed for Pages capacity; their firmware artifact remains available. If
older PR pages cannot bring the tree under budget, publication stops instead
of deleting the current PR's new preview. Closing a PR removes every public
preview under `/pr/<N>/`, deletes the firmware artifacts recorded for the PR,
clears its success history, and leaves a minimal tombstone to reject delayed
requests. The state is excluded from public Pages output.
The firmware download ZIP is named `specter-firmware_PR-440_47e6588891f3.zip`
(PR number and the first 12 characters of its exact source commit). Inside the
ZIP, the files use the same base name with `.bin` and `.hex` extensions;
`source.json` continues to carry full-source-SHA, hashes and provenance.
On a GitHub Actions rerun (attempt 2+), only the ZIP artifact name adds
`_attempt-2` etc. This avoids collisions with an earlier artifact from the
same workflow run without overwriting the previous firmware.

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
convention. There is no custom server, database, callback workflow, or second
wallet logic implementation.

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
