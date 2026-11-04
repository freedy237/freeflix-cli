# Contributing

FreeFlix is a fork of [autoflix-cli](https://github.com/PaulExplorer/autoflix-cli);
thank you to its author for the original scraping foundation.

## Ground rules

- **French UI, English source.** Every user-facing string goes through
  `t("English source")` and needs an entry in `_FR` (`src/freeflix_cli/i18n.py`).
  `tests/test_i18n_complete.py` fails otherwise.
- **Icons, not emoji.** Use `icon("name")` / `iconify(text)`, never a decorative
  emoji in a menu.
- **One Back = one level.** Handlers keep their own navigation state; Esc and
  the last menu row must return exactly one screen up.
- **No hard-coded colour.** Use `themes.color(role)` or the `ui.py` primitives.
- **Never publish from a dirty tree.** Local mirror first, tests green, then
  the release process in [docs/RELEASE.md](docs/RELEASE.md).

## Development

```bash
uv sync
uv run freeflix
uv run --with pytest --with pytest-cov -m pytest -q
uvx ruff check --select E,W,F,B --ignore E501,E402 src/freeflix_cli/
```

- The suite is offline. Mock HTTP (`_get`, `requests.get`) and `subprocess`
  instead of hitting the network.
- A site change is usually a selector: edit `DEFAULT_SELECTORS` in
  `scraping/resilient.py`, and optionally `data/selectors.jsonc` for a
  release-free hot patch.
- A new provider: add `handlers/<name>.py` + `scraping/<name>.py`, register it
  in `main._register_providers()` with its `supported_languages`, and add a
  parsing test with a saved HTML fixture.

## Adding a fix

1. Reproduce with a test (prefer a focused unit test over a network test).
2. Fix the smallest surface.
3. Run the full suite and ruff.
4. Add the user-visible change to `CHANGELOG.md`.
5. If the change touches one OS only, say so explicitly in the commit message:
   Windows/macOS behaviour cannot be validated by the Linux CI job alone.

## Reporting a broken source

Run `freeflix --doctor --sources` (live search + resolve for every source) and
include the failing source, the error line, and the date. Most breakages are
one selector or one rotated domain.
