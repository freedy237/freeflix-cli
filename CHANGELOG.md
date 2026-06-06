# Changelog

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
