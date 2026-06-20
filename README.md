# FreeFlix CLI 🍿

[![PyPI version](https://img.shields.io/pypi/v/freeflix-cli.svg?color=blue)](https://pypi.org/project/freeflix-cli/)
[![Python](https://img.shields.io/pypi/pyversions/freeflix-cli.svg)](https://pypi.org/project/freeflix-cli/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

> Watch movies, series and anime from your terminal — multi-language, multi-source, no browser, no ads.

**FreeFlix** is a hardened, feature-extended fork of [autoflix-cli](https://github.com/PaulExplorer/autoflix-cli) by PaulExplorer. All upstream functionality is preserved ; on top of that, FreeFlix ships :

> 🆕 **v1.7.1** — massive code cleanup : unused imports removed, AutoFlix upstream references removed, legacy remote config fetches eliminated. Faster startup, smaller footprint.


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
| 🌐 | **6 streaming sources** : Anime-Sama, GoldenAnime, French-Manga, GoldenMS, French-Stream, Nyaa |
| 🎮 | **4 player backends** : mpv, VLC, browser, download-only |
| 🇫🇷 | **French UI** : the whole CLI is in French when language is set to FR |
| 🛡 | **Anti-crash mpv config** : ytdl-hook off, gpu renderer, no infinite reconnect |
| 🎨 | **Anime4K** pre-bundled with runtime toggle CTRL+1 / CTRL+0 |
| 🩺 | **`freeflix --doctor`** system diagnostic (check deps, config, network) |

---

## 📦 Installation

### 🚀 One-liner (anything with Python ≥ 3.9)

No git, no package manager, no sudo needed. Just Python (or PowerShell on Windows).

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/freedy237/freeflix-cli/main/scripts/install.py | python3

# Windows (PowerShell)
powershell -c "iwr -useb https://raw.githubusercontent.com/freedy237/freeflix-cli/main/scripts/install.ps1 | iex"
```

This installs `uv` if missing, then `freeflix-cli`.

### From PyPI (if you already have the system deps)

If `mpv`, `yt-dlp`, `ffmpeg`, `aria2` and `libnotify` are installed :

```bash
uv tool install freeflix-cli     # recommended
# or
pipx install freeflix-cli
# or
pip install --user freeflix-cli
```

Then :

```bash
freeflix
```

### Linux (install script — system deps + Anime4K shaders)

```bash
git clone https://github.com/freedy237/freeflix-cli.git
cd freeflix-cli
chmod +x scripts/install.sh
./scripts/install.sh
```

### macOS (install script — system deps + Anime4K shaders)

```bash
git clone https://github.com/freedy237/freeflix-cli.git
cd freeflix-cli
chmod +x scripts/install-mac.sh
./scripts/install-mac.sh
```

### Windows (install script — system deps + Anime4K shaders)

```powershell
git clone https://github.com/freedy237/freeflix-cli.git
cd freeflix-cli
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

### From source (developer mode)

```bash
git clone https://github.com/freedy237/freeflix-cli.git
cd freeflix-cli
uv pip install -e .
```

---

## 🚀 Usage

```bash
freeflix
```

That's it. The menu walks you through everything.

### Common keyboard shortcuts in mpv

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

### Hybrid laptops (Intel/AMD iGPU + Nvidia dGPU)

If you're on a Linux Optimus laptop, FreeFlix detects the dGPU (Nvidia via `nvidia-smi`, AMD via `lspci`) and routes mpv onto it automatically (no FPS drop with Anime4K). To also have this when launching `mpv` standalone (outside FreeFlix), copy the wrapper :

```bash
cp scripts/wrappers/mpv ~/.local/bin/mpv
chmod +x ~/.local/bin/mpv
```

(Make sure `~/.local/bin` is in your `$PATH` before `/usr/bin`.)
The Linux `install.sh` does this for you when it detects an Nvidia card.

### Settings menu

`freeflix → ⚙ Settings (AniList)` exposes :

- **AniList Token** — paste the OAuth token from anilist.co to enable sync ;
- **Language** — switches the UI (FR / EN) and default subtitle language ;
- **Default Player** — mpv / vlc / browser / download / manual ;
- **Download Quality** — auto / 1080 / 720 / 480 ;
- **OpenSubtitles API Key** — register free at [opensubtitles.com/en/consumers](https://www.opensubtitles.com/en/consumers) ;
- **Parallel Downloads** — number of concurrent batch workers (1–4) ;
- **Daily New-Episode Notifications** — enables a `systemd --user` timer that scans Anime-Sama history once a day.

---

## 🔍 Project layout

```
freeflix-cli/
├── src/freeflix_cli/
│   ├── main.py                 # entry point (`freeflix` command)
│   ├── tracker.py              # local progress / settings store
│   ├── player_manager.py       # mpv/vlc/download dispatcher
│   ├── i18n.py                 # FR/EN translations
│   ├── subtitles.py            # OpenSubtitles client
│   ├── notifications.py        # daily scan + systemd setup
│   ├── handlers/               # per-provider flows
│   └── scraping/               # site-specific scrapers
├── config/
│   ├── mpv.conf                # anti-crash + Anime4K config (shared)
│   ├── input.conf              # CTRL+1 / CTRL+0 Anime4K toggles
│   └── freeflix_position.lua   # position-resume mpv script
├── scripts/
│   ├── install.py              # cross-platform one-liner installer
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
- **mpv** : their respective authors.
- **GitHub: [@freedy237](https://github.com/freedy237)** — fork maintainer.

## ⚠️ Disclaimer

This notice is to inform you that **FreeFlix** functions strictly as an automated search tool and specialized browser. It fetches video file metadata and links from the internet in a manner similar to any standard web browser.

- **No Hosting:** FreeFlix does not host, store, or distribute any media files or copyrighted content. All content accessed through this tool is hosted by independent third-party websites.
- **DMCA Compliance:** This software does not violate the provisions of the Digital Millennium Copyright Act (DMCA) as it only provides access to publicly available links and does not store copies of any content on its own servers.
- **User Responsibility:** The use of this software and the legality of streaming content are the sole responsibility of the user, based on their respective country's or state's laws.
- **Copyright Holders:** If you believe any content accessed through this tool violates your intellectual property, please contact the actual file hosts or the websites providing the streams, as the developers of this repository have no control over or access to the hosted content.

This project is for **educational purposes only**.

---

## 📜 License

GNU General Public License v3.0 — same as upstream. See [LICENSE](./LICENSE).

---

## 🇫🇷 Résumé en français

FreeFlix est un fork stabilisé d'autoflix-cli avec :

- 5 lecteurs (mpv, VLC, navigateur, download-only) ;
- Téléchargement vidéo (yt-dlp / aria2c, choix qualité, batch saison complète) ;
- Reprise à la seconde près dans mpv ;
- Sync AniList, fallback OpenSubtitles ;
- Téléchargements parallèles + notifications quotidiennes ;
- Source Nyaa torrents en plus ;
- Nouvelle source **French-Manga** (anime VF/VOSTFR, lecteurs vidzy & luluvid) ;
- **Au premier lancement, on te demande d'abord la langue des animes** (anglais VO/sous-titres ou français VF/VOSTFR), puis la langue de l'interface ;
- Les sources et les sous-titres téléchargés **suivent la langue des animes choisie** (anglais → sous-titres anglais, etc.) ;
- UI 100 % traduite en français ;
- Config mpv anti-crash + Anime4K déjà préinstallé ;
- Tous les bugs liés au refacto d'animes-sama.fr de mai 2026 fixés.

Installer :

```bash
uv tool install freeflix-cli    # ou pipx install freeflix-cli
```

…puis tape `freeflix`. Si tu n'as pas encore `mpv`, `yt-dlp`, `ffmpeg`, `aria2` et `libnotify` installés sur ta machine, lance plutôt le script d'install dédié à ton OS (`scripts/install.sh`, `install-mac.sh` ou `install.ps1`) qui prend tout en charge.
