# Dépannage

## Diagnostic de base

```bash
freeflix --version
freeflix --doctor
cat ~/.cache/freeflix-cli/freeflix.log | tail -50
```

`--doctor` affiche trois blocs utiles : **INSTALL** (module chargé, version du
code vs métadonnées), **BINARIES** (mpv, ffmpeg, yt-dlp, aria2c, chafa) et
**MPV CONFIG** (le dossier `~/.config/freeflix/mpv`, celui que l'app utilise).

## « Metadata and code disagree » / version mélangée

Deux installations se marchent dessus (ancien `pip`, nouveau `uv tool`, ou un
binaire dans le `PATH`).

```bash
which -a freeflix
uv tool uninstall freeflix-cli
uv tool install freeflix-cli
freeflix --doctor   # INSTALL doit afficher le même Code et Metadata
```

Sur Windows, ferme FreeFlix avant `uv tool upgrade` (fichiers verrouillés).

## Le terminal reste en mode souris / collage après une sortie

Corrigé en 2.1.0 (`_clean_exit` restaure souris, bracketed paste et curseur).
Si cela arrive encore, lance `reset` ou ferme l'onglet. Pour désactiver la
souris : `FREEFLIX_NO_MOUSE=1 freeflix`.

## Aucune affiche / pas de posters

- `chafa` absent → `freeflix --doctor` le signale ; installe-le
  (`sudo dnf install chafa`, `sudo apt install chafa`, `brew install chafa`).
- Terminal sans support d'images : les posters s'affichent en blocs colorés
  (c'est normal). Sixel/kitty est détecté automatiquement.
- Poster lent : le rendu chafa tourne en arrière-plan ; il apparaît sans
  appuyer sur une touche depuis 2.0.

## Une source ne répond plus

```bash
freeflix --doctor --sources   # teste recherche + résolution, source par source
```

- **Cloudflare / 403** : Papystreaming est connu comme bloqué ; Coflix peut
  demander un captcha. Réessaie plus tard ou change de source.
- Les domaines changent souvent : `data/source_portal.jsonc` sert de secours.
  Supprime `~/.cache/AutoFlixCLI/origins.json` pour forcer une re-résolution.

## Un lecteur affiche une pub de 30 s

Les flux de moins de 90 s sont marqués `⚠ 30s` et ne sont plus proposés comme
épisode. Si un lecteur reste mauvais, choisis-en un autre : les URLs et les
qualités sont analysées avant la lecture.

## Téléchargement bloqué / incomplet

Les fichiers sont préparés dans `~/Downloads/FreeFlix/.temp/`, vérifiés, puis
déplacés atomiquement. Un fichier `.incomplete` est conservé pour reprise.

```bash
freeflix --doctor            # yt-dlp / ffmpeg / aria2c présents ?
rm -rf ~/Downloads/FreeFlix/.temp   # repartir de zéro (perd la reprise)
```

Si un épisode échoue en batch, l'app retente en séquentiel (1 fragment à la
fois) ; annule avec `Échap Échap`.

## AniList ne se connecte pas

- Le token doit être un **token utilisateur** (pas le Secret du client).
- `freeflix --doctor` ne teste pas AniList : vérifie le token dans Réglages →
  AniList, puis relance.
- Un token expiré affiche un message clair ; recolle-en un nouveau depuis
  <https://anilist.co/settings/developer>.

## Windows

- Installe **Windows Terminal** (le vieux `cmd.exe` n'a pas le VT complet).
- Si `freeflix` n'est pas reconnu après l'installateur : ouvre un nouveau
  terminal (le PATH utilisateur est mis à jour dans le registre).
- Souris : `Windows Terminal` ≥ 1.18 ; sinon le clavier reste complet.
- Police Nerd : l'installateur la pose et configure Windows Terminal ; ferme
  **toutes** les fenêtres pour que la police s'applique.

## macOS

- `install-mac.sh` écrit dans `~/.config/freeflix/mpv` (dossier dédié).
- Apple Silicon : mpv arm64 natif est installé (pas Rosetta).
- Si Homebrew manque pour la police : `brew install --cask font-caskaydia-cove-nerd-font`.

## Repartir d'une configuration propre

```bash
mv ~/.local/share/AutoFlixCLI/progress.json ~/progress.backup.json
rm -rf ~/.cache/AutoFlixCLI
freeflix
```

Les téléchargements dans `~/Downloads/FreeFlix` ne sont jamais supprimés par
ces commandes.
