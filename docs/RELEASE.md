# Release process

The release is driven by a tag. `release.yml` refuses to publish unless the
tagged commit passes the suite, the lint, and `pyproject.version == tag`.

## 1. Prepare

1. Bump the version in **both** places (the test `test_code_version_matches_pyproject`
   enforces it):
   - `pyproject.toml` → `[project].version`
   - `src/freeflix_cli/install_health.py` → `CODE_VERSION`
   - `uv.lock` → the `freeflix-cli` package entry
2. Add a `CHANGELOG.md` section. The GitHub release notes are generated from
   the git log, so keep commit subjects readable.
3. Run the full gate:

```bash
uv run --with pytest --with pytest-cov -m pytest -q
uvx ruff check --select E,W,F,B --ignore E501,E402 src/freeflix_cli/
```

4. Install the exact tree locally and smoke-test it **before** tagging:

```bash
uv tool install --reinstall .
freeflix --version
freeflix --doctor
```

## 2. Tag and publish

```bash
git add -A
git commit -m "release 2.1.0: <one-line summary>"
git tag -a v2.1.0 -m "FreeFlix 2.1.0"
git push origin main
git push origin v2.1.0
```

The tag starts `Release`:

1. `test` job — ruff, version check, pytest.
2. build sdist/wheel, `twine check`, publish to PyPI (OIDC, no token).
3. create the GitHub Release with the wheel + sdist attached.
4. dispatch `Binaries` (`workflow_dispatch`, tag input) to build
   Linux/Windows/macOS executables and attach them to the same release.

Why the dispatch step: a `release: published` event created with
`GITHUB_TOKEN` does **not** start another workflow. `workflow_dispatch` is
explicitly allowed with that token, so `binaries.yml` is now triggered from
`release.yml` instead of listening to `release.published` alone.

## 3. Verify

```bash
# GitHub Actions: Release + Binaries green
curl -s https://pypi.org/pypi/freeflix-cli/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
uv tool upgrade freeflix-cli
freeflix --version
```

If PyPI accepted the upload but a later step failed, the version is burnt:
publish the fix as the next patch version — never re-tag.

## Local mirror (maintainer workflow)

To test unmerged work without touching PyPI:

```bash
uv tool install --reinstall --no-cache /path/to/freeflix-cli
freeflix
```

`freeflix --doctor` shows the module path and confirms the code version matches
the package metadata, which catches a stale mirror install.

## Standalone binaries

`binaries.yml` builds with PyInstaller on Linux, Windows and macOS arm64. The
JSONC data files are bundled with `--add-data` and read from `sys._MEIPASS`
(see `scraping/config.py` and `scraping/resilient.py`). The smoke test runs
`--version` **and** `--doctor`, so a bundle missing rich/curl_cffi fails in CI
instead of at the user's first launch.
