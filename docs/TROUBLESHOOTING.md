# Dépannage

## Le réflexe : `freeflix --doctor`

`--doctor` produit **un seul rapport exhaustif**, prévu pour être copié-collé
dans un ticket. L'objectif : quand quelqu'un a un problème, on lui demande son
`--doctor` — et on doit pouvoir diagnostiquer sans lui poser d'autres questions.

Il ne modifie rien, ne pose aucune question et n'écrit jamais dans tes données
d'appli. Chaque vérification est isolée et limitée dans le temps : un contrôle
en échec ne casse jamais le rapport.

```bash
freeflix --doctor                 # rapport complet (installation, OS, lecteurs, réseau…)
freeflix --doctor --sources       # + test live de chaque source (recherche + lecteurs + flux)
freeflix --doctor --players       # + résolution réelle des lecteurs par source (implique --sources)
freeflix --doctor --report        # écrit un .txt prêt à coller (dossier courant)
freeflix --doctor --report ~/freeflix.txt   # idem, à l'emplacement choisi
freeflix --doctor --json          # rapport machine-readable sur stdout
freeflix --doctor --upload        # + upload en Gist secret (nécessite `gh`)
freeflix --doctor --no-network    # sans sondes réseau (rapide / hors-ligne)
```

Le rapport complet prend ~2–4 s hors réseau ; `--sources`/`--players` ajoutent
des tests réseau avec un budget global (chaque source est bornée).

### Lire le rapport

L'en-tête donne **version (code + métadonnées), date UTC/locale, OS, terminal,
Python, durée et résumé** (`n PASS / n WARN / n FAIL / n SKIP`).

Chaque ligne de contrôle a la forme :

```text
  WARN  NET-03  AniList    api.anilist.co: DNS FAIL - gaierror: Name or service not known
        fix: switch DNS to 1.1.1.1 or enable a VPN, then test: getent hosts github.com
```

- `PASS` : OK. `WARN` : fonctionne mais dégradé / à surveiller.
- `FAIL` : cassé ou bloquant (lecture impossible, config corrompue, disque plein…).
- `SKIP` : non testé (autre OS, `--no-network`, budget épuisé).
- Le code (`NET-03`, `BIN-02`…) est repris dans **VERDICT → FIXES** avec l'action
  concrète à exécuter. Commence par le premier `FAIL`, puis les `WARN` de FIXES.

Le rapport est en **ASCII**, sur **78 colonnes** maximum : il reste lisible dans
un terminal 80 colonnes, un `cmd.exe` cp1252 et un commentaire GitHub.

### Ce que couvre le rapport

| Section | Contenu |
| --- | --- |
| `INSTALL` | binaire figé vs package, module réellement chargé, version code vs métadonnées, lanceurs en double |
| `SYSTEM` | OS/distro/kernel/arch, terminal (`TERM`, dimensions, TTY), encodage, locale, Python (venv/figé), mode d'install, ordre du `PATH` + doublons, droits des dossiers FreeFlix, dossier temporaire |
| `CONFIG & DISK` | chemins effectifs (données, cache, logs, téléchargements, mpv), intégrité de `progress.json`, réglages tracker (lecteur, langues, qualité, analyse, cache, thème), présence des jetons (jamais leur valeur), portails effectifs, espace disque |
| `BINARIES` | versions minimales mpv/ffmpeg/vlc/yt-dlp/aria2c/chafa, copies managées, commande d'install **exacte** pour ton OS |
| `PLAYERS (mpv / vlc)` | chemin réellement résolu par l'app + test de démarrage `mpv --version` / `vlc --version` |
| `MPV CONFIG & SHADERS` | `mpv.conf`, `input.conf`, script de position, et **contenu GLSL** des 5 shaders Anime4K (pas seulement leur présence) |
| `LOCAL PROXY` | bind 127.0.0.1, démarrage, `GET /player/heartbeat` local, arrêt propre, port libéré |
| `NETWORK` | DNS + TCP + TLS + expiration du certificat pour chaque hôte (GitHub, config distante, AniList, portails), blocage DNS/ISP, proxy système, resolveurs, FlareSolverr |
| `SOURCES & STREAMS` | par source : recherche live + (avec `--players`/`--sources`) résolution des lecteurs réels et sonde manifeste + premier segment HLS |
| `TERMINAL & IMAGES` | taille, chafa, protocole image (kitty/iterm/sixel/blocs), Nerd Font, souris, alt-screen, couleurs |
| `LOGS` | fichier de log, taille/rotation, dernières erreurs, motifs récurrents (403, 429, timeout…) |
| `STATE & CACHE` | historique/follows/épisodes vus, téléchargements interrompus, tailles de cache, cache des sorties |
| `WINDOWS` | binaires managés `.exe`, `%LOCALAPPDATA%`/`%APPDATA%` inscriptibles, VT console, page de code, chemins longs, Mark-of-the-Web, Defender, terminal hôte |

### Partager le rapport

```bash
freeflix --doctor --report          # → freeflix-doctor-AAAAMMJJ-HHMMSS.txt
freeflix --doctor --report rapport.txt
freeflix --doctor --json > rapport.json
freeflix --doctor --upload          # → URL de Gist secret (gh auth login requis)
```

Le rapport **ne contient aucun secret** : les jetons (AniList, OpenSubtitles,
`cf_clearance`) sont seulement signalés comme `set`/`unset`, jamais affichés.
Colle le fichier entier dans le ticket :
<https://github.com/freedy237/freeflix-cli/issues>

### Sources : OK / MORT-FOURNISSEUR / BUG-FREEFLIX

Avec `--sources`, chaque source est classée :

- **OK** — recherche + résolution + manifeste + premier segment vérifiés.
- **MORT-FOURNISSEUR** — Cloudflare, 403/429, DNS, embeds supprimés, flux
  expiré : ce n'est pas ta machine, réessaie plus tard ou change de serveur.
- **BUG-FREEFLIX** — exception de code (`AttributeError`, `KeyError`, parseur) :
  c'est un vrai bug, colle le rapport dans un ticket.

## « Metadata and code disagree » / version mélangée

Deux installations se marchent dessus (ancien `pip`, nouveau `uv tool`, ou un
binaire dans le `PATH`). Le rapport le montre en `INSTALL` (Code ≠ Metadata) et
les lanceurs en double dans `INSTALL → launchers`.

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
souris : `FREEFLIX_NO_MOUSE=1 freeflix`. Le rapport le signale dans
`TERMINAL & IMAGES → mouse`.

## Aucune affiche / pas de posters

- `chafa` absent → `freeflix --doctor` le signale (`TERMINAL & IMAGES → chafa`)
  avec la commande d'installation de ton OS.
- Terminal sans support d'images : les posters s'affichent en blocs colorés
  (c'est normal). `image protocol` indique ce qui a été détecté
  (kitty/iterm/sixel/`auto` = blocs). Sixel/kitty est détecté automatiquement.
- Poster lent : le rendu chafa tourne en arrière-plan ; il apparaît sans
  appuyer sur une touche depuis 2.0.

## Une source ne répond plus

```bash
freeflix --doctor --sources   # recherche + résolution + premier segment, source par source
```

- **Cloudflare / 403** : Papystreaming est connu comme bloqué ; Coflix peut
  demander un captcha. Réessaie plus tard ou change de source. Le rapport
  distingue `MORT-FOURNISSEUR (Cloudflare)`.
- **Toutes les sources en DNS FAIL** → le rapport lève un `NETWORK → internet
  FAIL` : c'est le DNS/FAI/VPN, pas FreeFlix.
- Les domaines changent souvent : `data/source_portal.jsonc` sert de secours.
  Le rapport liste les portails effectifs et leur origine (`default`/`remote`/
  `local`) dans `CONFIG & DISK`.
- Supprime `~/.cache/AutoFlixCLI/origins.json` pour forcer une re-résolution.

## Un lecteur affiche une pub de 30 s

Les flux de moins de 90 s sont marqués `⚠ 30s` et ne sont plus proposés comme
épisode. Si un lecteur reste mauvais, choisis-en un autre : les URLs et les
qualités sont analysées avant la lecture. `--doctor --players` montre le nom
réel des serveurs et l'état du premier segment.

## Téléchargement bloqué / incomplet

Les fichiers sont préparés dans `~/Downloads/FreeFlix/.temp/`, vérifiés, puis
déplacés atomiquement. Un fichier `.incomplete` est conservé pour reprise.
Sur Windows, ce chemin se trouve sous le dossier « Téléchargements » réel de
l'utilisateur (OneDrive/localisé), et `.temp` porte l'attribut Hidden.

```bash
freeflix --doctor            # yt-dlp / ffmpeg / aria2c présents ? disque libre ?
rm -rf ~/Downloads/FreeFlix/.temp   # repartir de zéro (perd la reprise)
```

Le rapport liste les téléchargements interrompus et la place libre
(`STATE & CACHE → interrupted downloads`, `CONFIG & DISK → disk (downloads)`).

Si un épisode échoue en batch, l'app retente en séquentiel (1 fragment à la
fois) ; annule avec `Échap Échap`.

## AniList ne se connecte pas

- Le token doit être un **token utilisateur** (pas le Secret du client).
- `freeflix --doctor` teste désormais **api.anilist.co** dans `NETWORK`
  (DNS/TCP/TLS) : un `WARN`/`FAIL` là indique un blocage réseau/FAI, pas le
  token. Le token lui-même n'est jamais affiché (`credentials` → `set`/`unset`).
- Vérifie le token dans Réglages → AniList, puis relance.
- Un token expiré affiche un message clair ; recolle-en un nouveau depuis
  <https://anilist.co/settings/developer>.

## Windows

Le rapport contient une section `WINDOWS` dédiée.

- Installe **Windows Terminal** (le vieux `cmd.exe` n'a pas le VT complet) ;
  `WINDOWS → console VT` et `terminal host` le confirment.
- Si `freeflix` n'est pas reconnu après l'installateur : ouvre un nouveau
  terminal (le PATH utilisateur est mis à jour dans le registre).
- Souris : `Windows Terminal` ≥ 1.18 ; sinon le clavier reste complet.
- Police Nerd : l'installateur la pose et configure Windows Terminal ; ferme
  **toutes** les fenêtres pour que la police s'applique.
- `WINDOWS → console codepage` doit être `65001` ; sinon `chcp 65001`.
- Un `mpv.exe` managé marqué **Mark-of-the-Web** se débloque avec
  `Unblock-File -LiteralPath "<chemin>"` (le rapport donne le chemin exact).

## Windows : antivirus (faux positif)

Defender (ou un antivirus tiers) peut signaler `scripts/install.ps1` ou
`freeflix-windows-x86_64.exe` comme :

- `Trojan:Win32/Commando.A!ml` / `Commando.C!ml`
- `Trojan:Script/Wacatac.*!ml`
- `Program:Win32/Wacapew.*!ml`

Le suffixe `!ml` = détection **heuristique** (machine learning), pas une
signature. Un installeur PowerShell non signé qui télécharge `uv`, écrit dans
le PATH et installe des paquets déclenche régulièrement ces faux positifs ;
c'est aussi le cas classique des binaires PyInstaller.

**Vérifier avant de faire confiance :**

1. Le script est public et lisible en entier :
   <https://github.com/freedy237/freeflix-cli/blob/main/scripts/install.ps1>
2. Compare le SHA-256 du binaire téléchargé avec `SHA256SUMS` de la release :
   `Get-FileHash .\freeflix-windows-x86_64.exe -Algorithm SHA256`
3. Envoie le fichier sur <https://www.virustotal.com> : quelques détections
   heuristiques parmi 70 moteurs = faux positif probable.

**Débloquer :**

```powershell
# Fichier téléchargé depuis Internet : retire la marque "Mark of the Web"
Unblock-File .\install.ps1
Unblock-File .\freeflix-windows-x86_64.exe

# Restaure depuis la quarantaine (Sécurité Windows → Protection contre les
# virus → Historique des menaces → Autoriser sur l'appareil), puis ajoute une
# exclusion sur le dossier de l'app si nécessaire :
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"
```

Signale le faux positif à Microsoft :
<https://www.microsoft.com/en-us/wdsi/filesubmission>

## Windows : mpv introuvable ou ne démarre pas

Depuis 2.4.3, l'installateur pose un **vrai mpv CLI** (`shinchiro.mpv`, puis
`mpv-player.mpv-CI.MSVC` en secours) au lieu de `mpv.net`. `mpv.net` ne fournit
que `mpvnet.exe`, une interface graphique qui n'accepte pas toujours les
options utilisées par FreeFlix (lecture sur stdin, IPC, `--config-dir`) —
d'où les échecs de lecture.

```powershell
# Vérifier ce que FreeFlix trouve (PLAYERS → mpv path / mpv startup)
freeflix --doctor
winget install --id shinchiro.mpv -e
# ou, si le paquet n'existe plus :
winget search mpv
```

Après installation, ouvre un **nouveau** terminal (le lien winget est dans
`%LOCALAPPDATA%\Microsoft\WinGet\Links`). Si seul `mpvnet.exe` est présent,
FreeFlix l'utilise en dernier recours mais peut refuser certains flux : dans ce
cas installe VLC (`winget install --id VideoLAN.VLC -e`) et choisis VLC comme
lecteur des matchs.

## macOS

- `install-mac.sh` écrit dans `~/.config/freeflix/mpv` (dossier dédié).
- Apple Silicon : mpv arm64 natif est installé (pas Rosetta).
- Si Homebrew manque pour la police : `brew install --cask font-caskaydia-cove-nerd-font`.
- Le rapport donne les commandes `brew install …` pour tout binaire manquant.

## Repartir d'une configuration propre

Avant de supprimer quoi que ce soit, garde le rapport (`--report`) : il montre
si le problème vient de la config ou d'ailleurs.

```bash
mv ~/.local/share/AutoFlixCLI/progress.json ~/progress.backup.json
rm -rf ~/.cache/AutoFlixCLI
freeflix
```

Les téléchargements dans `~/Downloads/FreeFlix` ne sont jamais supprimés par
ces commandes.
