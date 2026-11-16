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

## Run it locally

Build the simulator yourself to test local Specter DIY changes or simulator
tooling. Pull request previews and the paired-fork setup are described in
[the guide](docs/browser-simulator.md).

Pick one of two ways. **On Linux** use the script below. **On Windows or
macOS** use [Docker](#windows-and-macos-docker).

### Linux

The script was tested on Ubuntu 24.04 (CI also runs Ubuntu). Install the
prerequisites once (Debian/Ubuntu commands; skip this if `git`, `python3` and the
build tools are already installed; it asks for your Linux password; on other
distributions install the equivalent packages):

```sh
sudo apt-get update && sudo apt-get install --yes git python3 build-essential pkg-config libffi-dev libreadline-dev
```

Then build and start the simulator:

```sh
git clone https://github.com/cryptoadvance/specter-diy-web-simulator.git
cd specter-diy-web-simulator && ./run-local.sh
```

When the script prints `Serving on http://localhost:8765/`, open that address in
a browser (Chromium is the engine covered by CI). The server only listens on your
own computer (`127.0.0.1`). Stop it with `Ctrl+C`; run `./run-local.sh` again to
restart.

`run-local.sh` downloads over 300 MB (the pinned Emscripten 3.1.74 plus the
firmware with its submodules), all into `.browser-work/` (ignored by Git), builds
the WebAssembly runtime, verifies it, and serves `web/`. Later runs reuse the
downloads and only rebuild. Options are environment variables:

| Variable | Effect |
| --- | --- |
| `PORT=9000` | serve on another port |
| `BUILD_ONLY=1` | build and verify, do not start the server |
| `FIRMWARE_ONLY=1` | fetch or select the firmware revision (with `SPECTER_REF`), then stop |
| `SERVE_ONLY=1` | serve the existing build without rebuilding |
| `BIND=0.0.0.0` | listen on all network interfaces instead of only `127.0.0.1` |
| `SPECTER_REF=<tag, branch or sha>` | simulate that firmware revision instead of the default branch; a later run without it switches back to the default branch (as last fetched, without a network access) |

Do not open `web/index.html` directly from disk: the page fetches the build
files over HTTP.

### Windows and macOS (Docker)

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and
start it. Then, in any terminal (PowerShell, Command Prompt or a macOS terminal):

```sh
git clone https://github.com/cryptoadvance/specter-diy-web-simulator.git
cd specter-diy-web-simulator
docker build -t specter-sim .
docker run --rm -p 127.0.0.1:8765:8765 specter-sim
```

Open <http://localhost:8765/>. Stop it with `Ctrl+C`. `docker build` does the
work of `run-local.sh` inside an Ubuntu container: it downloads and compiles
everything (about 10 minutes the first time, and several GB of Docker build
cache) and keeps only the static site, so the final image is about 200 MB.
`docker run` only serves it and starts immediately. If port 8765 is taken, use
another host port, for example `-p 127.0.0.1:9000:8765`, and open that one.
Build from a `git clone`, not a ZIP download, because the image takes the
simulator commit from `.git`. To simulate another firmware revision, add
`--build-arg SPECTER_REF=<tag, branch or sha>` to `docker build`. Tested on
Windows 11 with Docker Desktop; macOS is untested.

<details>
<summary>Manual steps without the script</summary>

```sh
# 1. Get the firmware (with submodules) and this repository
git clone --recurse-submodules https://github.com/cryptoadvance/specter-diy.git
git clone https://github.com/cryptoadvance/specter-diy-web-simulator.git

# 2. Install and activate the pinned Emscripten toolchain
git clone https://github.com/emscripten-core/emsdk.git
./emsdk/emsdk install 3.1.74
./emsdk/emsdk activate 3.1.74
source ./emsdk/emsdk_env.sh        # repeat in every new shell
emcc --version                     # must print 3.1.74

# 3. Build the WebAssembly runtime from the firmware checkout
cd specter-diy-web-simulator
SPECTER_SRC="$(realpath ../specter-diy)" bash web/browser/build-browser.sh

# 4. Check the build, then serve the web/ directory
python3 web/browser/verify_build.py
python3 -m http.server 8765 --directory web
```

</details>

The build records which firmware commit and which simulator commit produced it
in `web/builds/<owner>/<repo>/<firmware-sha>/build-info.json`. The simulator
repository and commit are read from this checkout; the firmware repository and
commit come from `SPECTER_SRC` (`.browser-work/specter-diy` when using `run-local.sh`). See
[Build locally](docs/browser-simulator.md#build-locally) for the environment
variables that override this and for running the automated browser tests.

**The build modifies the firmware checkout.** `build-browser.sh` patches C
sources and makefiles under `f469-disco/` (display, SDL, crypto and MicroPython
unix-port files), updates submodules, and writes `browser.manifest.py` inside
`SPECTER_SRC`. Use a dedicated clone of `specter-diy`, not a working copy with
uncommitted changes. `run-local.sh` uses its own clone in `.browser-work/`;
delete that folder to start from scratch.

**Troubleshooting:** see [Troubleshooting](docs/browser-simulator.md#troubleshooting).
