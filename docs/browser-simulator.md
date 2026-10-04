# Browser simulator and PR previews

The browser simulator runs the **actual** Specter DIY `src/` application under
the fork's MicroPython Unix port, compiled with Emscripten 3.1.74. LVGL draws
the display in a Web Worker. The website presents that framebuffer inside the
physical device image and forwards pointer coordinates to LVGL. Browser shims
replace only device transport: `/state/sd` via `platform.SDCard`, scanner data
via `pyb.UART('YA')`, and MemoryCard APDUs via `uscard.Reader`.

```text
Browser page → Worker → MicroPython/WASM → Specter Python → LVGL → Canvas
                              ↑                   ↑
                      virtual SD/card       QR scanner seam
```

**Experimental development build. Never enter a real seed phrase or use real
funds.** The browser and any automatically built firmware lack the security
assurances of an official release. Use test seeds and dedicated test hardware.
Imported SD files, scanned QR payloads, and virtual card data stay in the tab;
the shell fetches static assets only. Runtime sockets and SSL are disabled.
Reloading discards simulated state. Normal restart retains simulated flash and
peripheral files; factory reset wipes flash separately. The webcam requires
HTTPS or localhost and browser permission. Some browser versions need the
local Unix simulator; physical-device camera, secure element, air-gap,
STM32 timing, battery, and physical card properties are not simulated.

The SD-card panel starts with its demo-set selector at **None**, beside **Add
files** and **Clear card**. Selecting Testnet or Mainnet replaces the previous
demo files and loads that network's public seed examples and transactions. The
SD card is inserted automatically when the demo needs it; Smartcards are never
inserted automatically. Returning to **None** removes demo files and restores
the previous simulated Smartcard contents and peripheral insertion state.
Unrelated files on the SD card remain in place, and this selection is not saved
across reloads.

## Build locally

From Linux or WSL with this repository checked out next to a recursive
Specter-DIY checkout:

1. Install and activate [Emscripten SDK](https://emscripten.org/docs/getting_started/downloads.html)
   **3.1.74** (`emcc --version` must report it), plus the native build
   dependencies required by the Specter-DIY source checkout.
2. Run `SPECTER_SRC=/path/to/specter-diy bash web/browser/build-browser.sh`
   from this repository's root. The source checkout must be at the exact
   commit you intend to simulate.
3. Run `python3 web/browser/verify_build.py` and
   `python3 web/tests/test-source-project.py`.
4. Run `npm ci --prefix web`, `npx --prefix web playwright install chromium`,
   then `python3 -m http.server 8765 --directory web` in one shell and
   `CI=true npm run test:browser --prefix web` in another. Run
   `npm run test:compat --prefix web` after installing Firefox and WebKit with
   Playwright for additional engine coverage.

The build output is `web/builds/<owner>/<repo>/<source-sha>/` with
`micropython.js`, `.wasm`, `.data`, and `build-info.json`. The manifest records
two immutable inputs: `source.repository`/`source.commit` identify the
Specter-DIY code being simulated, while `simulator.repository`/
`simulator.commit` identify the simulator tooling that built it. It also
records the Emscripten version, build time, and SHA256 of each artifact.
`web/browser/current.json` remains only a pointer to the build. Both generated
directories are ignored by Git. `SPECTER_SOURCE_REPOSITORY=owner/repo`,
`SIMULATOR_REPOSITORY=owner/repo`, and `SIMULATOR_COMMIT=<full-sha>` can be
used when building source and tooling from different repositories.

The build script applies only browser compatibility changes to the checked-out
MicroPython/LVGL C submodules. It freezes the wallet's `src/` tree without
changing wallet screens or logic. Browser-specific Python, JS, and source
patching stay under `web/browser/`. The existing Unix simulator and hardware
firmware build remain separate.

For newer board revisions, the browser freeze uses the board's curated
`f469-disco/manifests/common.py`, including embit from its `src/` package path.
Older revisions without that manifest retain the original flat-library freeze.
The build checks the resulting module list before compiling WebAssembly, so
CPython-only embit examples and tests cannot enter a current browser build.

## CI and Pages

The Specter-DIY `Build` workflow runs native tests, builds Unix and STM32
firmware, and runs browser/QR/SD/Smartcard smoke tests. It resolves simulator
`main` once and checks out the exact simulator SHA in every build job before
running simulator scripts. This keeps the execution context and read-only token
in the Specter repository. The browser and firmware artifacts carry separate `source.json`
records, and the browser `build-info.json` carries both provenance records.
The build workflow has **read-only** repository permissions and no deployment
secret.

The firmware repository does not call a remote reusable workflow at `main`:
GitHub could resolve that workflow independently from the simulator SHA in
build metadata. The privileged publisher implementation lives in the firmware
repository's protected default branch.

For PRs, the read-only `Build` workflow runs directly on `pull_request` and
uses the exact PR head repository and SHA from the event. PR source runs only
in jobs with read-only permissions. A separate job builds Emscripten JavaScript from
default-branch firmware and trusted simulator tooling. The PR build supplies
WebAssembly and frozen firmware data. The read-only build replaces the PR
build's generated JavaScript with its runtime and updates artifact hashes. A
separate read-only job in the protected publish workflow independently builds
the trusted runtime; the write-enabled job verifies the browser JavaScript
against that artifact. HTML, CSS, images, UI logic, worker, peripheral
implementation, and the experimental warning come from the publisher's
simulator checkout. Its worker inherits a CSP allowing same-site assets and
the local Virtual Host on port 8788 while blocking other outbound connections.

A separate `Publish browser simulator` workflow runs from the trusted default
branch after `Build` completes. It verifies that the browser manifest, its
artifact hashes, the firmware hashes, and both provenance records identify the
same still-current PR head. It never executes the downloaded build. A passing
default-branch build updates the stable Pages root; a passing PR build updates
`/pr/<number>/` and a single PR comment with links to the simulator, firmware
artifact, and build log. A failed current PR build removes its stale preview
and replaces that one comment with a failure notice, even when it uploaded no
artifacts. The PR is identified from the trusted `workflow_run` event and
checked against the current pull-request API record. A run
superseded by a newer PR commit cannot replace the current preview. The
publisher keeps an
`gh-pages` branch as static state and uses `actions/deploy-pages` to deploy the
complete tree. PRs receive no write token or deployment credentials.

Deploy the simulator changes to its trusted `main` branch before enabling the
new firmware workflow on the firmware default branch. Remove legacy PR
previews from `gh-pages` once, then rebuild open PRs so old published shells
cannot remain reachable. GitHub Pages must use **GitHub Actions** as its
deployment source. A PR with new C imports may require a compatible trusted
Emscripten runtime update before its WebAssembly can run; the browser smoke
tests must pass with the combined artifacts.

### Rebuild an older open PR without a commit

Once this workflow is on the default branch, use **Actions → Build → Run
workflow**, select the default branch, and enter the PR number and the first
seven (or more) hexadecimal characters of its current head SHA. The Build job
resolves the prefix against that PR's current full head SHA before checking out
source. If the head changes to a different prefix before publication, the
publisher ignores the stale run. Seven characters are convenient but are not
globally unique; use a longer prefix when comparing closely spaced revisions.
Whitespace around the inputs is ignored. If the SHA does not match the PR's
current head, the target job reports the current prefix and stops the build.
The CLI helper needs only the PR number and reads the SHA itself:

```sh
python3 web/tools/trigger_pr_build.py 123 --repo cryptoadvance/specter-diy
```

This starts the existing `Build` workflow; it does not create another Actions
workflow or add a commit to the PR. Manual runs check out the PR's exact head
for Specter source and firmware, but use the current default branch's browser
build tools and website shell. The browser manifest records both the PR source
commit and the simulator tooling commit. The publisher checks both,
and it can remove a failed current manual preview without downloading any
artifact. A very old PR with incompatible MicroPython/LVGL or firmware sources
may still fail to build; its build log will show the concrete incompatibility.
GitHub's manual Run workflow button is unavailable until this workflow file is
present on the repository's default branch.

For `cryptoadvance/specter-diy`, enable **Settings → Pages → Build and deployment →
GitHub Actions** once. Confirm Actions are enabled and allow the publisher workflow
to write to the repository. After the first successful default-branch build,
the stable URL is `https://cryptoadvance.github.io/specter-diy/`; PR previews
are `https://cryptoadvance.github.io/specter-diy/pr/<number>/`. The same workflow
uses `GITHUB_REPOSITORY` and works in another fork after its owner enables
Actions and Pages. PR previews are untrusted development code; the warning
is permanent and no wallet secrets should ever be entered.

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
activation, shutdown, baseline stability, and normal restart with real firmware.

GitHub Pages does not provide COOP/COEP response headers. This build does not
require SharedArrayBuffer. The DIY display has a Canvas pixel bridge for
browsers without transferable OffscreenCanvas. Chromium is covered by CI;
Firefox and WebKit should be checked when changing the display bridge. Test
on physical mobile devices and hardware before any release claim.
