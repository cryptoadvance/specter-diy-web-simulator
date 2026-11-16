#!/usr/bin/env bash
# Build the Specter DIY browser simulator from source and serve it locally.
#
#   ./run-local.sh                 build (first run: slow) and serve on :8765
#   PORT=9000 ./run-local.sh       serve on another port
#   BUILD_ONLY=1 ./run-local.sh    build and verify, do not start the server
#   SPECTER_REF=<tag|branch|sha> ./run-local.sh   simulate another firmware revision
#                                  (without it, the default branch is restored)
#   FIRMWARE_ONLY=1 ./run-local.sh fetch/select the firmware revision, then stop
#   SERVE_ONLY=1 ./run-local.sh    serve an existing build without rebuilding
#   BIND=0.0.0.0 ./run-local.sh    listen on all interfaces (default: 127.0.0.1 only)
#
# Everything it downloads goes into ./.browser-work (ignored by git): a
# recursive clone of cryptoadvance/specter-diy and Emscripten 3.1.74. The
# firmware clone there is patched by the build; delete .browser-work to reset.
# Needs Linux with git, python3 and the native build tools below.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$HERE/.browser-work"
FIRMWARE="$WORK/specter-diy"
EMSDK_DIR="$WORK/emsdk"
PORT="${PORT:-8765}"
BIND="${BIND:-127.0.0.1}"
EMSCRIPTEN_VERSION=3.1.74
APT_PACKAGES="git python3 build-essential pkg-config libffi-dev libreadline-dev"

step() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

serve() {
  step "Serving on http://localhost:$PORT/  (Ctrl+C to stop)"
  exec python3 -m http.server "$PORT" --bind "$BIND" --directory "$HERE/web"
}

if [[ "${SERVE_ONLY:-0}" = 1 ]]; then
  [[ -f "$HERE/web/browser/current.json" ]] || die "No build found. Run ./run-local.sh without SERVE_ONLY first."
  serve
fi

step "Checking prerequisites"
case "$(uname -s)" in
  Linux) ;;
  *) die "Linux is required (found $(uname -s))." ;;
esac
missing=()
for tool in git python3 gcc make pkg-config; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
pkg-config --exists libffi 2>/dev/null || missing+=("libffi-dev")
[[ -f /usr/include/readline/readline.h ]] || missing+=("libreadline-dev")
if ((${#missing[@]})); then
  echo "Missing: ${missing[*]}" >&2
  die "Install the prerequisites, then run this script again:
  sudo apt-get update && sudo apt-get install --yes $APT_PACKAGES"
fi

# The build records which simulator checkout produced it. Check this now so a
# problem shows up in seconds, not after the downloads.
if ! simulator_commit="$(git -C "$HERE" rev-parse HEAD 2>&1)"; then
  if [[ ! -e "$HERE/.git" ]]; then
    die "$HERE is not a git clone (no .git metadata). Use:
  git clone https://github.com/cryptoadvance/specter-diy-web-simulator.git"
  fi
  die "$HERE is not a usable git checkout: $simulator_commit"
fi
if [[ -z "${SIMULATOR_REPOSITORY:-}" ]]; then
  origin="$(git -C "$HERE" remote get-url origin 2>/dev/null || true)"
  if [[ ! "$origin" =~ github\.com[:/][A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+ ]]; then
    die "Cannot tell the GitHub owner/repo of this clone (origin: '${origin:-none}'). Run:
  SIMULATOR_REPOSITORY=owner/repo ./run-local.sh"
  fi
fi

if [[ -n "$(git -C "$HERE" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
  echo "WARNING: this checkout has uncommitted changes. The build records only the commit" >&2
  echo "         (${simulator_commit:0:7}), which does not describe them." >&2
fi

mkdir -p "$WORK"

step "Firmware source (cryptoadvance/specter-diy)"
if [[ ! -d "$FIRMWARE/.git" ]]; then
  git clone --recurse-submodules https://github.com/cryptoadvance/specter-diy.git "$FIRMWARE"
else
  echo "Using existing $FIRMWARE"
fi
# --force: an earlier build patched files inside the submodules, and git
# refuses to switch a submodule commit over locally modified files without it.
switch_firmware() {
  git -C "$FIRMWARE" checkout --force "$1"
  git -C "$FIRMWARE" submodule update --init --recursive --force
}
if [[ -n "${SPECTER_REF:-}" ]]; then
  git -C "$FIRMWARE" fetch --tags origin
  switch_firmware "$SPECTER_REF"
else
  # Without SPECTER_REF the default firmware branch is built, also after an
  # earlier run with SPECTER_REF left the clone on another revision. This does
  # not fetch: it returns to the branch as last fetched, so plain runs stay offline.
  default_branch="$(git -C "$FIRMWARE" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  default_branch="${default_branch#origin/}"
  if [[ -z "$default_branch" ]]; then
    for candidate in master main; do
      if git -C "$FIRMWARE" show-ref --verify --quiet "refs/remotes/origin/$candidate"; then
        default_branch="$candidate"; break
      fi
    done
  fi
  [[ -n "$default_branch" ]] || die "Cannot tell the default branch of $FIRMWARE. Select a revision:
  SPECTER_REF=<tag|branch|sha> ./run-local.sh   (or delete .browser-work and retry)"
  current_branch="$(git -C "$FIRMWARE" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  if [[ "$current_branch" != "$default_branch" ]]; then
    echo "Firmware is on ${current_branch:-a detached commit $(git -C "$FIRMWARE" rev-parse --short HEAD)}; SPECTER_REF is not set, so switching back to the default branch '$default_branch'."
    switch_firmware "$default_branch"
  fi
fi

[[ "${FIRMWARE_ONLY:-0}" = 1 ]] && { echo "Firmware ready in $FIRMWARE."; exit 0; }

step "Emscripten $EMSCRIPTEN_VERSION"
if [[ ! -f "$EMSDK_DIR/emsdk_env.sh" ]]; then
  git clone https://github.com/emscripten-core/emsdk.git "$EMSDK_DIR"
fi
"$EMSDK_DIR/emsdk" install "$EMSCRIPTEN_VERSION"   # no-op when already installed
"$EMSDK_DIR/emsdk" activate "$EMSCRIPTEN_VERSION"
# shellcheck source=/dev/null
source "$EMSDK_DIR/emsdk_env.sh" >/dev/null

step "Building the WebAssembly simulator (the first build takes a while)"
SPECTER_SRC="$FIRMWARE" bash "$HERE/web/browser/build-browser.sh"

step "Verifying the build"
python3 "$HERE/web/browser/verify_build.py"

[[ "${BUILD_ONLY:-0}" = 1 ]] && { echo "Build finished."; exit 0; }

serve
