# Documentation

| Document | Contenu |
|---|---|
| [USAGE.md](USAGE.md) | menus, clavier/souris, sources, planning, téléchargements, langues |
| [ARCHITECTURE.md](ARCHITECTURE.md) | modules, pipeline de résolution, données, hot-patch |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | diagnostic, installations mélangées, sources, Windows/macOS |
| [RELEASE.md](RELEASE.md) | bump, tests, tag, PyPI, binaires, checksums |
| [CORRECTIONS-2.1.0.md](CORRECTIONS-2.1.0.md) | suivi constat par constat de l'audit 2.0.0 |
| [SCORECARD-2.1.0.md](SCORECARD-2.1.0.md) | réévaluation de la grille (tous les domaines ≥ 8,5) |
| [AUDIT-FREEFLIX-2.0-2026-11-04.md](AUDIT-FREEFLIX-2.0-2026-11-04.md) | audit initial (instantané) |
| [../SECURITY.md](../SECURITY.md) | modèle de sécurité et signalement |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | règles de contribution, tests, providers |

## En une minute

```bash
uv tool install freeflix-cli
freeflix
freeflix --doctor
```

Le code vit dans `src/freeflix_cli/` : `main.py` (accueil + réglages),
`handlers/` (un flux par source), `scraping/` (HTML + extracteurs),
`player_manager.py` (lecteurs + téléchargements), `proxy.py` (proxy local),
`preview_picker.py` (liste avec poster), `tracker.py` (état persistant).
