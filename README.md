# FreeFlix CLI 🍿

> Watch movies, series and anime from your terminal — multi-language, multi-source, no browser, no ads.

**FreeFlix** is a hardened, feature-extended fork of [autoflix-cli](https://github.com/PaulExplorer/autoflix-cli) by PaulExplorer. All upstream functionality is preserved ; on top of that, FreeFlix ships :

- A second player (**Haruna**, the KDE mpv-based GUI) ;
- A complete **download backend** (yt-dlp for HLS, aria2c for direct mp4, with quality selection 480p/720p/1080p) ;
- **Batch "download whole season"** ;
- **Position-in-episode resume** (mpv lua hook + tracker) ;
- **AniList sync** on watch / mark-as-watched ;
- **OpenSubtitles fallback** when a source has no subtitle ;
- **Parallel multi-episode downloads** (1–4 workers) ;
- **Daily new-episode notifications** via systemd timer + libnotify ;
- A **Nyaa torrent provider** (downloads via aria2 BitTorrent) ;
- A **Local Downloads browser** in the home menu ;
- **Anime4K Mode A_VL** shaders pre-bundled (toggle CTRL+1 / CTRL+0) ;
- **French localisation** of the whole UI (auto-switched based on language pref) ;
- Multi-mirror portal fallback + `website_origin` caching (24 h TTL) ;
- Multiple **bug fixes** : 403 on `/catalogue/?search=` (animes-sama.fr refactor), double-slash legacy URLs in history, settings-menu exit loop, ffmpeg infinite-reconnect at byte 1506, Videasy/Vidlink Referer not propagated, history resume silent-failure, and more.

> ⚠️ FreeFlix is a community fork. The original project is **autoflix-cli** by PaulExplorer ; all credit goes to him for the underlying scraping work and architecture. FreeFlix exists only to consolidate the fixes and features I personally needed.

---

## ✨ What FreeFlix gives you

| | Feature |
|---|---|
| 🎬 | Stream movies, series and anime in **VF / VOSTFR / VA / VJ / VKR / VCN** |
| 📥 | Download single episodes or **entire seasons** to `~/Downloads/FreeFlix/` |
| ▶️ | **Resume at the exact second** you left off (mpv only) |
| 🔄 | **AniList sync** : mark-as-watched on AniList automatically |
| 📝 | **OpenSubtitles** fallback when a source has no subs |
| ⚡ | **Parallel downloads** (up to 4 concurrent episodes) |
| 🔔 | **Daily notifications** when new episodes drop |
| 🌊 | **Nyaa.si torrents** (high-quality anime releases) |
| 🌐 | **6 streaming sources** : Anime-Sama, GoldenAnime, GoldenMS, Coflix, French-Stream, Nyaa |
| 🎮 | **5 player backends** : mpv, Haruna, VLC, browser, download-only |
| 🇫🇷 | **French UI** : the whole CLI is in French when language is set to FR |
| 🛡 | **Anti-crash mpv config** : ytdl-hook off, gpu renderer, no infinite reconnect |
| 🎨 | **Anime4K** pre-bundled with runtime toggle CTRL+1 / CTRL+0 |

---

## 📦 Installation

### Linux (Fedora, Debian/Ubuntu, Arch, openSUSE, Alpine)

```bash
git clone https://github.com/freedy237/freeflix-cli.git
cd freeflix-cli
chmod +x scripts/install.sh
./scripts/install.sh
```

The script detects your distro and installs : `mpv`, `haruna`, `yt-dlp`, `ffmpeg`, `aria2`, `libnotify`, Python deps, then the `freeflix` command via `uv` (preferred) or `pipx`.

### macOS

```bash
git clone https://github.com/freedy237/freeflix-cli.git
cd freeflix-cli
chmod +x scripts/install-mac.sh
./scripts/install-mac.sh
```

Uses Homebrew for system deps. **IINA** is installed in place of Haruna (Haruna isn't on macOS).

### Windows (10/11)

Open PowerShell as a regular user :

```powershell
git clone https://github.com/freedy237/freeflix-cli.git
cd freeflix-cli
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Uses `winget` for system deps. `mpv.net` is installed (the maintained Windows port of mpv).

### Manual / from PyPI source

```bash
# Pre-requisites (whatever package manager you use) :
#   mpv  yt-dlp  ffmpeg  aria2  libnotify  python>=3.9

# Then :
pip install --user .
# OR
uv tool install .
# OR
pipx install .
```

---

## 🚀 Usage

```bash
freeflix
```

That's it. The menu walks you through everything.

### Common keyboard shortcuts in mpv / Haruna

| Key | Action |
|---|---|
| **CTRL + 1** | Enable Anime4K Mode A_VL |
| **CTRL + 0** | Disable Anime4K |
| **`#`** | Cycle audio track |
| **`j`** | Cycle subtitle track |
| **`_`** (Shift + `-`) | Cycle video track |
| **ALT + V** | Cycle video track (alias) |
| **ALT + 1 / 2 / 3** | Force video track #1 / #2 / #3 |
| **ALT + T** | Show track diagnostics |
| **`i`** | Toggle mpv stats overlay |

### Settings menu

`freeflix → ⚙ Settings (AniList)` exposes :

- **AniList Token** — paste the OAuth token from anilist.co to enable sync ;
- **Language** — switches the UI (FR / EN) and default subtitle language ;
- **Default Player** — mpv / vlc / haruna / browser / download / manual ;
- **Download Quality** — auto / 1080 / 720 / 480 ;
- **OpenSubtitles API Key** — register free at [opensubtitles.com/en/consumers](https://www.opensubtitles.com/en/consumers) ;
- **Parallel Downloads** — number of concurrent batch workers (1–4) ;
- **Daily New-Episode Notifications** — enables a `systemd --user` timer that scans Anime-Sama history once a day.

---

## 🛠 What got fixed vs. upstream autoflix-cli

| Bug | Fix |
|---|---|
| `403` on anime-sama portal after `anime-sama.pw` shutdown | Override to `animes-sama.fr` + local `source_portal.jsonc` |
| `404` on `/catalogue/?search=…` (new site rejects trailing slash) | Strip the slash + URL-encode the query |
| Search results parser broken (no more `<h2>`) | Fall back to `<div class="card-title">` |
| Season list empty (no more `panneauAnime()` JS) | Detect seasons via `<a href="/catalogue/<slug>/<season>">` |
| Episode list empty (no more `episodes.js` endpoint) | Fetch `<season>/<lang>` HTML and parse inline `var epsN = […]` |
| `parse_episodes_from_js` only matched single quotes | Now accepts single AND double quotes |
| History entries with `//` in season URL → resume silently exits | `_absolutize()` collapses repeated slashes |
| Settings menu : choosing options 0/1 immediately closes the menu | Refactor stray `if`s into a proper `if/elif/elif/else` chain |
| Videasy/Vidlink 502 Bad Gateway in proxy | Propagate `selection["headers"]` (Origin + Referer) all the way through |
| mpv infinite reconnect loop at byte 1506 | Remove `stream-lavf-o=reconnect=…` ; rely on the proxy retry |
| mpv ytdl-hook crashes on autoflix proxy URLs | `ytdl=no` in `mpv.conf` |
| Vulkan/`gpu-next` instability on Mesa | `vo=gpu` (stable renderer) |
| DNS-over-HTTPS timeouts (1.1.1.1) | Automatic fallback to system DNS |

## 🆕 What's new in v1.0

- 🎮 **Haruna** added as a player option (mpv + GUI = same engine, nicer UX) ;
- 📥 **Download** option in every player menu — yt-dlp for HLS, aria2c for direct mp4, sane defaults ;
- 📥 **Batch "Download ALL episodes"** in the anime-sama flow ;
- ▶️ **Position-in-episode resume** via mpv lua hook ;
- 🔄 **AniList writeback** on mark-as-watched ;
- 📝 **OpenSubtitles** fallback (requires free API key) ;
- ⚡ **Parallel downloads** (configurable 1–4 workers) ;
- 🔔 **Daily new-episode notifications** (systemd `--user` timer) ;
- 🌊 **Nyaa torrent provider** (aria2c BitTorrent mode) ;
- 📁 **My Downloads** menu in the home (local file browser + play) ;
- ✓ **Mark an episode as watched (no play)** ;
- 🌐 **Multi-portal fallback** : list of mirrors per source, tried in order ;
- 💾 **Portal URL cache** (24 h TTL) ;
- 🎨 **Anime4K Mode A_VL** pre-bundled (toggle CTRL+1 / CTRL+0) ;
- 🇫🇷 **French localisation** of the whole UI ;
- 🛡 Stability-first **mpv.conf** (anti-crash) shared between mpv and Haruna.

---

## 🔍 Project layout

```
freeflix-cli/
├── src/freeflix_cli/
│   ├── main.py                 # entry point (`freeflix` command)
│   ├── tracker.py              # local progress / settings store
│   ├── player_manager.py       # mpv/vlc/haruna/download dispatcher
│   ├── i18n.py                 # FR/EN translations
│   ├── subtitles.py            # OpenSubtitles client
│   ├── notifications.py        # daily scan + systemd setup
│   ├── handlers/               # per-provider flows
│   └── scraping/               # site-specific scrapers
├── config/
│   ├── mpv.conf                # anti-crash + Anime4K config (shared)
│   ├── input.conf              # CTRL+1 / CTRL+0 Anime4K toggles
│   └── autoflix_position.lua   # position-resume mpv script
├── scripts/
│   ├── install.sh              # Linux multi-distro
│   ├── install-mac.sh          # macOS (Homebrew)
│   └── install.ps1             # Windows (winget)
├── data/
│   └── source_portal.jsonc     # portal URL overrides
├── pyproject.toml
├── LICENSE                     # GPL v3 (inherited from upstream)
└── README.md
```

---

## 🤝 Credits

- **Original project** : [autoflix-cli](https://github.com/PaulExplorer/autoflix-cli) by [PaulExplorer](https://github.com/PaulExplorer) — all the heavy scraping lift comes from there.
- **Anime4K shaders** : [bloc97/Anime4K](https://github.com/bloc97/Anime4K).
- **mpv** & **Haruna** : their respective authors.
- **GitHub: [@freedy237](https://github.com/freedy237)** — fork maintainer.

## 📜 License

GNU General Public License v3.0 — same as upstream. See [LICENSE](./LICENSE).

---

## 🇫🇷 Résumé en français

FreeFlix est un fork stabilisé d'autoflix-cli avec :

- 5 lecteurs (mpv, Haruna, VLC, navigateur, download-only) ;
- Téléchargement vidéo (yt-dlp / aria2c, choix qualité, batch saison complète) ;
- Reprise à la seconde près dans mpv ;
- Sync AniList, fallback OpenSubtitles ;
- Téléchargements parallèles + notifications quotidiennes ;
- Source Nyaa torrents en plus ;
- UI 100 % traduite en français ;
- Config mpv anti-crash + Anime4K déjà préinstallé ;
- Tous les bugs liés au refacto d'animes-sama.fr de mai 2026 fixés.

Installer : clone le repo, lance `scripts/install.sh` (Linux), `scripts/install-mac.sh` (macOS) ou `scripts/install.ps1` (Windows), puis tape `freeflix`.
