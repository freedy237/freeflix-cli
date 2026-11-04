# Architecture

FreeFlix is a terminal client: it scrapes streaming sites, resolves a playable
stream, serves it through a local proxy when the CDN needs custom headers, and
hands it to mpv/VLC — or downloads it with yt-dlp/aria2c.

```
freeflix (console script)
└── cli.py                  fast flags (--version/--help/--doctor) — no heavy import
    └── main.py             logging, dependency gate, splash, home loop, settings
        ├── setup_assistant first-run installs, mpv config, Anime4K, migrations
        ├── update_checker  PyPI check + upgrade with the original installer
        ├── providers_registry + handlers/*   one flow per source
        │   └── scraping/*                    HTML/JSON parsing, extractors
        ├── player_manager  player choice, quality/bitrate probe, downloads
        │   └── proxy.py    127.0.0.1 HLS/MP4 proxy, header injection, resume
        └── progress.py     splash, download bars, batch view, Esc cancellation
```

## Source pipeline

`search → season/language → episode → player list → stream URL → player/proxy`

1. **Handlers** own the navigation for one provider (search loop, season picker,
   episode picker, resume from history) and return to their caller on Back.
2. **Scraping** modules own the HTML/JSON parsing and the stream extractors.
   Fragile selectors live in `DEFAULT_SELECTORS` (`scraping/resilient.py`) and
   can be repaired without a release through `data/selectors.jsonc`.
3. **player_manager** dedupes players, probes quality/bitrate (HLS variants,
   DASH, ffprobe), then launches mpv/VLC/browser or downloads.
4. **proxy** rewrites manifests/segments to `127.0.0.1`, injects the per-host
   headers, re-signs expired CDN URLs, and streams with Range resume.

## Where data lives

| Path | Content |
|---|---|
| `~/.local/share/AutoFlixCLI/progress.json` | history, follows, positions, settings, AniList token (mode 0600) |
| `~/.cache/AutoFlixCLI/covers/` | persistent poster cache |
| `~/.cache/AutoFlixCLI/http/` | HTTP cache (TTL, pruned in background) |
| `~/.cache/AutoFlixCLI/origins.json` | resolved site mirrors (24 h) |
| `~/.config/freeflix/mpv/` | dedicated mpv config, scripts, shaders |
| `~/.cache/freeflix-cli/freeflix.log` | rotating log (`--verbose` also prints) |
| `~/Downloads/FreeFlix/` | published downloads; staging in `.temp/` |

The `AutoFlixCLI` names are inherited from the upstream fork and kept for
backward compatibility: renaming them would orphan every existing install.

## Hot-patchable configuration

- `data/source_portal.jsonc` — authoritative site mirrors; bundled, fetched
  from `raw.githubusercontent.com`, then overridden by
  `~/.config/freeflix/source_portal.jsonc`.
- `data/selectors.jsonc` — CSS selector overrides, loaded locally then
  refreshed remotely. The baked-in defaults are always the fallback.

When a site changes, a one-line selector patch can ship through `main` without
a PyPI release.

## Design system

`themes.py` maps semantic roles (`accent`, `text`, `surface`, `border_soft`,
`selection`, …) to colours; `ui.py` exposes the primitives (`wordmark`, `rule`,
`section`, `panel`, `chip`); `neon.py` draws the animated Cinema Noir frame.
No widget hard-codes a hex colour outside the brand mark.

## Tests

`tests/` is offline by design (mocked HTTP/subprocess). The real network is
exercised only by `freeflix --doctor --sources` and `tools/audit_providers.py`.
`tests/test_i18n_complete.py` scans the AST: every `t("…")` key must exist in
`_FR`, and every user-facing literal must be wrapped in `t()`.
