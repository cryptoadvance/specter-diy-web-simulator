#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPECTER_SRC="${SPECTER_SRC:-$(cd "$ROOT/.." && pwd)}"
EMSDK_ENV="${EMSDK_ENV:-$ROOT/../.browser-work/emsdk/emsdk_env.sh}"

# SPECTER_SRC must be a Specter-DIY firmware checkout, not this repository.
# Without it the default above points at the simulator checkout itself.
[[ -d "$SPECTER_SRC/f469-disco" ]] || {
  echo "SPECTER_SRC=$SPECTER_SRC is not a Specter-DIY checkout (no f469-disco/)." >&2
  echo "Set SPECTER_SRC to a recursive clone of cryptoadvance/specter-diy." >&2
  exit 1
}

# Print "owner/repo" for the GitHub remote 'origin' of the checkout in $1.
origin_repository() {
  git -C "$1" remote get-url origin 2>/dev/null \
    | sed -E 's#^(https://github.com/|git@github.com:|ssh://git@github.com/)##; s#\.git$##'
}

SOURCE_SHA="$(git -C "$SPECTER_SRC" rev-parse HEAD)"
ORIGIN_REPOSITORY="$(origin_repository "$SPECTER_SRC" || true)"
SOURCE_REPOSITORY="${SPECTER_SOURCE_REPOSITORY:-${GITHUB_REPOSITORY:-$ORIGIN_REPOSITORY}}"

# Simulator provenance describes the tooling checkout (this repository), never
# the firmware checkout. Derive it from this repository unless overridden;
# CI may pass SIMULATOR_REPOSITORY and SIMULATOR_COMMIT explicitly.
SIMULATOR_ROOT="$(cd "$ROOT/.." && pwd)"
SIMULATOR_REPOSITORY="${SIMULATOR_REPOSITORY:-$(origin_repository "$SIMULATOR_ROOT" || true)}"
SIMULATOR_COMMIT="${SIMULATOR_COMMIT:-$(git -C "$SIMULATOR_ROOT" rev-parse HEAD 2>/dev/null || true)}"
[[ -n "$SIMULATOR_REPOSITORY" && -n "$SIMULATOR_COMMIT" ]] || {
  echo 'Cannot determine simulator repository/commit from this checkout.' >&2
  echo 'Set SIMULATOR_REPOSITORY=owner/repo and SIMULATOR_COMMIT=<full-sha>.' >&2
  exit 1
}
[[ "$SOURCE_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo "Invalid source repository '$SOURCE_REPOSITORY' (expected owner/repo)." >&2
  echo "Set SPECTER_SOURCE_REPOSITORY=owner/repo if the firmware clone has no GitHub origin." >&2
  exit 1
}
[[ "$SIMULATOR_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo "Invalid simulator repository '$SIMULATOR_REPOSITORY' (expected owner/repo)." >&2
  echo "Set SIMULATOR_REPOSITORY=owner/repo if this clone has no GitHub origin." >&2
  exit 1
}
[[ "$SIMULATOR_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid simulator commit' >&2; exit 1; }
OUT="$ROOT/builds/$SOURCE_REPOSITORY/$SOURCE_SHA"

# CI checks out the exact PR head. Building from this checkout makes the
# firmware artifact and browser manifest identify the same source commit.
git -C "$SPECTER_SRC" submodule update --init --recursive

if ! command -v emcc >/dev/null; then
  # A pinned emsdk installation can be supplied outside this repository.
  test -f "$EMSDK_ENV" || {
    echo "Emscripten 3.1.74 is required: 'emcc' is not on PATH and $EMSDK_ENV does not exist." >&2
    echo "Run 'source /path/to/emsdk/emsdk_env.sh' first, or set EMSDK_ENV to that file." >&2
    exit 1
  }
  # shellcheck source=/dev/null
  source "$EMSDK_ENV" >/dev/null
fi
test "$(emcc --version | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)" = 3.1.74 || {
  echo "Expected Emscripten 3.1.74" >&2
  exit 1
}

python3 "$ROOT/browser/patch-source.py" "$SPECTER_SRC"
python3 "$ROOT/browser/write-browser-manifest.py" "$SPECTER_SRC"
python3 "$ROOT/tests/test-browser-manifest.py" "$SPECTER_SRC"
make -C "$SPECTER_SRC/f469-disco/micropython/mpy-cross" -j4 \
  CFLAGS_EXTRA="-Wno-dangling-pointer -Wno-enum-int-mismatch"

# The older MicroPython makefiles do not track a changed frozen manifest or
# Emscripten link flags reliably. Rebuild the dedicated browser target.
if [[ "${BROWSER_CLEAN:-1}" = 1 ]]; then
  make -C "$SPECTER_SRC/f469-disco/micropython/ports/unix" \
    BUILD=build-specter-web-browser PROG=micropython.js clean
fi
rm -f "$SPECTER_SRC/f469-disco/micropython/ports/unix/micropython.js" \
  "$SPECTER_SRC/f469-disco/micropython/ports/unix/micropython.wasm" \
  "$SPECTER_SRC/f469-disco/micropython/ports/unix/micropython.data"

make -C "$SPECTER_SRC/f469-disco/micropython/ports/unix" -j4 \
  DEBUG="${BROWSER_DEBUG:-0}" \
  BUILD=build-specter-web-browser PROG=micropython.js \
  CC=emcc LD=emcc AR=emar STRIP=true SIZE=true \
  MICROPY_PY_BTREE=0 MICROPY_PY_FFI=0 MICROPY_PY_SOCKET=0 \
  MICROPY_PY_THREAD=0 MICROPY_PY_TERMIOS=0 MICROPY_PY_USSL=0 \
  MICROPY_USE_READLINE=1 \
  USER_C_MODULES="$SPECTER_SRC/f469-disco/usermods" \
  FROZEN_MANIFEST="$SPECTER_SRC/browser.manifest.py" \
  CFLAGS_EXTRA="-DMICROPY_NLR_SETJMP=1 -DMICROPY_PY_UCRYPTOLIB=1 -DMICROPY_SSL_AXTLS=1 -Wno-error -sUSE_SDL=2 -ffile-prefix-map=$SPECTER_SRC=/specter-diy ${BROWSER_NLR_FLAGS:-} ${BROWSER_CFLAGS_DEBUG:-}" \
  LDFLAGS_ARCH= \
  LDFLAGS_EXTRA="-sUSE_SDL=2 ${BROWSER_ASYNCIFY_FLAGS:--sASYNCIFY=1 -sASYNCIFY_STACK_SIZE=65536} -sALLOW_MEMORY_GROWTH=1 -sFORCE_FILESYSTEM=1 -sEXIT_RUNTIME=0 -sSTACK_SIZE=${BROWSER_STACK_SIZE:-8388608} -sEXPORTED_RUNTIME_METHODS=FS,ccall --preload-file $ROOT/browser/runtime@/browser -Wl,--allow-multiple-definition ${BROWSER_NLR_FLAGS:-} ${BROWSER_LINK_DEBUG:-}"

python3 "$ROOT/browser/normalize-glue.py" "$SPECTER_SRC/f469-disco/micropython/ports/unix/micropython.js"
mkdir -p "$OUT"
cp "$SPECTER_SRC/f469-disco/micropython/ports/unix/micropython.js" "$OUT/"
cp "$SPECTER_SRC/f469-disco/micropython/ports/unix/micropython.wasm" "$OUT/"
cp "$SPECTER_SRC/f469-disco/micropython/ports/unix/micropython.data" "$OUT/"
python3 "$ROOT/browser/write-manifest.py" "$SPECTER_SRC" "$OUT" \
  "$SOURCE_REPOSITORY" "$SIMULATOR_REPOSITORY" "$SIMULATOR_COMMIT"
echo "Browser artifacts: $OUT"
