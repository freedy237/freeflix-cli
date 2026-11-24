#!/usr/bin/env bash
# Build a standalone FreeFlix executable (no Python needed) into ./dist/.
# Requires uv. Bundles curl_cffi's native lib, package metadata, the package's
# JSON reference data (Match clubs + channel logos) and the JSONC data files
# (source portals + hot-patchable selectors).
#
# NOTE: --collect-submodules ships Python modules only. Without
# --collect-data the frozen binary silently loses
# src/freeflix_cli/data/{clubs,channel_logos}.json, which Match uses for
# curated team names and channel logos — a visible downgrade vs `pip install`.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --with . --with pyinstaller --with lxml \
  pyinstaller --onefile --name freeflix \
  --collect-all curl_cffi \
  --collect-submodules freeflix_cli \
  --collect-data freeflix_cli \
  --hidden-import readchar \
  --copy-metadata readchar --copy-metadata freeflix-cli --copy-metadata curl_cffi \
  --add-data "data/source_portal.jsonc:data" \
  --add-data "data/selectors.jsonc:data" \
  src/freeflix_cli/__main__.py
./dist/freeflix --version
./dist/freeflix --doctor >/dev/null
# Single source of truth (also used by the release/CI workflows): prove the
# frozen bundle really carries Match's reference data + the portal JSONC.
./scripts/check-binary-data.sh ./dist/freeflix
echo "Built: dist/freeflix"
