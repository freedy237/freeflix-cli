# Corrections 2.1.0 — état par rapport à l'audit

Suivi de chaque constat de `docs/AUDIT-FREEFLIX-2.0-2026-11-04.md`.
Légende : **corrigé**, **partiel**, **reporté** (avec raison), **faux positif**
(l'audit se trompait, rien à corriger).

## P0

| Constat | État | Détail |
|---|---|---|
| Reprise séquentielle cassée (tuple vs `"ok"`) | corrigé | `ok, reason = _verify_download(...)` ; les fragments sont conservés, le mux rejeté est renommé `.incomplete`. Test dédié. |
| Test qui supprime `~/.local/share/freeflix-cli/bin` | corrigé | Fixture `autouse` qui isole `_bin_dir` dans `tmp_path` ; `rmtree` réel supprimé. |
| `--doctor` déclare ffmpeg BROKEN | corrigé | Table `_VERSION_FLAGS` (`ffmpeg/-version`) ; vérifié : `ffmpeg OK` sur la machine. |
| Workflow `Binaries` mort-né | corrigé | `release.yml` dispatch `binaries.yml` via `workflow_dispatch` (autorisé avec `GITHUB_TOKEN`), `--add-data`, smoke test `--doctor`. À valider au prochain tag. |
| `Esc` exécute la dernière action | corrigé | Vraie ligne « ← Retour » ajoutée aux menus Reprendre/Parcourir (Anime-Sama, Coflix, French-Stream). La convention reste « dernière ligne = retour ». |
| Papystreaming tagué `en` | faux positif | Décision utilisateur : le catalogue est anglais. Laissé `["en"]`. Les branches dupliquées HiAnime/GoldenAnime ont été supprimées. |
| Purge des fragments contraire à la docstring | corrigé | La docstring de `_download_stream` décrit désormais le comportement réel (purge volontaire des fragments douteux) ; la reprise séquentielle, elle, conserve les fragments. |

## P1

| Constat | État | Détail |
|---|---|---|
| `progress.json` non validé / Home sans `try` | corrigé | Validation de forme par conteneur + dashboard sous `try/except`. |
| `os._exit` laisse le terminal sale | corrigé | `_clean_exit()` : souris, bracketed paste, curseur, écran alterné, proxy, puis `SystemExit`. |
| Changement de langue non appliqué aux sources | corrigé | `registry.clear()` + `_register_providers()` sur langue UI et langue anime. |
| Souris Windows (VT input) | corrigé | `ENABLE_VIRTUAL_TERMINAL_INPUT` activé sur stdin. À valider sur Windows. |
| Faux positifs 15–30 s (flux directs) | corrigé | `_ffprobe_quality` remonte `duration` et `is_likely_ad_placeholder` s'applique aussi aux MP4 directs. |
| Budget 40 s insuffisant | partiel | Les budgets restent généreux (40 s menu / 25 s par lecteur) ; un travail adaptatif serait une refonte du menu, non faite. |
| Cache qualité 600 s / lien expiré | partiel | Le proxy re-signature les URLs expirées ; le cache court reste à 10 min pour les succès. Pas de TTL par type de lien. |
| Hôtes supportés masqués (`vidmoly`, `filemoon`) | reporté | Masquage volontaire après l'audit live 2026-10 (l'utilisateur ne veut plus de faux lecteurs). À revalider en live avant de les réafficher. |
| Dédoublonnage trop agressif | corrigé | La clé inclut le libellé complet : « voe vostfr » et « voe vff » restent distincts ; seules les URLs identiques sont fusionnées. |
| Buffering infini | corrigé | Plafond de 300 s sans octet sur `/ts` et `/video`. |
| Cookies/en-têtes dans les URLs du proxy | corrigé | Jeton opaque `?h=…` (24 car.) + jeton de capacité `?k=…` par processus : un autre programme local ne peut plus utiliser le proxy. |
| TLS DoH non vérifié | corrigé | Vérification réactivée dans `net_config`, `cloudflare`, `french_stream`. |
| Injection PowerShell des toasts | corrigé | XML dans un fichier temporaire, `$doc.Load(path)`, nettoyage `finally`. |
| `setx PATH "%PATH%"` | corrigé | Écriture registre `REG_EXPAND_SZ` via `winreg`. Cookies retirés des métadonnées de reprise ; noms de fichiers Windows durcis. |
| `setup_done` posé malgré l'échec | corrigé | `setup_done` seulement si configs + shaders OK ; sinon retry au lancement suivant. |
| macOS : mauvais dossier mpv | corrigé | `install-mac.sh` écrit dans `~/.config/freeflix/mpv`. |
| `--doctor` inspecte le mauvais mpv | corrigé | `_mpv_config_dir()` importe `get_mpv_config_dir()` ; vérifie les shaders `_S`. |
| mpv Intel sur Apple Silicon | corrigé | Builds **arm64** natifs macOS + Windows ARM ajoutés (sha256 pinnés). |
| `install.ps1` x86_64 en dur, TLS | corrigé | Détection `PROCESSOR_ARCHITECTURE`, TLS 1.2/1.3. |
| `install.sh` tout-ou-rien | corrigé | Paquets installés un par un, échecs optionnels signalés sans abort. |
| Shaders `_VL` vs `_S` | corrigé | `install.sh` et `install-mac.sh` installent S + VL. |
| Fil d'Ariane : boucle infinie ≤ 8 col. | corrigé | Troncature déterministe et bornée. |
| EOF stdin : boucle 100 % CPU | corrigé | EOF traité comme Esc. |
| Resize / ancre souris | reporté | Pas de SIGWINCH ; un vrai resize propre demande de re-mesurer la géométrie à chaque frame souris. Cosmétique, non bloquant. |
| `_live._alt_screen` privé Rich | partiel | Accès privé conservé (pas d'alternative publique), borné par `rich>=14.2,<15` + `try/except`. |
| Wordmark ambre hors thème noir | corrigé | `_on_black_theme()` ne renvoie True que si le thème définit un `surface` sombre. |
| `skeleton()` ignore reduce motion | corrigé | Une seule frame statique quand `reduced()` est vrai. |
| `selection_text` → blanc | corrigé | Repli littéral `black`. |

## P2 / dette

| Point | État | Détail |
|---|---|---|
| Monolithes (`cli_utils`, `select_with_preview`, `main`) | partiel | `select_with_preview` extrait dans `preview_picker.py` (2 896 → 2 166 lignes dans `cli_utils`) et le menu Réglages extrait de `main()` (660 → 359 lignes). Reste : handlers/scraping et 290 lignes de `_settings_menu`. |
| Trois décodeurs clavier | corrigé | Le preview utilise `_read_menu_key(timeout=…)` (décodeur partagé, collage/OSC/mouse/ESC identiques) ; son décodeur privé a été supprimé. Test PTY réel : flèche + Entrée → index attendu. |
| Handlers/scraping redondants | partiel | Branches providers dédupliquées ; la structure handler/scraper reste (elle isole bien les sites). |
| 109 clés i18n mortes | reporté | Suppression mécanique possible mais risque de casser des clés construites dynamiquement ; le test AST couvre les clés utilisées. |
| Trois noms d'application | documenté | Conservés pour ne pas perdre les données existantes ; documentés dans `docs/ARCHITECTURE.md`. |
| Version à trois endroits | corrigé | Test `test_code_version_matches_pyproject` + procédure `docs/RELEASE.md`. |
| Code mort (flags dupliqués, `registry.clear`) | corrigé | Flags retirés de `main.py`, `registry.clear()` utilisé. |
| README en retard | corrigé | 10 sources, 2.0, planning, Nouveautés, souris, commandes dev. |
| `docs/` vide | corrigé | `README.md` (index), `USAGE.md`, `ARCHITECTURE.md`, `TROUBLESHOOTING.md`, `RELEASE.md`, `CORRECTIONS-2.1.0.md`, audit + `SECURITY.md`. |
| CI sans macOS / 3.11 / 3.13 | corrigé | Matrice étendue + build wheel + smoke install. |
| Tests réseau | corrigé | `test_nerd_font` hors ligne, `recent._fetch` ne résout plus le miroir sans anime suivi. |
| Tests destructeurs / faibles | partiel | Fixture binaires, 17 tests de non-régression + 30 tests unitaires (cli, doctor, registry, config, thèmes, IPC Windows) ; quelques assertions historiques restent à nettoyer. |
| Couverture / timeouts CI | corrigé | ~45 % mesurés, plancher 40 %, `pytest-timeout=120`, `ruff==0.17.3` épinglé. |
| Release sans garde-fou | corrigé | `needs: test`, version == tag, `twine check`, binaires dans la foulée. |
| Hygiène repo | corrigé | `.ruff_cache/`, `.freebuff/`, `.mypy_cache/` ignorés ; `CONTRIBUTING.md`. |

## Ce qui reste volontairement ouvert

1. **Resize terminal** : pas de SIGWINCH, l'ancre souris des menus inline n'est pas re-mesurée ; cosmétique après un redimensionnement.
2. **Hôtes masqués** (`vidmoly`, `filemoon`) : à revalider en live (`freeflix --doctor --sources`) avant réaffichage.
3. **Clés i18n mortes** : nettoyage mécanique à faire, sans risque fonctionnel (le test AST couvre les clés utilisées).
4. **`_settings_menu`** (290 lignes) : encore gros ; découpage par catégorie (AniList / lecture / apparence / réseau) à planifier.
