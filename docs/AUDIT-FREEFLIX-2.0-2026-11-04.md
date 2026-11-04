# Audit complet — FreeFlix CLI 2.0.0

**Date** : 4 novembre 2026 · **Version auditée** : 2.0.0 (`194cf3c`, tag `v2.0.0`, PyPI 2.0.0)
**Périmètre** : dépôt complet (`src/`, `tests/`, `scripts/`, `config/`, `data/`, CI, packaging) + historique des conversations d'agents sur la machine.
**Méthode** : lecture du code (30 447 lignes `src`, 69 modules ; 9 040 lignes de tests), exécution de la suite (533 tests), lint CI, `freeflix --doctor`, vérification PyPI/GitHub Actions, extraction des sessions opencode et Claude Code.

> **Mise à jour (2.1.0)** : les corrections issues de cet audit sont appliquées
> dans la version 2.1.0. Voir le suivi constat par constat dans
> [`CORRECTIONS-2.1.0.md`](CORRECTIONS-2.1.0.md) et la réévaluation
> [`SCORECARD-2.1.0.md`](SCORECARD-2.1.0.md).

> Légende : **[V]** vérifié par lecture ou exécution · **[S]** déduit du code, à confirmer sur la plateforme concernée (surtout Windows/macOS).

---

## 0. Synthèse — le verdict en une page

FreeFlix n'est plus un petit fork : c'est un produit complet, avec 10 sources, un pipeline de résolution maison, un proxy local, des téléchargements vérifiés, un planning Anime-Sama, un feed « Nouveautés », un sync AniList, une UI bilingue pilotable à la souris et un design system 2.0. La discipline de développement est réelle : i18n testée par AST, cache HTTP, reprise réseau, staging des téléchargements, SSRF bloqué, aucune couleur en dur, `progress.json` écrit atomiquement.

Le problème n'est plus « est-ce que ça marche » mais **la cohérence entre les promesses, les chemins secondaires et la maintenance**. Les bugs les plus coûteux sont dans les recoins : reprise séquentielle des téléchargements cassée par un tuple comparé à `"ok"`, test qui supprime un vrai dossier utilisateur, `--doctor` qui déclare ffmpeg cassé, workflow de binaires mort-né, `Esc` qui exécute la dernière action du menu, changement de langue à moitié appliqué. S'y ajoutent des monolithes (`cli_utils.py` 2 896 lignes, `main()` 660 lignes) qui rendent chaque correction plus risquée qu'elle ne devrait l'être.

| Domaine | Note | Commentaire |
|---|---|---|
| Fonctionnalités | 9/10 | Très au-dessus de la moyenne des CLI de streaming |
| UX / design 2.0 | 8,5/10 | Identité forte, souris, accessibilité ; quelques angles morts |
| Architecture | 6/10 | Bonnes idées, mais fichiers-monstres et duplication |
| Robustesse réseau | 7,5/10 | Proxy, cache, reprise : sérieux ; faux positifs et budgets courts |
| Téléchargements | 6,5/10 | Conception solide, un bug casse la reprise de secours |
| Multi-OS | 5,5/10 | Linux solide, Windows/macOS non testés en CI, chemins divergents |
| Tests / CI | 6/10 | 533 tests verts, mais 12 % d'échecs CI et des trous critiques |
| Release / packaging | 5/10 | PyPI/GitHub OK, binaires annoncés inexistants, pas de garde-fou |
| Documentation | 4/10 | README en retard sur la 2.0, `docs/` vide, pas de CONTRIBUTING |
| Sécurité | 7/10 | SSRF/token bien traités ; en-têtes dans les URLs, TLS off, injection PS |

**Les 10 constats à retenir**

1. **`_verify_download()` renvoie `(ok, reason)` mais la reprise séquentielle le compare à `"ok"`** → la reprise après échec ne publie jamais le fichier. [V]
2. **La suite de tests supprime le vrai dossier `~/.local/share/freeflix-cli/bin`** (`shutil.rmtree`) → risque de détruire les binaires gérés par l'utilisateur. [V]
3. **`freeflix --doctor` affiche `ffmpeg BROKEN`** alors que ffmpeg est sain : il teste `ffmpeg --version` (exit 8) au lieu de `-version`. [V]
4. **Le workflow `Binaries` n'a jamais tourné** (0 run, 0 binaire sur toutes les releases) : il écoute `release: published`, événement créé par `GITHUB_TOKEN`, qui ne redéclenche pas de workflow. Le README promet pourtant un `.exe`. [V]
5. **`Esc` sélectionne toujours la dernière option** : dans les menus où la dernière ligne est une action (« Parcourir les saisons »), `Esc` ouvre un écran au lieu de revenir. [V]
6. **Papystreaming, site français, est tagué `en`** → invisible en mode FR, proposé aux anglophones ; les branches GoldenAnime/HiAnime sont dupliquées et asymétriques. [V]
7. **Les en-têtes (dont cookies de gate `vz_ok`/`fsv_pe`) sont sérialisés en JSON dans l'URL du proxy local** → visibles dans les manifestes, les logs et l'inspection de processus. [V]
8. **Le changement de langue ne reconstruit pas le registre des sources** : le menu Accueil se traduit, les noms de sources restent dans l'ancienne langue jusqu'au redémarrage. [V]
9. **Des hôtes supportés sont masqués comme « offline »** (`vidmoly`, `filemoon`, `dood.li`) alors que leurs extracteurs existent ; à réconcilier avec l'audit live. [V]
10. **La 2.0 n'a pas mis à jour le README** : il annonce encore 6 sources, ne parle ni de Cinema Noir ni de YTS/EZTV/HiAnime/Coflix/Papystreaming. [V]

---

## 1. Le projet en bref

FreeFlix CLI est un fork maintenu d'`autoflix-cli` (PaulExplorer), distribué sur PyPI sous `freeflix-cli`, lancé par la commande `freeflix`. Il permet de chercher, regarder et télécharger films, séries et animes depuis un terminal, en VF/VOSTFR/VO, via mpv, VLC, le navigateur ou un simple téléchargement.

**Chiffres clés (4 nov. 2026)**

| Métrique | Valeur |
|---|---|
| Version | 2.0.0 « Cinéma Noir » |
| Code source | 30 447 lignes, 69 modules |
| Tests | 533 tests (382 fonctions), 9 040 lignes, 54 s |
| Sources | 10 providers (12 enregistrements conditionnels) |
| Langues UI | FR / EN (830 paires de traduction, 721 utilisées) |
| Thèmes | 12 palettes, dont Cinema Noir par défaut |
| Historique git | 221 commits, 119 tags, 1 auteur |
| CI (100 derniers runs) | 88 succès, 12 échecs (12 %) |
| Distribution | PyPI 2.0.0 + GitHub Release (wheel/sdist uniquement) |

**Fonctionnalités réelles** (vérifiées dans le code, pas seulement dans le README) :

- 10 sources : Anime-Sama, French-Anime, HiAnime, GoldenAnime, GoldenMS, Papystreaming, French-Stream, Coflix, YTS/EZTV, Nyaa.
- Planning Anime-Sama live (7 jours, posters, suivi d'un anime sans lancer d'épisode).
- « Nouveautés » = nouveaux épisodes des animes suivis/regardés, avec respect de l'état `released`.
- Recherche paginée (French-Stream « Afficher la suite », HiAnime 4 pages, Coflix 100, Nyaa 75, YTS 50).
- Lecteurs : mpv, VLC, navigateur, téléchargement seul ; analyse qualité/débit (HLS, DASH, ffprobe).
- Téléchargements simples et par saison, 1–4 workers, staging `.temp`, vérification durée/taille, reprise.
- AniList (continue watching, sync), OpenSubtitles en secours, notifications systemd.
- UI souris complète, breadcrumbs, filtre `/`, aide `?`, réduction des animations, thème mono.

---

## 2. Architecture réelle

```
freeflix (console_script)
└── cli.py            → --version / --help / --doctor sans charger l'app (~60 ms)
    └── main.py       → logs, flags, drain terminal, warm-up image, feed Nouveautés
        ├── setup_assistant.py  → gate deps, polices, mpv.conf, Anime4K, migrations
        ├── splash / LoadingScreen (0,86 s) + _register_providers()
        ├── update_checker.py   → invite MAJ, upgrade uv/pipx/pip, execv
        ├── boucle Accueil (main.py:1146+) : dashboard, Reprendre, AniList, Sources, Nouveautés, Historique, Downloads, Stats, Réglages
        └── handlers/*  → scraping/*  → player_manager.py  → proxy.py (127.0.0.1) → mpv/VLC/browser
```

**Modules et responsabilités**

| Module | Lignes | Rôle | Point d'attention |
|---|---:|---|---|
| `main.py` | 1 642 | Entrée, splash, registre, Accueil, Réglages, stats | `main()` = 660 lignes, routage par index |
| `cli_utils.py` | 2 896 | Console, thèmes, souris, breadcrumbs, 4 widgets | `select_with_preview` = 787 lignes |
| `player_manager.py` | ~3 200 | mpv/VLC, qualité, téléchargements, reprise | 65 `except` larges |
| `proxy.py` | ~1 500 | Proxy HLS/MP4, en-têtes, re-signature, SSRF | URLs avec en-têtes en query |
| `setup_assistant.py` | ~1 900 | Installation binaires/polices/configs | 4 installateurs divergents |
| `progress.py` | ~900 | Barres, BatchView, annulation | boucle Live bloquante possible |
| `tracker.py` | 634 | `progress.json` (historique, follows, tokens) | pas de validation de schéma |
| `i18n.py` | 1 001 | 830 paires EN→FR, `t()` | 109 clés mortes |
| `scraping/player.py` | ~1 600 | Extracteurs (packer, VOE, fsvid, byse, embed4me…) | 33 `except` larges |
| `handlers/playback.py` | ~800 | Menu lecteurs, analyse, téléchargement | budget 40 s |
| `terminal_image.py` | ~1 000 | chafa/sixel, cache de posters | couplage cache `AutoFlixCLI` |

**Flux de données**

- **Configuration** : `data/source_portal.jsonc` (miroirs) et `data/selectors.jsonc` (sélecteurs hot-patch) embarqués dans le wheel via `share/freeflix-cli/data`, surchargés à distance depuis `raw.githubusercontent.com`, puis par `~/.config/freeflix/source_portal.jsonc`.
- **État** : un seul `~/.local/share/AutoFlixCLI/progress.json` (mode `0600`, écriture atomique `mkstemp` + `fsync` + `os.replace`).
- **Caches** : `~/.cache/AutoFlixCLI/covers` (posters), `~/.cache/AutoFlixCLI/http` (HTTP), `~/.cache/AutoFlixCLI/origins.json` (miroirs 24 h), `~/.cache/freeflix-cli/freeflix.log`.
- **Téléchargements** : `~/Downloads/FreeFlix/.temp/<titre>/`, puis publication `os.replace` vers `~/Downloads/FreeFlix/<série>/`.

**Trois noms d'application coexistent** : `AutoFlixCLI` (données, cache posters, origines), `freeflix-cli` (logs, binaires gérés), `freeflix` (config mpv, override portail). C'est hérité de l'upstream et rend la désinstallation/backup confuse. [V]

---

## 3. Ce qui est vraiment solide

1. **Le pipeline de résolution est riche et assumé.** Décodage Dean Edwards, VOE, fsvid, byse, AES embed4me, XOR HiAnime, AES-GCM Xpass ; dispatch par hostname ; rejet de leurres. Peu de projets CLI vont aussi loin.
2. **Le proxy local est bien pensé.** Bind `127.0.0.1` uniquement, refus des IP loopback/privées/link-local après résolution DNS (anti-rebinding), réécriture des master/segments, re-signature à l'expiration, reprise `Range`. [V]
3. **La robustesse réseau est au-dessus de la moyenne.** `resilient_body` retente indéfiniment tant que le client est connecté, détecte les déconnexions, rafraîchit le manifeste ; `mpv` est configuré `reconnect`, timeouts longs. C'est exactement ce que l'utilisateur avait demandé.
4. **Les téléchargements sont staged et vérifiés.** HLS via yt-dlp (8 fragments, `--abort-on-unavailable-fragments`), MP4 via aria2c (8 connexions, `--continue`), durée EXTINF vs ffprobe, taille vs `Content-Length`, refus en `.incomplete`, publication atomique. La conception est bonne ; un bug casse la reprise (voir P0-1).
5. **L'i18n est réellement testée.** `test_i18n_complete.py` scanne l'AST : 721 clés utilisées, 0 manquante, 0 chaîne d'interface non traduite sur les chemins d'affichage. C'est rare et précieux.
6. **Le design system 2.0 est tokenisé.** `color(role)` + `ui.py` ; aucune couleur en dur hors marque ; thèmes legacy maintenus par `_ROLE_FALLBACK` ; wordmark partagé splash/accueil.
7. **L'accessibilité n'est pas un slogan.** `FREEFLIX_REDUCED_MOTION`, repli statique de `NeonPanel`, thème `mono`, clavier + souris partout, aide `?` centralisée.
8. **La chasse aux « Esc fantômes » est aboutie.** Drain 200 ms, absorption des blobs paste/OSC/CSI/focus, `disable_terminal_reports()` au démarrage, `chafa --probe off`. Le problème le plus pénible de l'historique a une vraie solution.
9. **Les perfs ont été travaillées.** Entrée CLI allégée (`--version` ~60 ms), imports différés pendant le splash, cache d'origine 24 h, caches TTL par provider, cache d'analyse qualité, `lxml` par défaut.
10. **La discipline de non-régression existe.** Tests dédiés aux bugs passés (`test_download_fixes`, `test_decoy_stream`, `test_search_parity`, `test_scraper_resilience` avec 53 cas de pages dégradées).

---

## 4. Problèmes P0 — à corriger avant toute nouvelle fonctionnalité

### P0-1 · La reprise séquentielle des téléchargements ne peut jamais réussir [V]

`_verify_download()` retourne `(ok, reason)` (`player_manager.py:1715-1758`), mais `_retry_hls_sequential()` fait :

```python
code = _verify_download(staged, expected, None, tol)
if code != "ok":          # un tuple n'est jamais égal à "ok"
    _purge_download_temp(staged)
    continue
```

(`player_manager.py:1980-1982`). Résultat : même un fichier valide est purgé et la boucle épuise ses tentatives. La fonctionnalité « sequential retry » annoncée en 1.15.1 est donc morte en silence.

**Correctif** : `ok, reason = _verify_download(...)` puis `if not ok:`. Deux lignes + un test qui vérifie qu'un fichier valide est publié.

### P0-2 · Un test détruit le dossier de binaires gérés de l'utilisateur [V]

`tests/test_managed_binaries.py:42-46` :

```python
d = _ensure_bin_dir()          # ~/.local/share/freeflix-cli/bin
assert d.is_dir()
shutil.rmtree(d, ignore_errors=True)
```

`_bin_dir()` pointe sur `user_data_dir("freeflix-cli", "PaulExplorer") / "bin"` (`setup_assistant.py:178-181`). `conftest.py` n'isole que les caches HTTP/origines, pas `HOME` ni `XDG_DATA_HOME`. Lancer `pytest` peut donc effacer les ffmpeg/mpv/chafa téléchargés par FreeFlix.

*Note d'audit* : la suite a été lancée ici ; le dossier est vide depuis (17:49) et `--doctor` ne voyait déjà aucun binaire géré — aucune perte constatée, mais le mécanisme est bien réel.

**Correctif** : fixture `autouse` qui isole `HOME`/`XDG_*` (ou monkeypatch de `_bin_dir`), et suppression du `rmtree` réel.

### P0-3 · `--doctor` déclare ffmpeg cassé à tort [V]

`_check_binary()` lance `[n, "--version"]` (`doctor.py:51-56`). ffmpeg ne connaît que `-version` : `ffmpeg --version` sort en code 8, donc `status = "BROKEN"`, alors que la bannière affichée est correcte.

Reproduit sur cette machine :

```
ffmpeg        BROKEN    ffmpeg version 9.0.2 …   /usr/bin/ffmpeg
ffmpeg --version  → exit 8
ffmpeg -version   → exit 0
```

**Correctif** : table de flags par outil (`ffmpeg: -version`, autres `--version`) et test unitaire.

### P0-4 · Le workflow `Binaries` est mort-né, les binaires n'existent pas [V]

`binaries.yml:6-7` écoute `release: published`. La Release est créée par `softprops/action-gh-release` avec le `GITHUB_TOKEN` (`release.yml`), et GitHub ne déclenche **pas** de nouveau workflow pour les événements produits par ce token. Preuves : `total_count = 0` pour `binaries.yml`, et toutes les releases (v2.0.0 incluse) ne contiennent que wheel + sdist.

Pourtant : `README.md:158-160` explique comment mettre à jour le « standalone `freeflix-windows-x86_64.exe` ». La promesse est fausse depuis août.

**Correctif** : soit déclencher le build dans le même workflow (`needs`/`workflow_call`), soit sur `workflow_run`, soit supprimer le workflow et corriger la doc. Ajouter `--add-data` pour les JSONC (le binaire PyInstaller ne les embarque pas, `build-binary.sh:5-12`).

### P0-5 · `Esc` exécute la dernière option au lieu de revenir [V]

`select_from_list(..., esc_selects_last=True)` par défaut (`cli_utils.py:1409`) et `Esc` renvoie `len(options) - 1` sans condition (`1741-1745`). Sur l'Accueil c'est voulu (Exit), mais sur les menus où la dernière ligne est une action réelle, `Esc` déclenche cette action :

- `handlers/anime_sama.py:550-557` : « Reprendre » / « Parcourir les saisons » → `Esc` parcourt les saisons.
- `handlers/coflix.py:137-144` : idem.

**Correctif** : `esc_selects_last=False` par défaut, opt-in explicite sur l'Accueil ; ou convention stricte « dernière option = retour » vérifiée par un test.

### P0-6 · Papystreaming est invisible pour les francophones [V]

`main.py:968-971` : `supported_languages=["en"]` pour Papystreaming, un site **français**. Le filtre `providers_registry.py:47-62` le masque donc en mode FR et l'affiche en EN. Par ailleurs, GoldenAnime/HiAnime ont des branches dupliquées et asymétriques (`main.py:900-938`) : en FR, elles sont enregistrées puis filtrées, ce qui ne sert à rien.

**Correctif** : `["fr"]` pour Papystreaming ; une seule branche par provider ; test de `_register_providers()` qui vérifie l'ordre et les langues.

### P0-7 · Reproduction du bug de téléchargement massif : le dossier est purgé [V]

Deux purgeurs contredisent la docstring de reprise : le retry purge tous les fragments (`player_manager.py:2221-2222`) et l'échec final aussi (`2308`), alors que la docstring promet une reprise (`2023-2027`). Les entrées « téléchargements interrompus » se retrouvent donc vides.

**Correctif** : ne purger qu'après succès, ou effacer la méta en même temps ; test de reprise interrompue.

---

## 5. Problèmes P1 — importants, à planifier

### Robustesse / fonctionnel

| # | Constat | Preuve | Impact |
|---|---|---|---|
| P1-1 | `progress.json` non validé : une clé de type inattendu (`episode_durations` en liste) fait planter `_home_dashboard()` hors `try` → crash-loop au démarrage | `tracker.py:22-31`, `525` ; `main.py:1239` | App inutilisable jusqu'à suppression manuelle du fichier |
| P1-2 | `os._exit(0)` contourne l'`atexit` `_mouse_off` ; `?2004h` n'a aucun pendant de désactivation | `main.py:1629,1642` ; `cli_utils.py:673-677, 759-767` | Terminal laissé en mouse/bracketed-paste après une sortie par exception |
| P1-3 | Le changement de langue ne reconstruit pas le registre ; `registry.clear()` n'est jamais appelé | `main.py:1099`, `1419-1424` | Noms de sources dans l'ancienne langue jusqu'au redémarrage |
| P1-4 | Souris Windows : `ENABLE_VIRTUAL_TERMINAL_INPUT` jamais activé sur stdin | `cli_utils.py:564-602` | Aucun rapport SGR reçu, mais `?1000h` envoyé → pas de souris et copier-coller perdu [S] |
| P1-5 | Faux positifs 15–30 s : durée non sondée pour les flux directs, refus <90 s limité à uqload | `player_manager.py:757-771`, `2077-2082` | Une pub/placeholder peut passer pour un épisode |
| P1-6 | Budget d'analyse 40 s insuffisant pour les MP4 throttlés (reconnu en commentaire) | `handlers/playback.py:114-121` | Lecteur valide marqué « non vérifié » |
| P1-7 | Cache qualité 600 s / résolution 90 s peut servir un lien expiré ; pas de refresheur pour les flux directs | `player_manager.py:781-808`, `2613-2619` | Échec de lecture après une pause |
| P1-8 | `_OFFLINE_HOST_MARKERS` masque `vidmoly`, `filemoon`, `dood.li` dont les extracteurs existent | `scraping/player.py:906-924`, `1543-1616` | Lecteurs valides invisibles (à confirmer en live) |
| P1-9 | Dédoublonnage trop agressif : deux embeds distincts même host/nom fusionnés | `handlers/playback.py:382-407` | « voe vostfr » + « voe vff » → une seule ligne |
| P1-10 | Relance infinie du proxy (`no_progress_budget=None`) sur `/ts` et `/video` | `proxy.py:1173-1176` | Buffering sans échec, annulation difficile |

### Sécurité

| # | Constat | Preuve | Impact |
|---|---|---|---|
| P1-11 | En-têtes (cookies `vz_ok`, `fsv_pe`, éventuel `cf_clearance`) sérialisés en JSON dans l'URL du proxy | `proxy.py:801-805` | Fuite locale dans manifestes/logs/inspection ; pas de secret de compte |
| P1-12 | TLS non vérifié sur le repli DoH (`DOH_SSL_VERIFYPEER=0`) | `net_config.py:19-20`, `cloudflare.py:198-199` | MITM possible sur le canal de secours |
| P1-13 | Injection PowerShell dans les toasts : XML inséré entre quotes simples, `'` non échappée | `notifications.py:100-122` | Titre piégé → casse/injection de commande sur Windows [S] |
| P1-14 | `setx PATH "<dir>;%PATH%"` sans shell : `%PATH%` littéral écrit dans le PATH utilisateur, troncature 1024 | `scripts/install.py:107-117` | PATH Windows corrompu après installation [S] |

### Installation / multi-OS

| # | Constat | Preuve | Impact |
|---|---|---|---|
| P1-15 | `setup_done` posé même si configs/shaders ont échoué → plus aucune reprise | `setup_assistant.py:1675-1699` | mpv sans Anime4K, sans message clair |
| P1-16 | macOS : `install-mac.sh` écrit `~/.config/mpv` alors que l'app lit `~/.config/freeflix/mpv` | `install-mac.sh:87-95` vs `setup_assistant.py:147-153` | Anime4K inutile après install script |
| P1-17 | `--doctor` inspecte `~/.config/mpv` au lieu du dossier FreeFlix | `doctor.py:103-106` | Faux « MISSING » / faux « OK » |
| P1-18 | mpv macOS figé sur build **Intel**, même Apple Silicon (seul ffmpeg bascule arm64) | `setup_assistant.py:242-247`, `420-431` | Rosetta requis / perfs dégradées [S] |
| P1-19 | `install.ps1` : zip uv `x86_64` en dur, pas de TLS 1.2 explicite | `install.ps1:39-42` | Échec ARM64, téléchargement bloqué sur vieux Windows [S] |
| P1-20 | `install.sh` : `apt/dnf/apk install … vlc` en une commande ; un paquet absent annule tout | `install.sh:31-58` | Installation échoue sur Fedora sans RPM Fusion / Alpine [S] |
| P1-21 | `install.sh` télécharge les shaders `_VL`, `mpv.conf` charge les `_S` | `install.sh:128-130` vs `config/mpv.conf:92` | Anime4K absent après install script (auto-réparé au premier lancement) |

### UI / rendu

| # | Constat | Preuve | Impact |
|---|---|---|---|
| P1-22 | `_crumb_line` boucle à l'infini si largeur ≤ 8 colonnes | `cli_utils.py:879-884` | App figée sur terminal minuscule |
| P1-23 | EOF (`os.read` → `b""`) non géré : boucle de refresh à 100 % CPU | `cli_utils.py:1163-1170` | CPU brûlé si stdin fermé |
| P1-24 | Pas de SIGWINCH ; ancre souris non re-mesurée après resize | `cli_utils.py:1577-1583` | Clics décalés après redimensionnement |
| P1-25 | `progress.py:179` écrit `self._live._alt_screen` (attribut privé Rich) | `progress.py:179` ; `rich>=14.2.0` non borné | Démarrage cassé à la prochaine montée de version Rich |
| P1-26 | `wordmark` reste ambre/ivoire hors thème noir (seul `noir` définit `surface`) | `ui.py:30-37`, `themes.py:185-190` | Incohérence avec l'aperçu de thème [V] |
| P1-27 | `skeleton()` ignore `motion.reduced()` | `cli_utils.py:2777-2798` | Accessibilité partielle |

---

## 6. P2 — dette technique, hygiène, documentation

- **Monolithes** : `cli_utils.py` 2 896 lignes, `select_with_preview` 787 lignes (`1948-2734`), `main()` 660 lignes (`983-1642`), 25 fonctions ≥ 120 lignes. Toute correction UI est un exercice de prudence.
- **Trois décodeurs clavier** : Windows (`1051-1151`), POSIX (`1153-1263`), preview (`2398-2443`), déjà divergents (Alt+lettre, CSI > 3 octets, constantes différentes). ~250 lignes dupliquées.
- **Handlers vs scraping** : chaque provider a un handler de flow et un module de scraping ; la logique de navigation est répétée (recherche, saison, épisode, retour). Le contrat « back = dernier index » est implicite.
- **i18n** : 109 clés mortes, 18 traductions identiques, clés-fragments (`select`, `got`, `ep`, `by`) qui imposent l'ordre des mots anglais ; `t()` réimporte `tracker` à chaque appel.
- **Trois noms d'app** : `AutoFlixCLI` (données/cache), `freeflix-cli` (logs/bin), `freeflix` (config). Un utilisateur ne sait pas quoi sauvegarder/supprimer.
- **Version à trois endroits** : `pyproject.toml:7`, `install_health.py:16`, `scripts/install.py:260` (+ `uv.lock`), sans test de cohérence.
- **Code mort** : `--version/--help/--doctor` re-implémentés dans `main.py:996-1025` alors que `cli.py:38-52` intercepte déjà ; `registry.clear()` jamais appelé ; `search_card` inutilisé ; `selectors.jsonc` vide ; deux recherches Cinemeta.
- **README en retard** : `README.md:75` annonce 6 sources (il y en a 10), aucune mention de Cinema Noir, de YTS/EZTV/HiAnime/Coflix/Papystreaming, des 533 tests ou de la 2.0. `docs/` est vide, pas de CONTRIBUTING/SECURITY.
- **Hygiène** : `.ruff_cache/` non ignoré ; `dist/` 25 Mo et `.venv` 83 Mo présents (non suivis, donc pas grave) ; tag `1.6.5` sans `v` qui ne déclenche rien ; 54 % de commits de release ; 119 tags pour 221 commits.
- **Dépendances** : `rich>=14.2.0` non borné (accès privé), `curl-cffi`/`platformdirs` exigent ≥3.10 alors que `requires-python` dit ≥3.9.2 ; `uv.lock` compense par marqueurs, mais la 3.9 est une résolution rétrogradée silencieuse, jamais testée en profondeur.

---

## 7. Sécurité et vie privée

**Ce qui est bien fait**

- Token AniList stocké dans `progress.json` en mode `0600`, jamais loggé [V].
- Proxy strictement local (`127.0.0.1`), refus des cibles loopback/privées/link-local après DNS, anti-rebinding, jail pour les sous-titres [V].
- Aucun `shell=True`, aucun `eval` sur du contenu distant (seulement un décodeur de packer), pas de `verify=False` global.
- Cache HTTP refusant les pages de challenge ; purge périodique.

**Points à corriger**

1. En-têtes/cookies dans les URLs du proxy (P1-11) → jeton opaque côté serveur, table `token → headers`.
2. TLS désactivé sur le repli DoH (P1-12) → vérifier, ou documenter comme compromis explicite.
3. Injection PowerShell des toasts (P1-13) → fichier XML temporaire ou échappement de `'`.
4. `setx PATH` (P1-14) → `SetEnvironmentVariable` ou `.reg`, jamais `%PATH%` littéral.
5. Dépendance à `enc-dec.app` pour trois sources GoldenMS : panne tierce = 3 lecteurs morts, et les payloads lui sont envoyés. Prévoir un circuit breaker + décodage local de secours.
6. URLs signées affichées dans les erreurs (`player_manager.py:2622`, `handlers/goldenms.py:427`) → masquer la query.
7. Installeurs : `curl | sh`, uv « latest » sans checksum, `setx` ; à durcir (versions pinnées, checksums).

---

## 8. Tests, CI et release

**Ce que la CI garantit vraiment**

- 4 jobs : Ubuntu 22.04 + Windows × Python 3.9/3.12 (`ci.yml:25-26`).
- Ruff `E,W,F,B` sur `src/` seulement, hors `E501,E402` (`ci.yml:40`) ; imports de tous les modules ; pytest avec `--cov-fail-under=15` (`ci.yml:55`).
- **Ne garantit pas** : macOS, Python 3.10/3.11/3.13, lint des tests, typage, build/installation du wheel, `freeflix --version`/`--doctor`, les installeurs, le binaire.
- Couverture plancher à 15 % : c'est un garde-fou de régression, pas une mesure de qualité.
- 192 runs CI, 12 % d'échecs sur les 100 derniers ; 0 PR (1 seul auteur) → la CI constate après merge, elle ne bloque pas.
- Reproductibilité : `uvx ruff` et `--with pytest` non pinnés, `uv run --with .` ignore `uv.lock`.

**Faiblesses des tests**

- ~97 % de la suite est mockée ; le vrai bout-en-bout se limite à 2 tests ffmpeg/yt-dlp, 2 downloads loopback, ~8 tests proxy locaux, 8 tests mpv IPC factices.
- Deux tests font du réseau réel : `test_nerd_font.py:26-33` (GET GitHub, `pytest.fail` hors ligne) et `test_recent_new_episodes.py:75-84` (appel `anime_sama.get_website_url()`).
- Assertions tautologiques : `test_health.py:24`, `test_managed_binaries.py:328` (`or True`), `test_batch_download.py:46` (`assert True`), `test_batch_download.py:73-103`.
- Tests d'implémentation : `test_v2_aesthetic.py:74-78` fige `_cell_speed == 30.0` ; `test_navigation.py:164-169` parse l'AST des handlers.
- Zones sans test : `providers_registry.py`, `doctor.py` (436 lignes), `config_loader.py`, `net_config.py`, `history_ui.py`, `icons.py`, `main.py` hors rendu, `cli.py`, installateurs, packaging JSONC.
- Tests fragiles : serveurs Range réimplémentés 4 fois, `sleep` dans `test_mpv_ipc.py:85/103`, course de port `test_proxy_resilient.py:261`, seuil de perf `test_stream_analysis.py:107-131`.

**Release**

`tag v*` → build → PyPI (OIDC) → notes `git log` → GitHub Release. Risques : aucun `needs: ci`, aucun contrôle `tag == version`, PyPI publié **avant** la Release (donc une erreur après publication laisse une version PyPI sans release, non réuploadable). 2 échecs de release sur l'historique récent. Les binaires ne sont jamais construits (P0-4).

---

## 9. Ce que racontent les autres conversations

L'utilisateur a demandé explicitement de regarder « les chats avec d'autres ». Voici ce qui existe réellement sur la machine.

### opencode / DeepSeek — le chantier principal

- **12 sessions** sur `freeflix-cli`, dont **« Analyse complète du projet »** : 303 messages utilisateur, **32,3 M tokens d'entrée**, **1,5 M de sortie**, du 10 octobre 21:03 au 4 novembre 16:35, 12 compactions.
- Cette session est le véritable journal de bord de la 1.10 → 2.0 : providers, i18n, souris, planning, Nouveautés, téléchargements, esthétique. Elle se termine par le push de la **2.0.0** (commit `194cf3c`, tag `v2.0.0`, PyPI + GitHub Release vérifiés).
- Sessions satellites : exploration du point d'entrée, du scraping, de l'UI ; audits live Anime-Sama / French-Stream / Golden ; traduction FR en 4 lots.
- Une session de support (`ses_e9880087`) ne contient que la reprise après une coupure réseau `api.deepseek.com`.

**Le « contrat implicite » qui ressort de ces échanges** (et qui doit servir de cahier des charges) :

1. Tout doit être **traduit en français** ; utiliser `icon()`/Nerd Font, jamais d'emoji décoratif codé en dur.
2. **Linux, macOS, Windows** + Python 3.9+, et les mises à jour doivent préserver ça.
3. **Ne jamais pousser sans test local** : miroir local, l'utilisateur teste, puis autorise ; vérifier PyPI après le push.
4. Navigation : **un retour = un niveau**, état conservé, écran propre, poster visible pendant les menus inline.
5. Recherche : **au moins autant de résultats que le site**, pagination type « Afficher la suite ».
6. Téléchargements **complets, vérifiés, reprenables**, jamais de parties sautées ; streaming qui survit aux coupures.
7. Planning **live** (jamais en dur), « Nouveautés » = épisodes des animes suivis, disparaît quand vu, revient à l'épisode suivant.
8. **Souris partout** (survol, clic, molette, clic droit).
9. Esthétique **Cinema Noir** : sobre, éditorial, animations fluides, pas d'esbroufe.

**Limites déjà actées dans les chats** : Papystreaming bloqué Cloudflare ; plusieurs hôtes Coflix morts en amont ; Vidzy gate + fingerprint TLS (aria2c inadapté) ; le portage Rust a été lancé puis **mis en pause** — le dossier `freeflix-cli_rust` n'existe plus dans `Applications/`.

### Claude Code — les origines

**82 prompts** contenant « freeflix »/« autoflix », depuis le **27 mai 2026** (création du projet). Thèmes : fork d'autoflix, Embed4Me, chafa, Nerd Font, sixel, mises à jour, Android, comparaison de vitesse avec autoflix, scripts d'installation multi-OS, « rendre FreeFlix populaire ». Idées évoquées mais **jamais implémentées** : saut d'opening/ending, système d'abonnement par code, streaming sportif live, site web/app, portage Rust.

### DSH (cette session)

Une seule session pour ce projet, créée aujourd'hui à 16:45 — celle-ci. Les trois autres sessions DSH de la machine concernent un montage vidéo PowerPoint et des « hi » sans rapport. **Il n'y a donc pas d'historique DSH antérieur sur FreeFlix** : l'historique utile est dans opencode et Claude Code.

---

## 10. Plan d'action proposé

### Sprint 0 — aujourd'hui, < 2 h (corrections à faible risque, fort impact)

1. `_retry_hls_sequential` : `ok, reason = _verify_download(...)` (P0-1) + test.
2. Isoler `HOME`/`XDG` dans `conftest.py`, supprimer le `rmtree` réel (P0-2).
3. `--doctor` : flag `-version` pour ffmpeg (P0-3) + test.
4. `esc_selects_last=False` par défaut, opt-in Accueil (P0-5).
5. `os._exit(0)` → sortie propre avec `finally` (P1-2).
6. Papystreaming `["fr"]`, dédupliquer les branches providers (P0-6).
7. README : sources réelles, 2.0, section dev/tests.

### Sprint 1 — 1 à 2 jours (fiabilité)

8. Réparer le workflow binaires (`workflow_run` ou même workflow), `--add-data`, smoke test `import freeflix_cli.main`.
9. Release : `needs: ci`, contrôle `tag == pyproject.version`, `twine check`, publier la Release avant PyPI ou rendre l'étape idempotente.
10. Jeton opaque pour les en-têtes du proxy (P1-11).
11. Rejet générique des placeholders < 90 s, flux directs inclus (P1-5).
12. Registre de providers reconstruit au changement de langue (P1-3).
13. `setup_done` conditionnel + `get_mpv_config_dir()` unique (P1-15/16/17).
14. Toasts PowerShell sans interpolation (P1-13) ; `setx` remplacé (P1-14).

### Sprint 2 — la semaine (structure)

15. Sortir `select_with_preview` dans `preview_picker.py`, pools au niveau module, `shutdown()` réel (P2).
16. Unifier les trois décodeurs clavier sur des constantes internes.
17. Windows : activer `ENABLE_VIRTUAL_TERMINAL_INPUT` ou ne pas envoyer `?1000h` (P1-4).
18. Rendre la suite offline (mock `get_website_url`, retirer le GET GitHub) ; ajouter macOS + Python 3.11/3.13 à la CI ; `uv sync --locked`.
19. Coverage 15 → 30 %, tests `providers_registry`, `doctor`, `config_loader`, packaging.
20. `try` autour de l'Accueil + validation légère de `progress.json` (P1-1).

### Sprint 3 — ensuite

21. TLS du repli DoH, circuit breaker `enc-dec.app`, découverte des hashes Allanime.
22. Résilience : budgets d'analyse adaptatifs, cache qualité plus court pour les liens signés, plafond `resilient_body`.
23. Hygiène : un seul nom d'app, script de bump (3 versions + CHANGELOG + tag), `docs/` rempli, CONTRIBUTING, `.ruff_cache` ignoré.
24. Si la promesse « binaire » est conservée : macOS Intel/ARM, Linux aarch64, checksums, signature.

---

## 11. Annexes

### Commandes exécutées

```bash
.venv/bin/python -m pytest -q                 # 533 passed, 54.39 s
uvx ruff check --select E,W,F,B --ignore E501,E402 src/freeflix_cli/   # All checks passed
freeflix --doctor                              # ffmpeg BROKEN (faux négatif)
curl pypi.org/pypi/freeflix-cli/json           # 2.0.0, wheel + sdist
curl api.github.com/.../releases/latest        # v2.0.0, 2 assets, pas de binaire
curl api.github.com/.../actions/workflows      # Binaries: active, 0 run
```

### Métriques

| | |
|---|---|
| Fonctions ≥ 120 lignes | 25 (dont `select_with_preview` 787, `play_video` 726, `main` 647) |
| `from __future__ import annotations` | 23 / 69 modules |
| `except:` nus | 0 |
| `shell=True` | 0 |
| `TODO/FIXME` | 0 |
| Chemins `/home/...` en dur | 0 |
| Fichiers suivis | 138 ; aucun artefact (`dist/`, `.coverage`, `__pycache__` ignorés) |
| Taille `.git` | 9,8 Mo |

### Fichiers chauds (à lire avant de modifier)

`src/freeflix_cli/cli_utils.py` · `player_manager.py` · `main.py` · `proxy.py` · `setup_assistant.py` · `handlers/playback.py` · `scraping/player.py` · `.github/workflows/{ci,release,binaries}.yml` · `tests/test_managed_binaries.py`.

### Sources externes consultées

- PyPI : https://pypi.org/pypi/freeflix-cli/json
- GitHub Releases : https://github.com/freedy237/freeflix-cli/releases
- GitHub Actions : https://github.com/freedy237/freeflix-cli/actions

---

*Rapport généré par audit statique + exécution locale. Aucun fichier source n'a été modifié. Les points marqués [S] (Windows/macOS, effets `setx`, TLS 1.2) demandent une validation sur la plateforme concernée.*
