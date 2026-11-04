#!/usr/bin/env bash
# Build a standalone FreeFlix executable (no Python needed) into ./dist/.
# Requires uv. Bundles curl_cffi's native lib, package metadata and the JSONC
# data files (source portals + hot-patchable selectors).
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --with . --with pyinstaller --with lxml \
  pyinstaller --onefile --name freeflix \
  --collect-all curl_cffi \
  --collect-submodules freeflix_cli \
  --hidden-import readchar \
  --copy-metadata readchar --copy-metadata freeflix-cli --copy-metadata curl_cffi \
  --add-data "data/source_portal.jsonc:data" \
  --add-data "data/selectors.jsonc:data" \
  src/freeflix_cli/__main__.py
./dist/freeflix --version
./dist/freeflix --doctor >/dev/null
echo "Built: dist/freeflix"
