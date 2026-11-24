#!/usr/bin/env bash
# Verify that a built FreeFlix executable REALLY embeds the reference data the
# app reads from the package (Match clubs.json + channel_logos.json today, and
# automatically ANY file later added to src/freeflix_cli/data/) plus the JSONC
# portal/selector files from data/.
#
# Why: PyInstaller's --collect-submodules ships Python modules only. A build
# that forgets --collect-data still starts, --version/--doctor still pass, and
# Match silently loses its curated team names + channel logos — a functional
# downgrade users blame on the sources (the reported "Windows version does
# less than Linux" bug of 2.6.1).
#
# DURABILITY: the required list is DERIVED FROM THE REPOSITORY, never
# hard-coded here. Adding a data file makes it mandatory in every binary;
# removing one removes the requirement. No list to keep in sync, forever.
#
# This helper is the SINGLE SOURCE OF TRUTH used by:
#   * scripts/build-binary.sh              (local builds)
#   * .github/workflows/binaries.yml       (release builds, all 3 OS)
#   * .github/workflows/standalone-binaries.yml (CI validation of every OS)
#   * scripts/rebuild-binaries.sh          (release verification/republish)
#
# Usage: scripts/check-binary-data.sh <path-to-binary>
#
# Environment:
#   PYI_ARCHIVE_VIEWER   command used to list the PyInstaller archive
#                        (default: pyi-archive_viewer if on PATH, else
#                         `uv run --with . --with pyinstaller --with lxml …`)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BIN_ARG="${1:-}"
if [[ -z "$BIN_ARG" || ! -f "$BIN_ARG" ]]; then
    echo "usage: $0 <path-to-freeflix-binary>" >&2
    exit 2
fi
# Resolve before cd: callers usually pass a repo-relative path (dist/freeflix).
BIN="$(cd "$(dirname "$BIN_ARG")" && pwd)/$(basename "$BIN_ARG")"
cd "$REPO_ROOT"

PKG_DATA_DIR="$REPO_ROOT/src/freeflix_cli/data"
PORTAL_DATA_DIR="$REPO_ROOT/data"
if [[ ! -d "$PKG_DATA_DIR" ]]; then
    echo "ERROR: $PKG_DATA_DIR not found (run from the FreeFlix repo)" >&2
    exit 2
fi

# Git Bash/MSYS hands POSIX paths to native Windows tools; the archive viewer
# is a native exe, so give it the Windows form (Linux/macOS keep theirs).
BIN_VIEW="$BIN"
case "$(uname -s 2>/dev/null || echo)" in
    MINGW*|MSYS*|CYGWIN*)
        BIN_VIEW="$(cygpath -w "$BIN" 2>/dev/null || printf '%s' "$BIN")"
        ;;
esac

LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT

viewer() {
    if [[ -n "${PYI_ARCHIVE_VIEWER:-}" ]]; then
        # shellcheck disable=SC2086  # deliberate word splitting of the command
        $PYI_ARCHIVE_VIEWER -l "$BIN_VIEW"
    elif command -v pyi-archive_viewer >/dev/null 2>&1; then
        pyi-archive_viewer -l "$BIN_VIEW"
    else
        uv run --with . --with pyinstaller --with lxml \
            pyi-archive_viewer -l "$BIN_VIEW"
    fi
}

if ! viewer > "$LIST.raw" 2>/dev/null; then
    echo "ERROR: could not list the PyInstaller archive of $BIN" >&2
    echo "       (is this really a FreeFlix standalone binary?)" >&2
    exit 1
fi
# PyInstaller's Windows builds list entries with backslashes (and the console
# may emit CRLF). Normalise once so ONE pattern works on every OS/runner.
tr -d '\r' < "$LIST.raw" | sed -e 's|\\|/|g' -e 's|//*|/|g' > "$LIST"
rm -f "$LIST.raw"

missing=()
required=0
# Every file shipped in the package data dir is mandatory in the binary.
while IFS= read -r path; do
    rel="${path#"$PKG_DATA_DIR"/}"
    required=$((required + 1))
    if ! grep -Fq "freeflix_cli/data/$rel" "$LIST"; then
        missing+=("freeflix_cli/data/$rel")
    fi
done < <(find "$PKG_DATA_DIR" -type f | sort)

# Every root data/ file (portals, hot-patchable selectors) too.
while IFS= read -r path; do
    rel="${path#"$PORTAL_DATA_DIR"/}"
    required=$((required + 1))
    if ! grep -Fq "data/$rel" "$LIST"; then
        missing+=("data/$rel")
    fi
done < <(find "$PORTAL_DATA_DIR" -maxdepth 1 -type f | sort)

if (( required == 0 )); then
    echo "ERROR: no data files found in the repository — refusing to pass" >&2
    exit 2
fi

if (( ${#missing[@]} )); then
    echo "MISSING from $(basename "$BIN"):" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    cat >&2 <<'EOF'
--------------------------------------------------------------
This binary would start, but the app would silently lose data
(Match club names/logos, portal URLs, selectors).
Rebuild with:  --collect-data freeflix_cli
         and:  --add-data "data/source_portal.jsonc:data"
         and:  --add-data "data/selectors.jsonc:data"
--------------------------------------------------------------
EOF
    exit 1
fi

echo "OK: embedded data complete in $(basename "$BIN") ($required files required)"
