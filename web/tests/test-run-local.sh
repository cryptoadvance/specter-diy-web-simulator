#!/usr/bin/env bash
# Offline tests for run-local.sh and build-browser.sh: preflight checks, remote
# handling, the dirty-checkout warning, switching the firmware revision and
# returning to the default branch when SPECTER_REF is no longer set.
# Needs no network, no Emscripten and no firmware download.
#
# Prerequisites for run-local.sh must be installed (git, python3, gcc, make,
# pkg-config, libffi-dev, libreadline-dev), as in the CI job.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.com
# Allow local-path submodules for the synthetic firmware repository below.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=protocol.file.allow GIT_CONFIG_VALUE_0=always

failures=0
pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1"; shift; printf '       %s\n' "$@"; failures=$((failures + 1)); }

# expect_fail <name> <pattern> <command...>: command must exit non-zero and print the pattern.
expect_fail() {
  local name="$1" pattern="$2"; shift 2
  local out status
  out="$("$@" 2>&1)"; status=$?
  if [[ $status -ne 0 && "$out" == *"$pattern"* ]]; then pass "$name"
  else fail "$name" "exit status $status, expected failure containing: $pattern" "$out"; fi
}

# A clone of this checkout. Its origin is a local path, so the simulator
# repository must be passed explicitly (SIMULATOR_REPOSITORY) where needed.
clone_simulator() { git clone -q "$REPO" "$1" && git -C "$1" config user.email test@example.com; }

# 1. A ZIP-style copy without .git is rejected before anything is downloaded.
mkdir "$TMP/nogit" && git -C "$REPO" archive HEAD | tar -x -C "$TMP/nogit"
expect_fail "run-local.sh rejects a copy without .git" "not a git clone" "$TMP/nogit/run-local.sh"

# 2. An origin that is not on GitHub is rejected with instructions.
clone_simulator "$TMP/sim-local-origin"
expect_fail "run-local.sh rejects a non-GitHub origin" "Cannot tell the GitHub owner/repo" \
  "$TMP/sim-local-origin/run-local.sh"

# 3. build-browser.sh: SPECTER_SRC must be a Specter-DIY checkout.
mkdir "$TMP/not-specter"
expect_fail "build-browser.sh rejects SPECTER_SRC without f469-disco/" "is not a Specter-DIY checkout" \
  env -i PATH="$PATH" HOME="$TMP" SPECTER_SRC="$TMP/not-specter" bash "$REPO/web/browser/build-browser.sh"

# 4. build-browser.sh: invalid repository names name the value and the variable to set.
mkdir -p "$TMP/fw-fake/f469-disco"
git -C "$TMP/fw-fake" init -q && git -C "$TMP/fw-fake" commit -q --allow-empty -m init
git -C "$TMP/fw-fake" remote add origin https://github.com/example/firmware.git
expect_fail "build-browser.sh rejects an invalid simulator repository" "Invalid simulator repository 'not a repo'" \
  env -i PATH="$PATH" HOME="$TMP" SPECTER_SRC="$TMP/fw-fake" SIMULATOR_REPOSITORY="not a repo" \
    SIMULATOR_COMMIT="$(git -C "$REPO" rev-parse HEAD)" bash "$REPO/web/browser/build-browser.sh"

# 5. build-browser.sh derives the simulator values from its own checkout: with a
#    GitHub origin on this checkout, validation passes and it stops later at the
#    missing Emscripten (env -i keeps any emsdk on PATH out).
clone_simulator "$TMP/sim-github-origin"
git -C "$TMP/sim-github-origin" remote set-url origin https://github.com/example/simulator.git
expect_fail "build-browser.sh derives simulator provenance from its checkout" "Emscripten 3.1.74 is required" \
  env -i PATH="$PATH" HOME="$TMP" SPECTER_SRC="$TMP/fw-fake" EMSDK_ENV="$TMP/none" \
    bash "$TMP/sim-github-origin/web/browser/build-browser.sh"

# Synthetic firmware repository whose submodule changes between two revisions.
git init -q "$TMP/fw-sub" && echo v1 > "$TMP/fw-sub/a.txt" && git -C "$TMP/fw-sub" add . \
  && git -C "$TMP/fw-sub" commit -qm c1 && C1="$(git -C "$TMP/fw-sub" rev-parse HEAD)" \
  && echo v2 > "$TMP/fw-sub/a.txt" && git -C "$TMP/fw-sub" commit -qam c2 && C2="$(git -C "$TMP/fw-sub" rev-parse HEAD)"
git init -q "$TMP/fw-super" && git -C "$TMP/fw-super" submodule add -q "$TMP/fw-sub" libs >/dev/null 2>&1
git -C "$TMP/fw-super/libs" checkout -q "$C1" && git -C "$TMP/fw-super" add -A \
  && git -C "$TMP/fw-super" commit -qm P1 && P1="$(git -C "$TMP/fw-super" rev-parse HEAD)"
git -C "$TMP/fw-super/libs" checkout -q "$C2" && git -C "$TMP/fw-super" add -A \
  && git -C "$TMP/fw-super" commit -qm P2 && P2="$(git -C "$TMP/fw-super" rev-parse HEAD)"

# Simulator clone with that firmware already in place, so nothing is downloaded.
clone_simulator "$TMP/sim"
mkdir "$TMP/sim/.browser-work"
git clone -q --recurse-submodules "$TMP/fw-super" "$TMP/sim/.browser-work/specter-diy"
FW="$TMP/sim/.browser-work/specter-diy"
DEFAULT_BRANCH="$(git -C "$FW" symbolic-ref --short HEAD)"   # the clone starts on the default branch (P2)

# 6. A clean checkout prints no warning; an uncommitted change does.
out="$(SIMULATOR_REPOSITORY=example/simulator FIRMWARE_ONLY=1 "$TMP/sim/run-local.sh" 2>&1)"; status=$?
if [[ $status -eq 0 && "$out" != *WARNING* ]]; then pass "no warning for a clean checkout"
else fail "no warning for a clean checkout" "exit status $status" "$out"; fi
echo "# change" >> "$TMP/sim/README.md"
out="$(SIMULATOR_REPOSITORY=example/simulator FIRMWARE_ONLY=1 "$TMP/sim/run-local.sh" 2>&1)"; status=$?
if [[ $status -eq 0 && "$out" == *"uncommitted changes"* ]]; then pass "warns about uncommitted changes"
else fail "warns about uncommitted changes" "exit status $status" "$out"; fi
git -C "$TMP/sim" checkout -q -- README.md

# 7. Switching SPECTER_REF to an older revision works although the build patched a submodule file.
echo "patched by the build" >> "$FW/libs/a.txt"
out="$(SIMULATOR_REPOSITORY=example/simulator SPECTER_REF="$P1" FIRMWARE_ONLY=1 "$TMP/sim/run-local.sh" 2>&1)"; status=$?
if [[ $status -eq 0 && "$(git -C "$FW" rev-parse HEAD)" == "$P1" && "$(cat "$FW/libs/a.txt")" == "v1" ]]; then
  pass "SPECTER_REF switch over a patched submodule"
else fail "SPECTER_REF switch over a patched submodule" "exit status $status, libs/a.txt: $(cat "$FW/libs/a.txt")" "$out"; fi

# 8. A later run without SPECTER_REF returns to the default branch instead of
#    quietly building the older revision. The firmware here is detached at P1.
echo "patched by the build" >> "$FW/libs/a.txt"
out="$(SIMULATOR_REPOSITORY=example/simulator FIRMWARE_ONLY=1 "$TMP/sim/run-local.sh" 2>&1)"; status=$?
if [[ $status -eq 0 && "$(git -C "$FW" symbolic-ref --short HEAD 2>/dev/null)" == "$DEFAULT_BRANCH"       && "$(git -C "$FW" rev-parse HEAD)" == "$P2" && "$(cat "$FW/libs/a.txt")" == "v2"       && "$out" == *"switching back to the default branch"* ]]; then
  pass "plain run returns to the default branch after SPECTER_REF"
else fail "plain run returns to the default branch after SPECTER_REF" "exit status $status, HEAD: $(git -C "$FW" rev-parse HEAD)" "$out"; fi

# 9. A local branch checked out by hand is also replaced by the default branch, and the
#    firmware is left untouched when the default branch is already selected.
git -C "$FW" checkout -q -b other "$P1" && git -C "$FW" submodule update --init --recursive --force -q
out="$(SIMULATOR_REPOSITORY=example/simulator FIRMWARE_ONLY=1 "$TMP/sim/run-local.sh" 2>&1)"; status=$?
if [[ $status -eq 0 && "$(git -C "$FW" symbolic-ref --short HEAD)" == "$DEFAULT_BRANCH" ]]; then
  pass "plain run leaves another branch for the default branch"
else fail "plain run leaves another branch for the default branch" "exit status $status" "$out"; fi
echo "local edit" >> "$FW/libs/a.txt"
out="$(SIMULATOR_REPOSITORY=example/simulator FIRMWARE_ONLY=1 "$TMP/sim/run-local.sh" 2>&1)"; status=$?
if [[ $status -eq 0 && "$out" != *"switching back"* && "$(tail -n1 "$FW/libs/a.txt")" == "local edit" ]]; then
  pass "plain run does nothing when the default branch is already selected"
else fail "plain run does nothing when the default branch is already selected" "exit status $status" "$out"; fi

echo
if [[ $failures -eq 0 ]]; then echo "All run-local tests passed."; else echo "$failures test(s) failed."; exit 1; fi
