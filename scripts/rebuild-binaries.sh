#!/usr/bin/env bash
# FreeFlix — one-command binary build & release verification automation.
#
# Solves the 2.6.1 "Windows downgrade" process gap:
#   * the standalone .exe was built without --collect-data, so Match lost its
#     bundled clubs/logos data and nothing caught it before users downloaded it;
#   * the release workflow only runs on a published release, and the published
#     v2.6.1 asset is still the broken exe.
#
# Modes
#   --local                 lint + tests + build the standalone binary locally
#                           + verify embedded data + build & verify the wheel.
#   --windows-ci            trigger .github/workflows/standalone-binaries.yml (all
#                           OSes) on GitHub, wait for the real Windows .exe,
#                           download and verify its embedded data.
#   --verify-release TAG    download a published release's assets, check their
#                           sha256 and verify each binary embeds the data.
#   --republish TAG         re-run binaries.yml for TAG (rebuilds all 3 OS
#                           binaries and re-attaches them to the release), then
#                           verify the result. This is how the already-published
#                           broken v2.6.1 exe gets fixed for users.
#   --all TAG               local + windows-ci + republish TAG + verify.
#
# Options
#   --skip-tests            skip ruff/pytest in --local/--all (faster).
#   -h, --help              this help.
#
# Requirements: uv (local builds), gh + auth (CI/release modes). Everything
# runs through the same shared checker (scripts/check-binary-data.sh) as CI.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

BLUE="\033[1;34m"; GREEN="\033[1;32m"; YELLOW="\033[1;33m"; RED="\033[1;31m"; NC="\033[0m"
log()  { echo -e "${BLUE}»${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

MODE=""
TAG=""
SKIP_TESTS=0
WORK="$(mktemp -d "${TMPDIR:-/tmp}/freeflix-rebuild.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

usage() {
    sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --local)          MODE="local" ;;
        --windows-ci)     MODE="windows-ci" ;;
        --verify-release) MODE="verify"; TAG="${2:?--verify-release needs a TAG}"; shift ;;
        --republish)      MODE="republish"; TAG="${2:?--republish needs a TAG}"; shift ;;
        --all)            MODE="all"; TAG="${2:?--all needs a TAG}"; shift ;;
        --skip-tests)     SKIP_TESTS=1 ;;
        -h|--help)        usage 0 ;;
        *) err "unknown argument: $1"; usage 1 ;;
    esac
    shift
done

if [[ -z "$MODE" ]]; then
    usage 1
fi

# ─── helpers ─────────────────────────────────────────────────────────
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || { err "required command not found: $1"; exit 1; }
}

python_bin() {
    if [[ -x "$ROOT/.venv/bin/python" ]]; then
        echo "$ROOT/.venv/bin/python"
    else
        echo "python3"
    fi
}

sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        (cd "$(dirname "$1")" && shasum -a 256 "$(basename "$1")" | awk '{print $1}')
    fi
}

# Run a GitHub workflow and echo the run id on stdout (logs go to stderr).
gh_dispatch_and_wait() {
    local workflow="$1"; shift
    if ! command -v gh >/dev/null 2>&1; then
        err "gh CLI is required for CI/release modes: https://cli.github.com/"
        exit 1
    fi
    if ! gh auth status >/dev/null 2>&1; then
        err "gh is not authenticated (run: gh auth login)"; exit 1
    fi
    log "Dispatching workflow ${workflow} with: $*" >&2
    gh workflow run "$workflow" "$@" >/dev/null
    local run_id=""
    for _ in $(seq 1 30); do
        sleep 3
        run_id="$(gh run list --workflow "$workflow" --limit 1 \
            --json databaseId,status --jq '.[0].databaseId' 2>/dev/null || true)"
        [[ -n "$run_id" && "$run_id" != "null" ]] && break
    done
    if [[ -z "$run_id" || "$run_id" == "null" ]]; then
        err "could not find the dispatched run of $workflow"; exit 1
    fi
    log "Waiting for run ${run_id} (gh run watch)…" >&2
    if ! gh run watch "$run_id" --exit-status --interval 20 >&2; then
        err "run ${run_id} failed — inspect with: gh run view ${run_id} --log-failed"
        exit 1
    fi
    echo "$run_id"
}

# ─── mode: local build + verification ────────────────────────────────
run_local() {
    need_cmd uv

    if (( ! SKIP_TESTS )); then
        log "Lint (ruff real-bug checks)…"
        if command -v ruff >/dev/null 2>&1; then
            ruff check --select E,W,F,B --ignore E501,E402 src/freeflix_cli/ tests/
        elif [[ -x "$HOME/.local/bin/ruff" ]]; then
            "$HOME/.local/bin/ruff" check --select E,W,F,B --ignore E501,E402 \
                src/freeflix_cli/ tests/
        else
            uvx ruff==0.17.3 check --select E,W,F,B --ignore E501,E402 \
                src/freeflix_cli/ tests/
        fi
        ok "ruff clean"

        log "Full test suite…"
        local py; py="$(python_bin)"
        if [[ "$py" == "python3" ]]; then
            uv run --with . --with pytest --with pytest-timeout \
                -m pytest -q --timeout=120
        else
            "$py" -m pytest -q --timeout=120
        fi
        ok "tests green"
    else
        warn "tests/lint skipped (--skip-tests)"
    fi

    log "Building the standalone binary (same recipe as CI)…"
    bash scripts/build-binary.sh
    ok "binary built and package data verified: dist/freeflix"

    log "Building the wheel (mirrors the CI packaging smoke test)…"
    uv build --wheel --out-dir "$WORK/wheel" >/dev/null
    local whl; whl="$(ls "$WORK"/wheel/*.whl)"
    "$(python_bin)" - "$whl" <<'PY'
import sys, zipfile
from pathlib import Path

repo = Path.cwd()
names = set(zipfile.ZipFile(sys.argv[1]).namelist())

# DURABLE: derive the expected files from the repository, so any data file
# added later is automatically required in the wheel too.
pkg_data = sorted((repo / "src" / "freeflix_cli" / "data").iterdir())
required = [f"freeflix_cli/data/{p.name}" for p in pkg_data if p.is_file()]
portal_data = sorted((repo / "data").iterdir())
required_portals = [
    f"share/freeflix-cli/data/{p.name}" for p in portal_data if p.is_file()
]

missing = [n for n in required if n not in names]
missing += [n for n in required_portals if not any(m.endswith(n) for m in names)]
if missing:
    print("MISSING from wheel: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)
print(f"OK: wheel carries package data ({len(required)} files) "
      f"+ portal data ({len(required_portals)} files)")
PY
    ok "wheel verified: $(basename "$whl")"
}

# ─── mode: real Windows build on GitHub ──────────────────────────────
run_windows_ci() {
    local run_id
    run_id="$(gh_dispatch_and_wait standalone-binaries.yml)"
    ok "standalone-binaries.yml run ${run_id} succeeded (Linux + Windows + macOS)"

    log "Downloading the built .exe artifact…"
    rm -rf "$WORK/win"; mkdir -p "$WORK/win"
    gh run download "$run_id" --name freeflix-windows-x86_64 \
        --dir "$WORK/win" >/dev/null
    local exe; exe="$(find "$WORK/win" -name '*.exe' | head -n 1)"
    [[ -n "$exe" ]] || { err "no .exe in the downloaded artifact"; exit 1; }
    ok "got $(basename "$exe") ($(du -h "$exe" | cut -f1))"

    log "Verifying the Windows .exe embeds Match package data…"
    bash scripts/check-binary-data.sh "$exe"
    ok "Windows .exe verified (cross-platform PyInstaller archive inspection)"
}

# ─── mode: verify a published release ────────────────────────────────
run_verify() {
    need_cmd gh
    [[ -n "$TAG" ]] || { err "--verify-release needs a TAG (e.g. v2.6.1)"; exit 1; }
    rm -rf "$WORK/release"; mkdir -p "$WORK/release"
    log "Downloading release ${TAG} assets…"
    gh release download "$TAG" --dir "$WORK/release" --pattern 'freeflix-*' --clobber

    local failed=0 verified=0
    while IFS= read -r sums; do
        local dir base expected actual target
        dir="$(dirname "$sums")"; base="$(basename "$sums")"
        expected="$(awk '{print $1}' "$sums")"
        target="$dir/${base%.sha256}"
        if [[ ! -f "$target" ]]; then
            warn "checksum file without matching asset: $(basename "$target")"
            continue
        fi
        actual="$(sha256_file "$target")"
        if [[ "$actual" != "$expected" ]]; then
            err "sha256 MISMATCH: $(basename "$target")"
            failed=1
            continue
        fi
        ok "sha256 OK: $(basename "$target")"
    done < <(find "$WORK/release" -name '*.sha256' -type f)

    # Verify embedded data on every executable asset (Linux, macOS, Windows —
    # PyInstaller archives are readable from any OS).
    while IFS= read -r bin; do
        if bash scripts/check-binary-data.sh "$bin"; then
            verified=$((verified + 1))
        else
            failed=1
        fi
    done < <(find "$WORK/release" -type f ! -name '*.sha256')

    if (( failed )); then
        err "release ${TAG} is NOT healthy (see MISSING lines above)"
        err "Fix it with:  $0 --republish ${TAG}"
        exit 1
    fi
    ok "release ${TAG} healthy: ${verified} binaries embed Match data + checksums OK"
}

# ─── mode: rebuild/re-attach the release binaries ────────────────────
run_republish() {
    need_cmd gh
    [[ -n "$TAG" ]] || { err "--republish needs a TAG (e.g. v2.6.1)"; exit 1; }
    warn "This rebuilds the 3 OS binaries for ${TAG} and re-attaches them to the release."
    local run_id
    run_id="$(gh_dispatch_and_wait binaries.yml -f tag="$TAG")"
    ok "binaries.yml run ${run_id} succeeded"
    log "Verifying the freshly re-attached release assets…"
    run_verify
}

# ─── dispatch ────────────────────────────────────────────────────────
case "$MODE" in
    local)     run_local ;;
    windows-ci) run_windows_ci ;;
    verify)    run_verify ;;
    republish) run_republish ;;
    all)
        run_local
        run_windows_ci
        run_republish
        ;;
esac

ok "Done."
