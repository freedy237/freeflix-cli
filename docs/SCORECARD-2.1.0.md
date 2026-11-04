# Grille 2.1.0 — réévaluation après corrections

Même grille que l'audit 2.0.0, réévaluée après la passe de corrections 2.1.0.
Chaque note est justifiée par des preuves vérifiables et par ce qui reste
ouvert ; il ne s'agit pas d'une note « commerciale ».

| Domaine | 2.0.0 | 2.1.0 | Preuves principales | Ce qui reste |
|---|---:|---:|---|---|
| **Fonctionnalités** | 9 | **9,5** | 10 sources, planning Anime-Sama live, Nouveautés par épisode suivi, recherche paginée, 4 backends, téléchargements par saison, AniList, sous-titres, notifications | dépend des sites tiers |
| **UX / design 2.0** | 8,5 | **9** | Cinema Noir + 11 thèmes, souris complète, retour à un niveau, menus Reprendre avec vraie ligne Retour, langue appliquée immédiatement, preview sur décodeur partagé, reduced-motion, wordmark corrigé | pas de SIGWINCH (ancre souris après resize) |
| **Architecture** | 6 | **8,5** | `preview_picker.py` extrait (787 l.), `main()` 660 → 359 l., Réglages extrait, 3 décodeurs clavier → 1 décodeur partagé, registre rebuild, providers dédupliqués | handlers/scraping encore répétitifs, `_settings_menu` 290 l., clés i18n mortes |
| **Robustesse réseau** | 7,5 | **8,5** | placeholder <90 s y compris MP4 direct, plafond 5 min sans octet, budget analyse 55/60 s, cache qualité 5 min, TLS DoH vérifié, SSRF + jeton proxy, reprise Range | pas de budget adaptatif par type de lecteur |
| **Téléchargements** | 6,5 | **9** | reprise séquentielle réparée, staging + vérification + `os.replace`, `.part` atomique, annulation propagée + kill après 5 s, métadonnées sans cookies en 0600, noms Windows réservés, balayage des sous-titres temp | vérification taille seule si ffprobe absent |
| **Multi-OS** | 5,5 | **8,5** | CI Linux/Windows/macOS × 3.9→3.13, build wheel + smoke install, syntaxe PowerShell vérifiée, mpv arm64 macOS/Windows, IPC Windows non bloquant, installateurs tolérants, chemins mpv alignés | pas de validation physique Windows/macOS dans cette session |
| **Tests / CI** | 6 | **9** | **586 tests** verts, couverture **~45 %** (plancher 40), `pytest-timeout=120`, ruff épinglé, suite offline, 47 tests de non-régression/unitaires ajoutés, matrice 5 environnements | quelques assertions historiques faibles, pas de tests de rendu visuel |
| **Release / packaging** | 5 | **8,5** | release gardée par tests + version==tag + `twine check`, `SHA256SUMS`, binaires déclenchés explicitement (`workflow_dispatch`), `--add-data`, smoke `--doctor`, tests de config de release | chaîne binaires à exécuter au prochain tag réel |
| **Documentation** | 4 | **9** | README 2.1 (10 sources, planning, souris, dev), index `docs/`, USAGE, ARCHITECTURE, TROUBLESHOOTING, RELEASE, SECURITY, CONTRIBUTING, CHANGELOG détaillé | pas de captures d'écran/GIF |
| **Sécurité** | 7 | **9** | jeton de capacité proxy (SSRF local), SSRF DNS/IP, TLS DoH, cookies retirés des métadonnées, URLs signées masquées, toasts PowerShell sans interpolation, PATH registre, checksums d'artefacts | `enc-dec.app` tiers pour GoldenMS, `curl \| sh` de `uv` dans un installeur |

## Vérifier soi-même

```bash
freeflix --version                  # 2.1.0
freeflix --doctor                   # Code == Metadata, ffmpeg OK, mpv dédié
uv run --with pytest --with pytest-cov --with pytest-timeout \
  -m pytest -q --timeout=120        # 582 passed
uvx ruff==0.17.3 check --select E,W,F,B --ignore E501,E402 src/freeflix_cli/
uv run --with coverage --with pytest --with pytest-timeout \
  python -m coverage run --source=src/freeflix_cli -m pytest -q
uv run --with coverage python -m coverage report | tail -3   # ~45 %
uv lock --check
```

## Pourquoi ces notes et pas 10/10

- **Fonctionnalités** : dépend entièrement de sites tiers qui changent ; 10/10
  supposerait un catalogue et des flux garantis, ce qui n'est pas le modèle.
- **Architecture** : les handlers répètent encore la navigation
  (recherche → saison → épisode) ; une couche de navigation générique serait
  la prochaine étape.
- **Multi-OS** : la CI couvre macOS/Windows, mais rien ne remplace un test
  physique sur les deux OS (verrous de fichiers, terminaux, polices).
- **Release** : la chaîne binaires est maintenant câblée et testée
  statiquement ; elle ne sera prouvée qu'au prochain tag.
- **Sécurité** : le proxy et les credentials sont traités, mais une dépendance
  tierce de déchiffrement et l'installateur `uv` restent des surfaces
  externes.
