# Changelog

## 1.8.1

### 🔎 Filter any list with `/`
- Press **`/`** in any menu to type-to-filter a long list (episodes, seasons,
  sources…). Enter picks the highlighted match, Esc clears the filter. The
  status bar shows the hint.

### 🏷️ Episode badges
- Episode rows now show at-a-glance badges: **✓ watched**, **▸NN m resume**
  (you stopped mid-episode), **⬇ downloaded**. Wired into Anime-Sama, Coflix and
  French-Stream episode lists. Watched state is recorded when you finish/play an
  episode.
## 1.8.0

### 🧭 New navigation UI
- **Breadcrumb trail** above every menu — you always see where you are and what
  Esc goes back to: `🏠 Home › Sources › Anime-Sama › Naruto › Saison 2 › VOSTFR`.
  Long trails truncate from the left so the deepest levels stay visible.
- **`?` help overlay** — press `?` in any menu for every keyboard shortcut
  (menus, multi-select, download cancel, mpv/Anime4K keys). Any key closes it.
- **Consistent status bar** at the bottom of every menu:
  `↑/↓ · Entrée : choisir · Échap : retour · ? : aide`.

### 🇫🇷 Full French coverage
- Translated **~40 prompts that were still English** in the French UI, across
  GoldenMS, AniList, Nyaa, Anime-Sama, Coflix, French-Stream and Papystreaming
  (type/season/episode inputs, subtitles, resume prompts, stream picker,
  torrent picker, AniList linking…).

### 🐛 Correctness fixes (full-project audit)
- **Latent wrong-episode bug**: three AniList-update callbacks captured loop
  variables late (B023) — bound at definition now.
- `t()` shadowing in the AniList handler (loop variable named `t`) fixed.
- Mutable default argument in `get_hls_link` removed; `raise … from None` in the
  Cloudflare fallback; unused loop variables renamed.
- All bare excepts were already gone (1.7.9); ruff is now clean on E/W/F/B
  across the whole project (deliberate late imports documented with noqa).
- First-run setup steps renumbered coherently.
## 1.7.9

### 📺 VLC fixes
- **Quiet playback**: VLC no longer floods the terminal with libav/libva/codec
  chatter — only the essentials are shown (its console output is hidden).
- **Respects the chosen quality**: on HLS, VLC used to ramp up to the highest
  variant, ignoring the resolution you picked. It's now capped with
  `--adaptive-maxheight`, so 720p stays 720p.

### 🧹 Internal cleanup (healthier base for 1.8)
- All **bare `except:`** replaced with `except Exception:` (13) — Ctrl-C and real
  errors are no longer swallowed.
- **Network timeouts** added everywhere they were missing (scraper wrappers,
  portal-resolution calls, the Cloudflare fetch helper, GoldenAnime) so a dead
  host can never hang FreeFlix.
## 1.7.8

### 🐧 Linux install fixed (Kubuntu & co)
- The static-build repos for **mpv and aria2 vanished (404)**. Both are no longer
  self-managed on Linux — FreeFlix installs them via the distro **package
  manager** (apt/dnf/pacman/zypper/apk) with a confirmation, then re-checks. No
  more "✗ player (download failed)". **VLC** is installed too (parity with the
  install scripts). ffmpeg stays self-managed (its build still works).

### 🔤 Nerd Font is now a standard dependency
- First-run setup **installs the Nerd Font** on every OS and defaults icons to
  **nerd**. Existing users get it via a one-time upgrade migration.

### ▶️ "Continue from AniList" — back & upgraded
- The home-menu entry is back (shown when an AniList token is set).
- It now has the **same tech as the normal sources**: poster previews (chafa),
  **quality/bitrate analysis**, subtitle search, position-resume, stats, and
  automatic AniList progress sync.

### 😌 Comfort
- **Last server remembered**: the player menu pre-selects the host you used last.
- **Quality/language badges** in the player menu (`[VF]` `[VOSTFR]` + resolution).
- **Toasts**: setting changes confirm with a brief self-dismissing message
  instead of "press Enter".

### 🔧 Other
- The "update available" notice now shows the single **`uv tool upgrade`**
  command (we ship via uv).
## 1.7.7

### ⬇️ No more half-downloaded files in your folder
- Every backend now downloads into the hidden `.temp/` dir; the finished file
  lands in `Downloads/FreeFlix/` (or the season folder) **only at 100%**.
  Previously aria2c wrote the `.mp4` straight into your folder, so a dropped
  connection left a partial file there. Now an interrupted download stays in
  `.temp/` (resumable) and never pollutes your folder.

### ⏸ Resume interrupted downloads
- **My Downloads** now shows an **Interrupted downloads** section listing what
  stopped mid-way (with % for HLS or MB downloaded). Select one to **Resume**
  (picks up where it stopped via aria2 `--continue` / yt-dlp `.ytdl` state) or
  **Delete** the partial. Resume works while the stream link is still valid;
  otherwise re-download it from the source.
- `.temp/` partials are never listed as playable files anymore.
## 1.7.6

### ⎋ Esc now works on Linux too
- The arrow menus read keys via readchar, which on POSIX **blocks on a lone Esc**
  waiting for a 2nd byte (to tell Esc from an arrow sequence) — so Esc appeared
  to do nothing on Linux while working on Windows. Menus now use a raw reader
  that detects a standalone Esc with a 50 ms peek. Esc reliably goes back one
  level (e.g. episode list → season list) on every OS.

### 🪟 Anime4K shaders fixed on Windows (for real this time)
- The actual culprit was **mpv.conf** (loaded on every video at startup), not
  just input.conf: its `glsl-shaders="A:B:C"` line uses ':' which is the wrong
  list separator on Windows (it's ';'), so mpv failed with
  "Cannot open file …A.glsl:/shaders/B.glsl". The startup-launch repair now also
  rewrites mpv.conf to ';' on Windows (':' stays on Linux/macOS).

### 🔤 Nerd Font now renders for existing installs
- Selecting "nerd" when the font was **already installed** previously did nothing
  (it returned early without configuring the terminal). It now sets Windows
  Terminal's font even then, plus a one-time launch check applies it
  automatically if your icon style is already "nerd".
- A small hint at the bottom of the episode multi-select shows "Space: select".
## 1.7.5

### ⬇️ Season downloads
- The episode list now offers a simple **Download** (instead of "Download ALL"):
  pick it, choose the quality, then **multi-select exactly which episodes** to
  grab (Space to toggle, `a` for all). Episodes **already on disk are detected,
  shown locked and skipped**.
- Each season downloads into its **own folder** (`Downloads/FreeFlix/<Series -
  Season>/`) with clean per-episode filenames.
- Fixed the **doubled title** in movie/series filenames (e.g.
  "Meilleurs ennemis - Movie - Meilleurs ennemis").
- Fixed the **batch progress bar** not moving when downloading selected episodes.

### ⎋ Escape = go back, everywhere
- Pressing **Esc** in any menu now steps back one level / cancels — e.g. in the
  episode list it returns to the season list — so you never scroll down to the
  Back row.

### 🌐 Faster posters
- Cover images now go through a resizing CDN (wsrv.nl): anime-sama's ~1.3 MB
  covers on the throttled raw.githubusercontent.com become ~30 KB in ~1 s
  (instead of ~8 s / timing out). Falls back to the original URL.

### 🪟 Windows
- **Nerd Font now actually renders**: installing it also sets Windows Terminal's
  font (`profiles.defaults.font.face`), then prompts to reopen the terminal.
- On first launch, if a Nerd Font is already present, icons default to **nerd**.
- First-run dependency install bar climbs smoothly instead of jumping 20/40/80.

### 🔧 Other
- **Papystreaming** moved to the **EN** sources (its streams are English) and
  renamed (no more "VF").
- **Subtitle download is OFF by default** (opt-in from Settings).
- The default-player names (download/manual/browser) are now translated.
- Removed the **Continue from AniList** home-menu entry.
- Anime4K shader toggle made cross-platform (carried over from 1.7.4).
## 1.7.4

### 🆕 New source: Papystreaming (FR — Films & Séries)
- French TMDB-based catalog with a clean search (titles, posters, year, movie/tv).
- Series show a **selectable seasons/episodes menu** (via Cinemeta) instead of
  typing numbers, with ← Back at each level.
- Streams resolved through the proven shared resolvers (Vidlink/…).

### 🪟 Windows fixes
- **Anime4K shaders now load on Windows.** The toggle joined shader paths with
  `:` (Linux/macOS separator) — on Windows mpv uses `;`, so it failed with
  "Cannot open file …". input.conf now appends each shader individually
  (cross-platform); a migration rewrites existing configs.
- **First-run dependency install bar climbs smoothly** (1%→100%) instead of
  jumping 20/40/80 — it now eases toward the next milestone while each tool
  installs (winget gives no real %).

### 🧭 Home menu
- **Browse sources** moved right after Resume (the main action), before
  History/Downloads/Stats.
## 1.7.3

### ⬇️ Downloads
- **Esc Esc to cancel** a download (single and whole-season batch). The box now
  shows the hint; arrow keys don't count, so it's only a deliberate double-Esc.
- **aria2c progress bar fixed**: the reader kept only progress lines, so aria2c's
  `[#… (X%) …]` line (printed inside a summary block with FILE:/---- junk) is no
  longer overwritten before the UI reads it — the bar climbs live instead of
  sitting on "starting…".
- **Unknown total size** (e.g. sibnet serves the mp4 with no Content-Length):
  show the downloaded amount + speed instead of "starting…".
- **Season download** quality menu now lists the **resolutions** (not the
  players) with an **approximate size per episode**; pick one to download.

### 🧭 Navigation
- Pressing **Esc to leave a search now returns to the source list**, not the
  home menu, so you can pick another source or re-search immediately.

### 🔌 Coflix search
- Rewritten: the query is **URL-encoded** (titles with spaces/accents work),
  non-JSON / errors no longer crash, malformed entries are skipped, image URLs
  are extracted robustly. On HTTP 429 (the site rate-limiting/blocking the
  search) a clear message is shown instead of a misleading "no results".

### 🐍 Python compatibility
- Added `from __future__ import annotations` to every module using `X | Y`
  type unions — fixes import crashes on **Python 3.9** (PEP 604 isn't evaluable
  there at runtime).
- Installer pins a stable **CPython 3.12** and passes `--force`, so re-running
  the one-liner always upgrades existing installs to the latest fixes.

### 🧹 Cleanup
- Fixed latent `NameError`s (`print_warning` / `re` used but not imported),
  removed duplicate i18n keys and dead code (ruff-clean on touched files).

## 1.6.11

### 🌐 French-Stream DNS timeout (fix)
- `french-stream.one` scraper used `DNS_OPTIONS` (DoH via 1.1.1.1) which is
  unreachable on some networks, causing 15s DNS resolution timeouts.
- Removed `curl_options=DNS_OPTIONS` from the french-stream session — now
  uses system DNS instead.

## 1.6.10

### 🎯 PyPI publish fix
- Re-publish v1.6.9 fix with the correct code. The initial v1.6.9 tag
  was pushed before the FlareSolverr-based approach was replaced with
  the simpler `fsschal=1` cookie fix.

### 🎨 Nerd Font auto-detection + install (feat)
- New `detect_nerd_font()` checks whether a Nerd Font (CaskaydiaCove)
  is installed: `fc-list` on Linux/macOS, registry on Windows.
- New `install_nerd_font()` downloads and installs CaskaydiaCove Nerd
  Font automatically per OS (zip + `~/.local/share/fonts` on Linux,
  `brew cask` on macOS, zip + `%LOCALAPPDATA%\Microsoft\Windows\Fonts`
  on Windows).
- In Settings → Icon Style, when "nerd" is selected, FreeFlix now
  detects if a Nerd Font is present and offers to install it if not.

## 1.6.9

### 🔍 French-Stream search not found (fix)
- `french-stream.one` now serves a JS challenge page (status 200) on the
  search endpoint that sets a `fsschal=1` cookie via JavaScript. The
  `search()` function was using `scraper.post()` directly and receiving
  the challenge page instead of results.
- Added `_post()` helper that detects the challenge page by body markers
  and sets the `fsschal=1` cookie on the scraper session automatically
  before retrying. No FlareSolverr needed.

## 1.6.8

### 🎯 Quality selection for downloads (feat)
- When downloading, the HLS quality probe now runs **before** the player
  selection screen, so you can pick the resolution (1080p / 720p / 480p…)
  **before** choosing "download".
- The selected height is passed through to yt-dlp as a `bv*[height<=N]`
  format filter, matching what you'd see in playback.

## 1.6.7

### 🐛 Episode title duplicate in downloads (fix)
- Some providers (notably Coflix) return episode titles that already embed the
  full series + season path (e.g. `"FROM - Saison 4 - Episode 7"` instead of
  just `"Episode 7"`), producing filenames like
  `"FROM - Saison 4 - FROM - Saison 4 - Episode 7.mp4`.
- New `clean_episode_title()` helper strips the series and season prefix from
  the episode title before constructing the download filename.
- 5 new tests covering Coflix full-path, partial prefixes, and edge cases.

## 1.6.6

### 🐍 Python 3.9 compatibility (fix)
- Added `from __future__ import annotations` to `scraping/player.py` to make
  the `str | None` type annotation (PEP 604) work on Python 3.9, which doesn't
  natively support the syntax. Fixes crash on import for Python 3.9 users.

## 1.6.5

### 🐛 Duplicate filename in downloads (fix)
- Season titles that already embed the series name (e.g. Coflix' `"FROM - Saison 4"`
  inside series `"FROM"`) no longer produce filenames like
  `"FROM - FROM - Saison 4 - Ep1.mp4"`. A new `clean_season_title()` helper strips
  the duplicate prefix, matching the existing resume-display logic.

### ⬇️ Download resume after interruption (fix)
- HLS fragments now go to a **stable `~/.temp/<title>/`** directory inside
  `Downloads/FreeFlix/` instead of a random temporary directory. The temp dir is
  **kept** on Ctrl-C / error, so yt-dlp finds its `.ytdl` resume state on the
  next launch and continues where it left off.

### ✅ Tests
- 12 new tests covering both fixes plus edge cases.

## 1.6.4

### ⚡ Instant startup (fix)
- `freeflix` showed nothing for ~2.5 s on launch. Cause: four **remote config
  files were fetched synchronously at import time** (players/new_url/kakaflix
  overrides + source portals), blocking before anything could display.
- These are optional upstream overrides of bundled defaults, so we now apply
  the **defaults instantly** and pull the remote overrides in a **background
  thread** kicked off at launch. They merge in (in place) well before any
  playback needs them. Import time dropped from ~3.8 s to ~0.6 s.
- Trimmed the splash sequence a touch too.

## 1.6.3

### ⬇️ Real-time download progress (fix)
- HLS now downloads with yt-dlp's **native parallel-fragment** downloader
  (`--concurrent-fragments 16`) instead of aria2c. With aria2c, yt-dlp only
  reported overall progress at the very end, so the bar sat on "starting…" then
  jumped to 100%. Native reports `(frag a/b)` **continuously**, so the bar now
  climbs **live** from the moment the download starts.
- Just as fast for HLS (16 fragments in parallel saturate the link) and still
  leaves the Downloads folder clean (fragments go to a temp dir, deleted after).
- aria2c is still used for direct `.mp4` (real-time single-file % + speed).

## 1.6.2

### ⬇️ Downloads
- **Speed back, clutter gone**: HLS uses yt-dlp **+ aria2c (x16)** again for
  throughput, but every fragment + the `.part` file now go to a **temp dir**
  (`-P temp:`) that's deleted afterwards — the Downloads folder only ever sees
  the final `.mp4`.
- **Rock-stable progress bar**: the fraction is driven only by yt-dlp's overall
  `(frag a/b)` count and is monotonic (never jumps backward); aria2c's
  interleaved per-fragment lines feed the **speed** readout only.

### 🖥️ Download box is now purely responsive
- The progress box renders in the alternate screen (`screen=True`), centered:
  resizing reflows it cleanly with no offset/leftover, and it erases itself on
  exit.

## 1.6.1

### 🐛 Downloads
- **No more fragment clutter**: HLS now uses yt-dlp's native parallel-fragment
  downloader (`--concurrent-fragments 16`) instead of handing each fragment to
  aria2c — which was spawning hundreds of `*.part-FragN` / `*.aria2` files in
  the FreeFlix folder. One `.part` file now, renamed to one `.mp4`.
- **Stable progress bar**: it tracks the overall download (`frag a/b`), not the
  tiny per-fragment files, so it starts clean and climbs smoothly to 100%.
- Leftover fragment/temp clutter is swept before and after every download.
- aria2c is still used for direct .mp4 (single file, multi-connection).

### 🔙 Back navigation everywhere
- Every season / language / episode picker now has a **← Back** that steps up
  one level (episode → language → season → out), so you can back out without
  finishing the whole flow. Applied to Anime-Sama, Coflix, French-Stream,
  French-Manga, GoldenMS, GoldenAnime.

### ✨ Launch
- The startup splash now plays a short, smooth 0 → 100% sequence instead of
  flashing past.

## 1.6.0

A big release — everything that landed since 1.5.9.

### ✨ Browse with posters (preview pane)
- Live **preview pane** (poster + title + genres / metadata) beside the result
  list on **every** source, updating as you navigate; type to filter.
- Covers per source: Anime-Sama, Coflix, French-Stream, French-Manga (TMDB
  thumbnails), GoldenMS (Cinemeta), GoldenAnime (AniList).
- Tuned for fluidity: per-URL image cache (no re-download on resize), two
  thread pools (downloads ×6 / chafa render ×2), on-demand repaint
  (`auto_refresh` off), debounced re-warm, fixed-height centered panel (no
  jump), animated spinner, footer key hints, narrow-terminal fallback.

### 🗂️ Grouped source menu
- Sources are now grouped: **Anime / Manga** first, then **Films & Séries**,
  under section headers.

### 📊 Progress bars (themed `▰▰▱`)
- New `progress` module shared across the app.
- **Launch splash** with an animated loading bar.
- **Dependency-install** progress (big FreeFlix + bar tracking each tool).
- **Download bar** that filters yt-dlp / aria2c logs and shows **speed +
  downloaded/total + ETA** instead.

### 🖥️ Full-screen, resize-safe UI
- Header banners render inside the Live region; home & source menus use the
  alternate screen — no more headers/posters stacking or wrapping on resize.
- Full-screen, resize-safe search inputs.

### 🔌 Sources & extractors (major overhaul)
- **GoldenMS**: new multi-extractor backend (Hexa, Mapple, Videasy, Vidlink,
  Xpass) with subtitles and per-source quality labels.
- **GoldenAnime**: new extractors (AllAnime with AES decryption, Animetsu,
  AniZone, Sudatchi) with subtitles.
- **French-Stream**: rebuilt scraper (movies + series, per-language episodes,
  robust posters).
- **Coflix**: rides a `cf_clearance` cookie, clean "protected by Cloudflare"
  message with a token tip, and always-present `og:image` covers.
- **player.py**: thread-local `curl_cffi` sessions so parallel extraction is
  safe; thread-local player config; **vidmoly** fixed (live domain is `.net`;
  parked `.to/.biz/.me` remapped).

### ▶️ Playback & downloads
- **Stream quality analysis** before playing: per-quality resolution + bitrate
  via ffprobe; labels like `1080p ~5.0 · 720p ~2.5 Mbps`. Bounded time budget
  so a slow host never freezes the menu.
- Faster downloads: **yt-dlp + aria2c** (16 connections) for HLS, 16 parallel
  fragments as fallback.
- **Subtitle download fixed**: gzip + zip decompression.
- **Subtitle search on all sources** (Cinemeta / IMDb lookup), toggleable.
- Data-used meter after playback.

### ☁️ Cloudflare handling
- New `cloudflare` module: `cf_get` cascade with a `cf_clearance` cookie and
  **FlareSolverr** auto-solve.
- **3 retries + system-DNS (no-DoH) fallback** for "connection reset" / DNS
  hiccups.
- Settings: paste a `cf_clearance` token; configurable FlareSolverr URL.

### ⚙️ Setup & platform
- **Resumable dependency gate**: caches an "all good" flag; until then each
  launch re-checks and installs only what's missing.
- **`install.ps1` rewritten**: pure ASCII (fixes the Windows PowerShell 5.1
  parse error), idempotent, installs **Windows Terminal + CaskaydiaCove Nerd
  Font**, writes a completion marker.
- Nerd Font option added to `install.sh` / `install-mac.sh`.
- **FlareSolverr auto-install** (Podman-first, `systemd --user` persistence).
- Settings: analyze-players toggle, subtitle-search toggle, icon style
  (emoji / Nerd Font), themed About panel.

### 🐛 Fixes & robustness
- **Removed Wiflix** entirely (handler, scraper, objects).
- Graceful handling of network failures in source flows — search / load no
  longer crash the app.
- Central emoji → Nerd Font conversion (`iconify`); no hardcoded emoji.
- Resize no longer stacks headers or pushes posters out of their frame.

### 📦 Install / upgrade
```
pip install -U freeflix-cli      # or: pipx upgrade freeflix-cli / uv tool upgrade freeflix-cli
```
