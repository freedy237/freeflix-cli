# Changelog

## 2.4.0

- **Match regroupé par statut** : sections `En direct (n)`, `À venir (n)`,
  `Terminés (n)` avec une **grille à colonnes fixes** (chaîne · heure ·
  équipes · compétition). Les largeurs sont calculées en cellules réelles
  sur tout l'écran, donc les heures et les équipes sont parfaitement
  alignées d'une section à l'autre.
- **Badges de chaîne génériques** : `beIN N` → `BN` (toutes les chaînes),
  `Dubai Sports N` → `DSN`, et toute autre chaîne reçoit une abréviation
  courte (≤ 6 caractères).
- **Noms d'équipes corrigés** : dictionnaire de clubs embarqué
  (`data/clubs.json`, ~430 entrées) utilisé avant la traduction machine,
  plus une liste de rejets pour les traductions littérales. Fini
  « ليل → nuit », « مان يونايتد → Homme Uni », « انجيه → Enregistrez-le ».
- **`LIVE` traduit** en `EN DIRECT` (FR).
- **Logos de chaînes** : index iptv-org embarqué
  (`data/channel_logos.json`, ~30 k entrées) pour afficher le logo d'une
  chaîne à partir de son nom.
- Cache de traductions versionné : les valeurs erronées des anciennes
  versions sont automatiquement régénérées.
- **Contrôle avant lecture d'un match** : le manifeste est testé (DNS + HLS)
  avant de lancer le lecteur. Une chaîne retirée ou bloquée affiche
  « Impossible de lire ce match : serveur injoignable » au lieu d'ouvrir un
  lecteur qui se referme aussitôt. Les chaînes Dubai Sports sont concernées
  aujourd'hui (CDN `mgmlcdn.com`/`mangomolo.com` ne résout plus).
- 614 tests au vert, ruff OK.

## 2.3.3

- **Match : badges de chaîne généralisés**. beIN 1..N → `B1`..`BN`
  (plus seulement 1–4), Dubai Sports N → `DSN`, et toute autre chaîne reçoit
  une abréviation courte (`Canal+ Sport 2` → `CS2`, `Sky Sports F1` → `SSF`,
  `ESPN` → `E`). Fin des libellés complets dans la liste.
- Testé sur le catalogue courant (18 matchs, 8 chaînes différentes).

## 2.3.2

- **Match buffer 20 s, démarrage rapide** : mpv utilise
  `cache-secs=20` + `demuxer-readahead-secs=20` + `cache-pause=no`
  (première image en ~1 s sur le test synthétique) ;
- VLC revient à la lecture **ffmpeg → TS** (celle qui ne s'arrêtait pas),
  sans cache réseau 20 s : démarrage immédiat et flux continu ;
- la lecture reste au bord du live tout en gardant 20 s de marge pour
  les connexions instables.

## 2.3.1

- **Qualités Match prêtes pour le futur** : 4K/2160p (≥ 15,0 Mbps,
  ~6,75 Go/h) et 1440p (≥ 8,0 Mbps, ~3,60 Go/h) ; une qualité inconnue
  garde une estimation prudente au lieu de casser l'affichage.
- Tests supplémentaires avec des équipes/compétitions arbitraires
  (Al Ahly / Zamalek) et des chaînes hors beIN : la traduction et
  l'affichage restent dynamiques.
- 607 tests au vert, ruff OK.

## 2.3.0

- **Match** : la chaîne est affichée entre parenthèses **devant** le match,
  avec un badge court (`beIN SPORTS 1..4` → `B1..B4`), ex.
  `(B4) ● LIVE 20:45 · Toulouse VS Strasbourg`.
- **Qualités Match** : chaque ligne affiche désormais la résolution, le débit
  minimum estimé et la consommation horaire estimée, ex.
  `HD (1080p) · ≥ 5.0 Mbps · ~2.25 Go/h`, `SD (720p) · ≥ 2.5 Mbps · ~1.13 Go/h`,
  `Low (480p) · ≥ 1.0 Mbps · ~0.45 Go/h` ; `Auto` reste en bas.
- 604 tests au vert, ruff OK.

## 2.2.2

- Menus **qualité** et **choix du lecteur** en plein écran : souris alignée
  (survol + clic) sur Linux et Windows.
- **Anime4K désactivé par défaut** : activation explicite par l'utilisateur
  (`CTRL+1` / `CTRL+2`, `CTRL+0` pour couper), conseil affiché en bas de mpv
  pendant 5 s, migration des anciennes configs sans toucher aux shaders perso.
- Entrée du menu principal renommée **Films, Séries & Anime** (traduite) ;
  la liste des providers et son fonctionnement restent inchangés.
- **Configs lecteurs isolées** : mpv utilise toujours son dossier dédié
  (`--config-dir`, sinon `--no-config`) ; VLC est lancé avec
  `--ignore-config --no-media-library --no-plugins-cache`. Les réglages
  personnels de la machine ne sont ni lus ni modifiés.
- Derniers correctifs Windows/mise à jour (ancrage console, VT input, redémarrage
  par nouveau processus, recherche uv/pipx hors PATH).
- 602 tests au vert, ruff OK.

## 2.2.1

- **Compatibilité Windows** :
  - ancrage souris des menus inline via `GetConsoleScreenBufferInfo`
    (fini les clics décalés) ;
  - activation VT input avec `ENABLE_EXTENDED_FLAGS` pour que Windows
    Terminal transmette vraiment les rapports SGR ;
  - écran des qualités en plein écran, ancrage fiable sur tous les OS ;
  - redémarrage après mise à jour via un nouveau processus sur Windows
    (`os.execv` n'est pas fiable avec un interpréteur Python verrouillé).
- **Mises à jour** : correction de la comparaison de version en mode
  source, détection `uv` resserrée, commande de mise à jour adaptée à
  l'installeur réel (uv/pipx/pip).
- VLC : lecture par **ffmpeg → TS** comme mpv (plus de fin de playlist
  HLS), timestamps normalisés, audio calé.
- 600 tests + tests Windows dédiés au vert, ruff OK.

## 2.2.0

- **Nouvel onglet Match** dans le menu principal : matchs de football du
  catalogue YacineTV, à l'heure du Cameroun (UTC+1), avec badge `LIVE`,
  à venir et terminés.
- Qualités HD/SD/Low + **Auto** (meilleure disponible), choix du lecteur
  **mpv / VLC** mémorisé, souris en clic seul sur les qualités.
- Noms d'équipes et de compétitions **traduits dynamiquement** en français
  ou anglais (cache local, aucun mapping en dur).
- Flux live servis par un mini-proxy HLS local : en-têtes UTF-8 exacts et
  segments `.php/.pdf` réécrits pour mpv/VLC.
- mpv en direct : cache mémoire 3 s, démarrage au bord du live, plus de
  cache disque de 30 min.
- 598 tests au vert, ruff OK.

## 2.1.2

- **Téléchargements Vidzy / fsvid / uqload réparés** : l'URL passée à yt-dlp
  traverse toujours le proxy local curl_cffi (fingerprint navigateur), mais
  elle porte maintenant le **jeton de capacité `?k=`** et le **jeton
  d'en-têtes `?h=`** ajoutés en 2.1. Sans eux, le proxy répondait 403 : le
  streaming fonctionnait, le téléchargement échouait.
- Vérifié en réel sur FROM S1E1 : fsvid et vidzy résolus, yt-dlp natif a
  téléchargé 34/316 fragments via le proxy sans erreur.
- Test du flux « Nouveautés » isolé des séries réellement suivies (plus de
  dépendance à l'état local de la machine).
- **CI macOS séparée** : les runners macOS GitHub sont souvent indisponibles
  (« job was not acquired »), ce qui rendait la CI rouge sans bug de code.
  macOS passe dans `macos.yml` (manuel + hebdomadaire) ; la CI de push reste
  Linux + Windows.
- 588 tests au vert, ruff OK. Aucun changement d'interface : le code écran
  reste celui de la 2.1.1.

## 2.1.1

- **Binaire Windows réparé** : `--doctor` (et le reste de l'interface) force
  UTF-8 sur stdout/stderr quand la console est en cp1252 ; le smoke test du
  binaire autonome passe à nouveau.
- 586 tests au vert, ruff OK.

## 2.1.0 — Fiabilité, sécurité et cohérence

Version de consolidation : l'audit complet de la 2.0.0 a été appliqué de bout
en bout, sans changement de fonctionnalité visible.

### Téléchargements

- **Reprise séquentielle réparée** : `_verify_download()` renvoie
  `(ok, reason)` ; le retry le comparait à `"ok"` et jetait chaque fichier
  valide. La reprise repart maintenant des fragments déjà téléchargés et
  conserve le fichier en `.incomplete` après le dernier échec.
- **Téléchargement atomique** : `_download()` écrit en `.part` puis
  `os.replace` ; un transfert coupé ne laisse plus un faux fichier complet.
- **Garde-fou** : plafond de 6 h sur un sous-processus non-TTY figé ;
  `terminate()` escalade en `kill()` après 5 s ; l'annulation atteint aussi
  la reprise séquentielle.
- **Métadonnées de reprise assainies** : `Cookie`, `Authorization`,
  `Proxy-Authorization`, `X-Api-Key` et `X-Auth-Token` sont retirés du JSON
  `.freeflix-resume.json`, écrit en `0600`.
- **Noms de fichiers Windows** : noms réservés (`CON`, `NUL`, `COM1…`),
  points/espaces finaux et caracteres de contrôle neutralisés.
- **Sous-titres temporaires** : les `freeflix_sub_*` / `freeflix_os_*` de plus
  de 24 h sont balayés au démarrage.

### Sécurité

- **En-têtes du proxy opaques** : les cookies de gate (`vz_ok`, `fsv_pe`, …)
  ne sont plus sérialisés en JSON dans les URLs des manifestes ; un jeton
  local de 24 caractères les remplace (anciennes URLs toujours acceptées).
- **TLS DoH vérifié** : le repli DNS ne désactive plus la vérification du
  certificat (MITM possible auparavant).
- **Toasts Windows** : le XML passe par un fichier temporaire au lieu d'être
  interpolé entre quotes simples dans PowerShell (injection via un titre
  piégé).
- **PATH Windows** : remplacement de `setx PATH … "%PATH%"` (littéral,
  tronqué à 1024) par une écriture registre `REG_EXPAND_SZ` préservant les
  variables.
- **URLs signées masquées** dans les messages (`?…`), plus de lien CDN
  complet dans le terminal ou les logs.
- **Jeton de capacité du proxy** : chaque URL média porte `?k=<jeton>` propre
  au processus ; un autre programme local ne peut plus utiliser le proxy comme
  relais SSRF/en-têtes.
- **Checksums publiées** : `SHA256SUMS` pour le wheel/sdist et un `.sha256`
  par binaire autonome.

### Stabilité

- `progress.json` : validation de forme au chargement (une clé de type
  inattendu ne bloque plus le démarrage) + tableau de bord protégé par
  `try/except`.
- Sortie propre : `os._exit` remplacé par une restauration explicite du
  terminal (souris, bracketed paste, curseur, écran alterné) puis
  `SystemExit`.
- Souris Windows : activation de `ENABLE_VIRTUAL_TERMINAL_INPUT` sur stdin
  (sans elle, `?1000h` était envoyé sans qu'aucun rapport n'arrive).
- Boucle infinie du fil d'Ariane corrigée sur terminal ≤ 8 colonnes ; EOF
  sur stdin traité comme Esc (plus de boucle à 100 % CPU).
- `Esc` : les menus « Reprendre / Parcourir » ont maintenant une vraie ligne
  « ← Retour », donc Esc ne déclenche plus l'action voisine.
- Registre des sources reconstruit au changement de langue : les noms de
  sources sont traduits immédiatement, et les doublons de branches
  HiAnime/GoldenAnime ont disparu.
- Déduplication des lecteurs : deux pistes de langue distinctes du même hôte
  (« voe vostfr » / « voe vff ») ne sont plus fusionnées.
- Reprise de flux : plafond de 5 min sans octet (le buffering infini cachait
  un CDN mort).
- Analyse des lecteurs : budget porté à 55 s (60 s pour le menu étendu) et
  cache qualité ramené à 5 min pour ne pas servir un lien signé périmé.
- mpv IPC Windows : lecture du named pipe via thread + file d'attente, donc
  `stop()` et les timeouts ne bloquent plus.
- macOS : chemins de socket AF_UNIX raccourcis (limite de 104 octets) avec
  repli sur `/tmp` quand `TMPDIR` est long.

### Installation / multi-OS

- `setup_done` n'est plus posé si les fichiers mpv ou les shaders ont échoué :
  le wizard réessaie au lancement suivant.
- `--doctor` : ffmpeg est testé avec `-version` (plus de faux « BROKEN ») et
  le dossier inspecté est bien `~/.config/freeflix/mpv`.
- macOS : `install-mac.sh` écrit dans le dossier FreeFlix (et non le mpv
  global) ; builds mpv **arm64** natifs sur Apple Silicon et Windows ARM.
- Installeurs : paquets système installés un par un (un paquet optionnel
  manquant n'annule plus tout), TLS 1.2/1.3 explicite et uv ARM64 sur
  Windows, shaders S + VL installés comme le charge `mpv.conf`.
- `selectors.jsonc` embarqué est enfin lu au démarrage (il n'était que
  téléchargé à distance) ; chemins PyInstaller ajoutés (`--add-data`).

### UI / accessibilité

- `selection_text` retombe sur `black` (et non `white`) pour les thèmes
  anciens ; le wordmark suit le thème actif au lieu de rester ambre.
- `skeleton()` respecte `reduce motion` (une seule image statique).
- Le tableau de bord n'écrit plus `progress.json` à chaque repaint.
- `--version` / `--help` / `--doctor` ne sont plus implémentés deux fois.
- `select_with_preview` (787 lignes) est extrait dans `preview_picker.py` :
  `cli_utils.py` passe de 2 896 à 2 166 lignes, avec un ré-export paresseux
  pour ne pas casser les imports existants.
- Le preview utilise désormais **le décodeur clavier partagé** (timeout
  inclus) : le troisième décodeur, avec sa propre gestion du collage et de
  l'ESC, a disparu.
- **Filtre protégé des rapports souris** : un rapport SGR coupé en fin de
  lecture est conservé puis complété au lieu d'être tapé (`/ 4;10M…`) ; le
  mode filtre coupe le suivi souris et le champ de recherche utilise un suivi
  « clic seulement » (pas de flood de mouvement).
- Le menu **Réglages** (290 lignes) est extrait de `main()` : la boucle
  d'accueil passe de 660 à 359 lignes.

### CI / release / tests

- La release exige désormais la suite de tests, le lint, et
  `pyproject.version == tag` ; `twine check` avant publication.
- Binaires : déclenchement explicite par `workflow_dispatch` depuis la
  release (l'événement `release: published` créé par `GITHUB_TOKEN` ne
  démarrait aucun workflow), `--add-data`, smoke test `--doctor`.
- CI étendue à macOS et Python 3.11/3.13 ; build du wheel et smoke test
  d'installation.
- Tests : isolation du dossier de binaires gérés (plus de `rmtree` réel),
  suite offline (plus de GET GitHub), 16 tests de non-régression pour cet
  audit.
- Couverture mesurée ~45 %, plancher CI relevé de 15 à **40 %** ;
  `pytest-timeout` (120 s) et `ruff==0.17.3` épinglé dans la CI.
- Tests dédiés `cli.py`, `doctor.py`, `providers_registry`, `config_loader`,
  `install_health`, thèmes/UI, métadonnées de reprise, noms Windows, garde-fous
  de release et IPC Windows.
- 586 tests au vert, ruff OK.

## 2.0.0 — Cinéma Noir

- **Nouvelle identité visuelle** : **Cinema Noir** devient le thème par
  défaut. Ivoire chaud, ambre, bleu poussière sur fond noir. Les thèmes clairs
  pour terminaux à fond blanc ont été retirés ; les anciens thèmes sombres
  (Gruvbox, Dracula, Catppuccin, Nord…) restent disponibles.
- **Système de design 2.0** : tokens sémantiques (`surface`, `text`, `muted`,
  `border_soft`, `selection`…) et primitives réutilisables (`ui.wordmark`,
  `ui.rule`, `ui.section`, `ui.panel`) au lieu de couleurs codées en dur.
- **Wordmark compact** : « FreeFlix » en deux tons, sans lettres espacées.
  En Cinema Noir il garde en permanence les couleurs de la palette
  (ambre `#E6B45E` + ivoire `#F4EEE2`), et non un simple noir/blanc ; les
  autres thèmes suivent leur propre accent. La lumière qui passe sur le
  cadre ne doit pas le repeindre en blanc.
- **Accueil éditorial** : statistiques vivantes, section « Continuer »,
  « Nouveautés » et barres de progression dans le rectangle arrondi de
  l'accueil. Le cadre reprend exactement la couleur des deux traits qui
  encadrent le bandeau du haut (`border_soft`, gris-bleu #2C2C36) sur le
  thème Cinema Noir ; la lumière ambre le parcourt par-dessus. Le panneau est
  redessiné à 30 fps (une cellule de bord par image) pour un déplacement
  fluide au lieu de sauts de plusieurs cellules. Les titres de section
  gardent leur casse naturelle (« Reprendre », « Nouveautés »).
- **Menus et fiches** : curseur `▸ ▌` (rail ambre, texte ivoire, plus de
  reverse plein écran), en-têtes filaires, métadonnées discrètes, espacement
  cohérent ; le poster reste l'élément central.
- **Accessibilité** : contrastes vérifiés, aucune information portée par la
  couleur seule, animations respectant `reduce motion`, affichage testé en
  80×24 sur fond noir.
- **Release GitHub** : les notes incluent désormais les installateurs
  Linux/macOS et Windows en une ligne.
- **Tests** : 533 tests au vert, ruff OK, imports Python 3.9 OK.

## 1.16.11

- **Retour du planning instantané** : après avoir regardé un épisode lancé
  depuis le planning, l'app ne bloque plus au retour. La vérification des
  posters modifiés (un HEAD par anime, jusqu'à 4 s chacun) tourne maintenant
  en **arrière-plan** : le menu se réaffiche immédiatement.
- **Curseur conservé** : le planning reste positionné sur l'anime que tu
  viens de regarder (au lieu de revenir tout en haut de la liste), et le jour
  sélectionné est également conservé.
- **Tests** : 525 tests au vert, ruff OK, imports Python 3.9 OK.

## 1.16.10

- **Suivre un anime depuis le planning** : le menu d'un anime du planning
  propose maintenant **« Suivre cet anime »** (et « Ne plus suivre »). Plus
  besoin de lancer un épisode : la série entre dans Nouveautés.
- **Base de suivi** : au moment du suivi, l'app mémorise le dernier épisode
  actuellement listé. Quand un **épisode suivant** sort, il apparaît dans
  Nouveautés (« Série — Saison · Épisode »).
- **Historique + suivis** : Nouveautés combine les animes déjà regardés et
  ceux suivis depuis le planning, sans doublon. Regarder un épisode met aussi
  à jour la base du suivi.
- **Quand tu le vois, ça part** : ouvrir l'élément le retire du badge et met
  à jour la base ; l'épisode de la semaine suivante réapparaît tout seul.
- **Vérifié** : suivi sans historique, nouveau épisode, épisode non encore
  sorti (planning `released=false`), épisode déjà vu et désabonnement.
- **Tests** : 525 tests au vert, ruff OK, imports Python 3.9 OK.

## 1.16.9

- **Nouveautés respecte le planning** : Anime-Sama pré-crée la page du
  prochain épisode, donc la liste des épisodes peut déjà contenir un épisode
  **pas encore sorti**. Nouveautés vérifie maintenant l'état `released` du
  planning : tant que l'épisode n'est pas sorti, il n'est pas annoncé ; à sa
  sortie, il apparaît.
- **Dernier épisode réellement sorti** : si l'épisode de la semaine est
  encore en attente, l'app revient à l'épisode précédent. Exemple : épisode
  12 pas encore sorti + tu as vu l'épisode 11 → rien ; épisode 12 sorti →
  Nouveautés affiche « Épisode 12 ».
- **Quand tu le vois, ça part** : ouvrir l'élément le marque comme lu et le
  retire du badge. La clé contient le numéro d'épisode, donc l'épisode de la
  semaine suivante réapparaît automatiquement.
- **Vérifié** : avec ton historique actuel, 0 nouveauté (tes épisodes de la
  semaine sont déjà vus) ; les tests couvrent épisode non sorti, épisode
  précédent et épisode sorti.
- **Tests** : 521 tests au vert, ruff OK, imports Python 3.9 OK.

## 1.16.8

- **Nouveautés = nouveaux épisodes des animes que tu regardes** : le flux ne
  se contente plus de détecter une nouvelle saison. Pour chaque série
  Anime-Sama de l'historique, il compare le **dernier épisode disponible**
  avec l'épisode que tu as regardé. Exemple : tu t'arrêtes à l'épisode 5,
  l'épisode 12 sort → il apparaît dans Nouveautés.
- **Libellé clair** : « Série — Saison 1 · Épisode 12 ». En ouvrant l'élément,
  le menu des épisodes se positionne directement sur le nouvel épisode.
- **Ça part quand tu l'as vu** : ouvrir un élément de Nouveautés le marque
  comme lu et le retire du badge d'accueil. La clé contient le numéro
  d'épisode : quand un **épisode suivant** sort, il réapparaît tout seul.
- **Vérifié en direct** : deux nouveautés détectées (Avatar — Saison 1 ·
  Épisode 9, Sentai Daishikkaku — Saison 2 · Épisode 12).
- **Tests** : 518 tests au vert, ruff OK, tests Python 3.9 OK.

## 1.16.7

- **Retour à une première page, comme sur le site** : French-Stream affiche
  désormais **une page de résultats** (25 cartes : les séries d'abord, puis
  les films) avec une ligne **« Afficher la suite »**, au lieu de charger les
  191 résultats d'un coup. Chaque clic charge la page suivante et l'ajoute à
  la liste ; le compteur se met à jour.
- **FROM reste en premier** : les 6 séries de la première page (FROM,
  From Dusk Till Dawn, Stranger Things…) sont conservées, avec leur choix de
  saison. Le correctif 1.16.6 n'est donc pas perdu.
- **Cache par page** : revenir sur une page déjà vue est instantané ; une
  ancienne liste complète (v3) n'est plus utilisée (clé `search-page-v4`).
- **Tests** : 512 tests au vert, ruff OK, imports Python 3.9 OK.

## 1.16.6

- **Séries French-Stream visibles** : les cartes « série » du site
  (`search-item search-series`) n'ont ni `onclick` ni `<a>` — les saisons
  sont dans un attribut `data-seasons`. L'app les ignorait donc totalement :
  « FROM », la première série du site pour la recherche *from*, n'apparaissait
  pas. Le parseur lit maintenant ces cartes ; **FROM arrive en premier** avec
  ses **4 saisons**.
- **Choix de la saison** : sélectionner une série affiche d'abord
  « Saison 1…N » (menu inline, poster conservé), puis la langue et les
  épisodes de la saison choisie. Avant, même en forçant l'URL, seule la
  saison 1 était accessible.
- **Recherche complète** : *from* renvoie désormais **191 résultats**
  (185 films + 6 séries) au lieu de 19, et le cache inclut les saisons
  (clé `search-cards-v3`, les anciennes listes tronquées sont ignorées).
- **Vérifié en direct** : FROM saisons 1 à 4 → 10 VF + 10 VOSTFR chacune.
- **Tests** : 513 tests au vert, ruff OK, imports Python 3.9 OK.

## 1.16.5

- **French-Stream : TOUS les résultats** (le vrai « 19 au lieu de 185 »).
  L'endpoint AJAX renvoie **une page par requête** : 19 cartes page 1, puis
  25 par page. L'app s'arrêtait à la page 1, d'où « From » → 19 résultats
  alors que le site en a **185**. La recherche parcourt maintenant les pages
  jusqu'à la dernière (arrêt sur page vide ou répétée), avec un plafond de
  20 pages / 12 s pour ne pas marteler le site. Vérifié : **From = 185
  résultats** (page 8), Naruto = 12, Avatar = 7 ; la liste complète est mise
  en cache 5 min (2ᵉ recherche instantanée).
- **Cache invalidé** : une ancienne liste tronquée (issue de la page 1) ne
  peut plus être resservie — nouvelle clé de cache `search-cards-v2`.
- **Même vérification sur les autres sources** :
  - **Coflix** : l'index REST passe à **100 résultats** (la page `/?s=`
    n'affiche que 16 cartes pour « the ») et reste fusionné avec les
    posters de la page HTML.
  - **HiAnime** : la recherche est paginée (34 page 1, 30 page 2…) ;
    l'app parcourt maintenant **4 pages (~120 séries)** au lieu de la
    première seulement.
  - **Nyaa** : **75 torrents** au lieu de 20 (la page du site en liste 75).
  - **YTS** : **50 films** au lieu de 20 (limite de l'API YTS).
  - **Anime-Sama** : tout le catalogue tient sur une page (48 cartes, 46
    watchables) — aucun changement nécessaire.
  - **French-Manga** : l'AJAX du site ignore le paramètre `page` et plafonne
    à 20 ; l'app affiche donc la même liste que le site.
  - **Papystreaming** : toujours bloqué par Cloudflare (403 upstream).
- **Tests** : 511 tests au vert (pagination French-Stream + HiAnime, arrêt
  sur page répétée), ruff OK, import complet vérifié sous Python 3.9.

## 1.16.4

- **Correctif Python 3.9** : `scraping/anime_sama.py` utilisait une annotation
  `str | None` sans `from __future__ import annotations`, ce qui faisait
  échouer l'import du module (donc de l'app) sur Python 3.9. Le filet de
  sécurité « dernière copie du catalogue servie si le réseau tombe » de
  1.16.3 est conservé.
- **Vérifié** : imports complets + **508 tests** passent sous **Python 3.9**
  et sous Python 3.12, ruff OK.

## 1.16.3

- **Plus de résultats perdus** : l'app peut maintenant afficher PLUS de
  résultats que le site, jamais moins.
  - **Coflix** : la page `/?s=` ne rend que quelques cartes (3 pour
    « Naruto ») alors que l'index WordPress en contient 5, dont les séries et
    les pages `/anime/`. Les deux index sont désormais **fusionnés**
    (posters de la page HTML + complétude du REST), sans doublon. Et la liste
    fusionnée est mise en cache 10 min : **44 s → 0 s** pour la même
    recherche.
  - **French-Stream** : la recherche mettait en cache le corps brut, y
    compris la page anti-robot → « Aucun résultat » pendant 5 minutes. Seule
    une liste **non vide** est maintenant mise en cache. Le parseur accepte
    les deux styles de guillemets, les cartes sans `.search-title` (titre pris
    dans l'image/l'URL) et fusionne les cartes dupliquées.
  - **Anime-Sama** : une coupure réseau passagère vidait la recherche ; la
    dernière copie valide du catalogue est maintenant servie à la place.
- **Compteur visible** : French-Stream, French-Manga et Coflix affichent
  désormais « N résultat(s) trouvé(s) » après chaque recherche — un résultat
  vide ne peut plus passer pour une panne silencieuse.
- **AniList** : la recherche de correspondance remonte 20 candidats au lieu
  de 10 (moins de « aucun match » sur les titres longs).
- **Audit complet des sources** (28 contrôles en direct) : **27 OK**. Seul
  Papystreaming reste bloqué par Cloudflare (403 upstream), les autres
  sources (Anime-Sama, French-Stream, GoldenMS, HiAnime, GoldenAnime,
  Coflix, French-Manga, YTS, EZTV, Nyaa) répondent.
- **Tests** : 508 tests au vert, ruff OK.

## 1.16.2

- **Vidzy réparé (la vraie cause)** : le lecteur d'un embed vidzy est encodé
  dans un « packer » JS (Dean Edwards). La vraie URL `sources:[{src:"…"}]`
  était donc invisible, et le seul m3u8 présent dans la page était le leurre
  `s1.fsvid.lol/troll/master.m3u8` d'où « ça marche sur certains films,
  jamais sur d'autres ». Un décodeur du packer est ajouté : **vidzy et
  vidzy.live se résolvent désormais systématiquement** (master + segments
  vérifiés).
- **fsvid / premium** : même décodeur, même résultat — **13/13 films**
  ouverts au lieu de « parfois ».
- **Faux positifs supprimés** : les embeds qui ne peuvent jamais lire
  (`File was locked by administrator`, `File Not Found`, `File expired`,
  `We can't find the video`, `video record missing`) sont détectés et
  retirés du menu au lieu d'afficher une fausse qualité. Les hôtes morts en
  amont (filemoon/byse, mixdrop, minochinos, netu…) ne sont plus proposés.
- **DoodStream** : une URL proxy kokoflix (`*_go.php?id=…`) demande
  maintenant `pass_md5` sur le vrai lecteur (playmogo) et reconstruit l'URL
  média comme le navigateur (suffixe + token) — vérifié **206 + 65 Ko lus**.
- **Voe** : le stub `Loading...` (redirect JS + jeton) est résolu : plus de
  ligne inutilisable affichée.
- **Qualité plus juste** : l'intro `.mp4` renvoyée par certains lecteurs
  n'est plus prise pour le flux de l'épisode.
- **Vérification en direct** (6 films, tous les lecteurs) : fsvid 13/13,
  vidzy 15/15, uqload 11/11 valides — les 1 uqload et 2 voe restants sont
  des fichiers réellement supprimés/lockés chez l'hébergeur et sont
  maintenant masqués.
- **Tests** : 502 tests au vert, ruff OK.

## 1.16.1

- **Anime-Sama réparé** : la recherche, les fiches et les saisons passent
  désormais par la cascade réseau partagée (`cf_get` : réessais, requête
  simple puis DNS-over-HTTPS) au lieu d'un `scraper.get()` direct. Une
  coupure DNS/TLS passagère sur `anime-sama.to` faisait croire que toute la
  source était morte (« Could not connect ») alors que le site répondait
  normalement une seconde plus tard. Vérifié en direct : recherche,
  `get_series()` et `get_season()` (293 épisodes VOSTFR/VF sur Boruto).
- **Tests** : 494 tests au vert, ruff OK.

## 1.16.0

- **Navigation sans effacement** : les menus saison, langue, épisode, lecteur,
  qualité et sous-titres sont désormais **inline partout** (Anime-Sama,
  French-Stream, French-Manga, GoldenMS, GoldenAnime, HiAnime, Coflix,
  Papystreaming, AniList, YTS/Nyaa, historique). Le poster et le contexte
  restent affichés ; « Retour » ne nettoie plus l'écran. Le flux « Nouveautés »
  (planning Anime-Sama) affiche lui aussi le poster avant les menus.
- **Performances** :
  - French-Stream : cache des pages/JSON (5 min) et sondage de vie des lecteurs
    en **HEAD parallèle** (4 s max) au lieu d'une extraction complète :
    sélection d'un film **93 s → 1,3 s** à froid, **0,03 s** au retour.
  - French-Manga : cache des recherches (5 min) et des listes d'épisodes
    (5 min) : recherche **7,4 s → 0,003 s**, épisodes **2,2 s → 0,003 s**.
  - Durée HLS mémorisée (3 min) : l'analyse de qualité et la lecture ne
    téléchargent plus deux fois la même playlist de 1100 segments.
  - HiAnime : la liste des serveurs d'un épisode est mémorisée 5 min, donc
    revenir sur un épisode ne relance plus la requête.
  - Posters : seuls les 8 résultats autour du curseur sont rendus par chafa ;
    les autres sont seulement téléchargés, ce qui garde les longues listes
    fluides.
- **Faux positifs** : après analyse, les lecteurs morts (`✗`) et les vidéos de
  moins de 90 s sont retirés du menu ; s'ils échouent tous, un avertissement
  clair s'affiche au lieu de laisser croire à une source valide.
- **Faux positifs « vidéo de 30 s »** : l'analyse de qualité mesure désormais
  la durée réelle du flux. Un flux HLS de moins de 90 s est affiché `⚠ 30s`
  au lieu d'une fausse qualité `720p ~1.0 Mbps`, et le téléchargement refuse
  de publier un extrait.
- **Cohérence UI** : plus d'emoji codés en dur pour la langue, le lecteur, la
  qualité et les sous-titres — tout passe par `icon()` (mode emoji/Nerd Font).
- **AniList** : un jeton invalide ou expiré affiche maintenant un message
  clair au lieu d'une erreur HTTP brute ; les erreurs passagères (timeout,
  429, 5xx) sont réessayées 3 fois. Le flux « trending » n'envoie plus le
  jeton personnel, donc un jeton mort ne masque plus les nouvelles sorties.
  Le champ « nouveau jeton » refuse le **Secret du client API** et explique
  où récupérer le vrai `access_token`.
- **Windows — console sans VT** : FreeFlix active maintenant
  `ENABLE_VIRTUAL_TERMINAL_PROCESSING` avant le suivi souris ; sur une console
  classique qui refuse ce mode, il bascule proprement en navigation clavier.
- **Sélection de texte** : un rappel « Shift+drag → sélectionner du texte »
  est ajouté à l'aide (`?`). Maintenir Maj pendant le glissement utilise la
  sélection native du terminal ; elle revient à la sortie de l'écran.
- **Audit complet des sources et lecteurs** (12 sources, ~80 contrôles en
  direct) : 2 faux positifs éliminés, 2 lecteurs réparés.
- **xtremestream (Coflix « Vidéo HD et 1080p »)** : le manifeste `xs1.php`
  répond 403 sans la page lecteur comme Referer. Le Referer/Origin est
  maintenant conservé pour le manifeste ET les segments : le lecteur passe de
  « qualité affichée puis 404 » à **3688 s en 720p**.
- **LuluStream** : résolu à nouveau (3688 s, 720p ~1.4 Mbps).
- **Manifestes sans extension** (`/player/xs1.php?data=…`) : la durée est
  désormais lue et vérifiée, même sans `.m3u8` dans l'URL.
- **Playlists volumineuses** : la limite de sonde passe de 2 à 4 Mo pour les
  playlists HLS (One Piece ≈ 1100 segments), afin que la vérification de durée
  ne soit plus silencieusement ignorée.
- **uqload** : Referer/Origin transmis pour le flux, en plus du garde-fou de
  durée.
- **French-Stream** : les fiches gardent des lecteurs supprimés par le site
  (voe répond 404). Ils sont maintenant retirés de la liste (404/410) au lieu
  d'échouer à la lecture ; les autres erreurs réseau gardent la ligne.
- **Coflix** : `Vidéo HD et 1080p` (xtremestream) lit la durée (3688 s) au
  lieu d'afficher une qualité sans preuve ; `LuluStream` de nouveau résolu.
  `VidMoly`, `coflix.upn`, `minochinos` et `Netu` restent indisponibles côté
  hébergeur (marqués ✗, le lecteur suivant est proposé). `Veed` se résout mais
  n'expose ni variante ni durée.
- **Tests** : 493 tests au vert, ruff OK.

## 1.15.1

- **Téléchargements en lot (Anime-Sama / uqload)** : les épisodes après les
  deux premiers échouaient tous instantanément. Uqload coupe les connexions
  quand 8 fragments sont demandés en parallèle ; le lot réessayait à
  l'identique. Chaque épisode qui échoue est maintenant retenté **fragment par
  fragment** (1 à la fois), avec la progression visible dans sa ligne
  (`sequential retry`), puis vérifié avant publication.
- **Finalisation des fichiers** : le déplacement final gère désormais les cas
  où le dossier de téléchargement et le dossier temporaire sont sur deux
  disques différents (`Invalid cross-device link`).
- **Tests** : 464 tests au vert, ruff OK.

## 1.15.0

- **Contrôle complet à la souris** : menus et listes cliquables, curseur qui
  suit le survol, molette, clic droit pour revenir, pagination et barre de
  défilement cliquables, fil d'Ariane cliquable, boutons aide/filtre,
  multi-sélection (tout/confirmer/annuler), aperçu (ouvrir/retour), champs
  texte (OK/annuler), Oui/Non (mise à jour/installation), et annulation d'un
  téléchargement par clic sur la barre du bas ou double-clic. Le suivi SGR est
  coupé proprement à la sortie de chaque écran (`FREEFLIX_NO_MOUSE=1` pour le
  désactiver).
- **Fluidité et affichage** : les mouvements de souris sont coalescés sur la
  dernière position, les répaints sont immédiats, et les menus saison / langue
  / épisode / qualité / lecteur sont **inline** : l'affiche et les infos de la
  série ne sont plus masquées pendant la navigation.
- **Planning Anime-Sama** : cliquer un anime affiche sa grande affiche puis les
  actions, comme après une recherche ; « Suivre le dernier épisode sorti »
  ouvre directement le dernier épisode.
- **Uqload / téléchargements** : les flux de moins de 90 s (extrait/pub) sont
  rejetés ; le download passe maintenant par le **même proxy local** que le
  streaming, avec les vrais en-têtes, au lieu de laisser yt-dlp recevoir
  l'extrait. Le flux résolu par l'analyse de qualité est réutilisé pour la
  lecture, et le choix de qualité est respecté. Vérifié : Avatar épisode 1 en
  23 min 07 s (et non 30 s), et un flux multi-qualités téléchargé en
  **1280×720**, 23 min 44 s.
- **Épisodes et langues** : tri numérique, suppression des épisodes sans
  lecteur valide, lecture dynamique des langues FrenchStream (`vf`, `vostfr`,
  `vo`, `vff`, `vfq`…).
- **Tests** : 463 tests au vert en français et en anglais, ruff OK.

## 1.14.1

- **Planning Anime-Sama — statut en direct** : le statut « Sorti » ne dépend
  plus du HTML mis en cache. FreeFlix lit maintenant `planning/sorties.php`,
  exactement comme le site, à chaque ouverture du planning (aucun cache HTTP).
  Un épisode uploadé passe donc en « Sorti » même si la carte serveur est
  encore marquée « pas encore sorti » ou « retardé ».
- **Affiches** : le cache persistant des posters n'est plus vidé à la fermeture
  de FreeFlix ; seules les images temporaires de session sont supprimées. Les
  affiches restent instantanées d'un lancement à l'autre quand le planning
  n'a pas changé.
- **CI** : assertions d'interface indépendantes de la langue (français/anglais).
- **Tests** : 433 tests au vert, ruff OK.

## 1.14.0

- **Anime-Sama — planning hebdomadaire** : nouveau menu à l'entrée de la
  source. Le planning est récupéré en direct (cache 5 min), filtré sur les
  animes, regroupé par jour et par heure, avec affiche et statut « sorti ».
  Chaque entrée permet de suivre le dernier épisode sorti ou de parcourir les
  saisons.
- **Affiches persistantes** : les posters du planning sont mis en cache sur
  disque, préchargés en parallèle et rafraîchis automatiquement quand le site
  change l'illustration (ETag/Last-Modified), sans re-télécharger à chaque
  visite.
- **Mise à jour au lancement** : FreeFlix demande maintenant `y/n` (`o/n` en
  français), met à jour avec le **même installateur** (uv → uv, pipx → pipx,
  pip → pip), installe les nouvelles dépendances, puis recharge le nouveau
  code sur Entrée. Les outils système manquants sont installés après le
  redémarrage.
- **Téléchargements sans trous** : les fichiers sont téléchargés dans
  `.temp/`, puis validés avant publication (durée ffprobe vs playlist HLS,
  taille vs `Content-Length`, fichier lisible). yt-dlp abandonne si un
  fragment reste indisponible au lieu de produire une vidéo qui saute ; les
  fragments corrompus sont purgés avant un nouvel essai. Un fichier incomplet
  n'est jamais déplacé dans `Downloads`.
- **Streaming résilient** : le proxy annonce une longueur exacte et coupe la
  connexion si le corps est court (plus de segment tronqué accepté comme
  complet). Reprise par `Range` au byte près, nouvelle session/DNS après une
  coupure, retries tant que le lecteur est connecté, et re-résolution du
  manifest après expiration du token ou changement d'hôte/CDN (Wi-Fi,
  opérateur). Les `401/403/410` initiaux et `Retry-After` sont gérés.
- **GoldenMS / Cinemeta** : Cinemeta répond parfois par un timeout (curl 28).
  La recherche réessaie 3 fois (avec backoff, timeout de lecture 20 s) puis
  utilise la dernière réponse en cache au lieu d'afficher « aucun résultat »
  et de masquer toute la source.
- **mpv** : timeout réseau désactivé (`--network-timeout=0`) et options de
  reconnexion activées pour laisser le proxy reprendre pendant une longue
  coupure ; le cache disque existant est conservé.
- **Tests** : 429 tests au vert, ruff OK. Ajout de tests bout-en-bout réels
  (ffmpeg + yt-dlp + proxy) : segment coupé en plein transfert → vidéo
  complète de 6 s, segment 404 → aucun fichier publié, MP4 coupé → reprise
  `Range`, origine tronquée → erreur protocolaire au lieu d'un faux succès.

## 1.13.8

- **Audit complet des sources** : nouvelle commande
  `python tools/audit_providers.py` (miroir → recherche → contenu → lecteurs →
  résolution → qualité/débit). Dernier passage : **27/28 contrôles OK**.
- **Voe réparé** : le domaine `voe.sx` redirige vers un miroir tournant dont
  la configuration JSON est doublement obfusquée. Les flux Voe (French-Stream)
  sont à nouveau lus, avec leur qualité (`720p ~1.2 Mbps`).
- **GoldenMS** : les sources (Vidlink, Hexa, Xpass, Mapple, Videasy) sont
  interrogées **en parallèle** avec un délai borné — plus de menu réduit à un
  seul lecteur parce qu'une source lente bloquait les autres.
- **French-Stream** : les embeds identiques listés sous `default/vostfr/vff`
  ne font plus de doublons, et les embeds temporairement bannis (page ne
  contenant que le faux flux `/troll/`) sont retirés au lieu d'échouer à la
  lecture.
- **Papystreaming** : message explicite quand le miroir répond un défi
  Cloudflare (limite côté site).
- **Tests** : 362 tests au vert, ruff OK.

## 1.13.7

- **Vidzy / fsvid — téléchargement réparé** : le CDN rejette le fingerprint TLS
  de yt-dlp (HTTP 403) même avec les bons cookies. Le lecteur reproduit
  maintenant le « gate » navigateur (cookie `vz_ok`, paramètre `gk`), et les
  téléchargements Vidzy passent par le proxy local curl_cffi (même chemin que
  la lecture). Nightborn (2026) se télécharge désormais.
- **Analyse** : les flux Vidzy reçoivent aussi le cookie de gate, donc la
  résolution/débit reste lisible (`468p ~0.8 Mbps`).
- **Tests** : 356 tests au vert, ruff OK.

## 1.13.6

- **Nightborn / GoldenMS** : la qualité et le débit analysés passent en tête
  des libellés (plus de troncature sur les petites largeurs), et l'extraction
  Videasy est bornée à 8 s pour éviter un blocage de plusieurs minutes.
- **Téléchargements signés** : yt-dlp et aria2c reçoivent désormais tous les
  en-têtes utiles (Cookie CloudFront, X-Playback-Environment, Referer…), y
  compris lors d'une reprise. Les shims yt-dlp cassés sont détectés avant le
  téléchargement, avec une commande d'installation adaptée à Windows
  (`winget`), macOS (`brew`) ou Linux (`dnf`/`apt`).
- **Multi-systèmes** : Doctor vérifie que les binaires s'exécutent réellement
  (pas seulement qu'ils existent) ; CI Ubuntu/Windows, Python 3.9 et 3.12.
- **Tests** : 355 tests au vert, ruff OK.

## 1.13.5

- **Retour lecteur → épisodes** : le menu des lecteurs (ainsi que les menus
  qualité / lecteur vidéo) ne vide plus l'écran et ne laisse plus de ligne
  `❯ Choisis le lecteur : ← Retour`. Le nettoyage complet ne se fait qu'au
  retour aux résultats de recherche ; l'affiche reste en place, sans texte
  superposé.
- **Tests** : 351 tests au vert, ruff OK.

## 1.13.4

- **Analyse des lecteurs partout** : HiAnime (section anglaise) et
  GoldenMS/Papystreaming affichent désormais la résolution et le débit moyen
  de chaque stream, comme les autres sources.
- **Délais d'analyse augmentés** : budget total 40 s (60 s pour le
  téléchargement en lot) et 25 s par lecteur, pour laisser aux MP4 directs
  lents le temps de lire leur en-tête. Les analyses réussies restent en cache
  10 min, donc les passages suivants sont instantanés.
- **DASH** : les manifests `.mpd` (Vidlink) sont lus directement pour la
  résolution/bande passante, avec les en-têtes et cookies signés transmis à
  ffprobe.
- **Tests** : 350 tests au vert, ruff OK.

## 1.13.3

- **Navigation Anime-Sama** : dans une série, les retours langues ↔ épisodes
  ↔ saisons ne vident plus l'écran ; l'affiche et le contexte restent visibles
  jusqu'au retour aux résultats de recherche.
- **Affiches sixel sous Konsole** : le nettoyage d'écran supprime aussi le
  calque graphique sixel (bascule temporaire de l'écran alterné), au lieu de
  laisser l'ancienne affiche sous le menu suivant.
- **Tests** : 343 tests au vert, ruff OK.

## 1.13.2

- **Anime-Sama — fausses saisons sur les nouveautés** : les fiches récentes
  gardent la `Saison 1` active et commentent le reste du modèle
  (`Saison 2`…`Saison 10`, `Film`, `OAV`) dans un bloc `/* ... */`. Le parseur
  comptait ces lignes commentées et affichait **12 saisons** pour un anime qui
  n'en a qu'une (Dreamland, The Exiled…). Les commentaires JS sont désormais
  retirés avant l'extraction ; les saisons actives restent détectées.
- **Tests** : régression sur pages récentes et sur saisons multiples réelles ;
  339 tests au vert, ruff OK.

## 1.13.1

- **Vidlink réparé** : les MP4 directs de `bcdn.hakunaymatata.com` répondent
  désormais **HTTP 429** (limitation côté CDN). Le lecteur demande donc le
  flux **DASH signé** (`X-Playback-Environment: dash-hevc`) et transmet le
  cookie CloudFront à mpv pour le manifeste **et** les segments. La source
  apparaît comme « Vidlink - Multi (DASH) ». Le DASH nécessite mpv ; VLC et
  le navigateur affichent un message explicite et invitent à choisir mpv ou
  une autre source.
- **Routage proxy des fichiers directs** : une URL `.mp4` signée va sur
  `/video` (octets bruts + Range) au lieu de `/stream` (playlist vide), ce qui
  corrige le « Failed to open » de mpv. `/stream` détecte aussi le contenu
  lorsqu'une source directe n'a pas d'extension et bascule vers `/video` sans
  charger toute la vidéo en mémoire.
- **Tests** : couverture DASH (forme de l'API + en-têtes mpv) et intégration
  proxy des fichiers directs ; 337 tests au vert, ruff OK.

## 1.13.0

- **Performances** : `lxml` devient une dépendance par défaut (parsing HTML
  **14,7× plus rapide** — mesuré : 7,38 s → 0,50 s sur 20 pages) ; point
  d'entrée CLI allégé (`--version` en **59 ms**, import principal 0,80 s →
  0,28 s) ; splash raccourci (1,9 s → 0,86 s) ; **cache d'origine des miroirs
  24 h** (Anime-Sama : 8,3 s → 0,00 s au lancement suivant) ; timeouts courts
  (6 s connexion) ; **sondes de langues en parallèle** (saison Anime-Sama :
  ~10 s → 2,3 s, revisite **0,009 s** grâce au cache négatif) ; cache TTL sur
  les recherches et listes d'épisodes (HiAnime, Coflix, YTS, EZTV,
  French-Stream) ; 8 niveaux de sparkline.
- **Esthétique** : dégradé truecolor du wordmark au repos, **points d'état
  sémantiques** (○ hors ligne) pour la santé des sources, toast avec rail
  coloré, **thème clair auto** via `COLORFGBG`, **mode animations réduites**
  (réglage + `FREEFLIX_REDUCED_MOTION=1` : comète/reflet/barres figés).
- **Corrections** : sélecteur de match GoldenAnime **inatteignable** (code
  enfermé dans `_ani_lines`) ; nouvel layout Anime-Sama (`as-carte`) avec
  fallback ancien ; cache HTTP isolé dans les tests (conftest) ; retries des
  posters honorant `attempts` ; cache French-Stream correctement structuré ;
  **plus de flash terminal entre le splash et l'accueil** (l'écran alterné est
  passé directement au premier menu) ; reflet du logo restauré en boucle
  fluide (~0,66 s/pass) sur un splash de 0,86 s ; **Coflix** : pages
  contenu/agrégateur de lecteurs et grille d'accueil mises en cache (revisite
  contenu 0,06 s au lieu de ~3 s, derniers ajouts 0,08 s au lieu de 2,1 s).
- **Contenus nettoyés partout** : entités HTML décodées, espaces/espaces
  insécables/zero-width normalisés, titres dupliqués supprimés (menu + fiche),
  en-têtes « Film : » redondants retirés, pluriels corrects (« 1 saison »,
  « 3 saisons ») au lieu de « saison(s) ».
- **Lecteurs plus rapides** : cache des analyses qualité/débit (10 min, 2 min
  en échec), budget du menu d'analyse 26 s → 6 s, ffprobe borné au budget
  (plus d'attente de 20 s sur un MP4 bridé), sondes HLS parallèles — les
  qualités « 1080p ~1,9 · 720p ~1,0 Mbps » s'affichent en ~4 s puis
  instantanément en revisite.
- **Navigation cohérente (pile)** : un seul Échap = un seul niveau, avec état
  conservé — Résultats ← Recherche, Saisons ← Résultats, Épisodes ← Saisons,
  Lecteurs ← Épisodes. Appliqué à Anime-Sama, HiAnime, GoldenAnime,
  French-Anime, French-Stream, Coflix, YTS/EZTV et Nyaa ; les résultats ne
  sont plus re-fetchés au retour, la recherche est pré-remplie. Corrige aussi
  un crash GoldenAnime en recherche par ID AniList et l'affichage littéral
  « None » après une fiche. Test de navigation automatisé ajouté.
- **Écran propre** : chaque retour (Back / Cancel / Exit), chaque entrée
  dans un provider **et chaque nouvelle recherche** vident l'écran — les
  anciens menus, posters et confirmations ne s'empilent plus dans le
  scrollback ; le niveau affiché est toujours le seul visible. YTS/EZTV
  gagnent aussi la boucle recherche (retour résultats → recherche).
- **Échap dans la recherche = retour** (corrigé) : il renvoyait la requête
  pré-remplie et relançait la recherche (effet « Échap → résultats »).
  Désormais Échap annule, Entrée sur champ vide accepte le défaut.
- **Posters d'aperçu fluides (corrigé)** : quand chafa mettait du temps, le
  poster ne s'affichait qu'après une touche de navigation. La boucle ne
  repeignait pas la transition « moulinette → image » quand le rendu
  terminait entre deux ticks ; elle est désormais détectée et affichée sans
  touche (aperçus en blocs **et** sixel).
- **GoldenMS : Échap ne lance plus les derniers ajouts** — un champ vide
  signifie « latest », donc Échap ouvrait cette vue au lieu de revenir. Il
  retourne maintenant au menu précédent (valeur d'annulation distincte).
- **Navigation (suite)** : GoldenMS entre dans la pile (type ← mode ← recherche
  ← résultats ← saisons ← épisodes ← lecteur) ; Papystreaming gagne la boucle
  de recherche (retour résultats → recherche) et le sélecteur saison/épisode
  remonte d'un niveau (idem EZTV) ; « Continue from AniList » (saison, langue,
  épisode), les reprises Anime-Sama / French-Stream et le sous-menu saison des
  sous-titres GoldenAnime ont un vrai Back ; le menu qualité HLS propose
  « ← Back » au lieu de lancer la lecture sur Échap.
- **Accueil vivant** : l'entrée « Nouveautés » est présente dès qu'une série
  Anime-Sama est suivie (ouverture = attente bornée du fetch de fond, plus
  jamais invisible pendant la visite) ; les menus reçoivent `get_renderable`
  (curseur qui respire, toasts et barre d'état mis à jour au repos) ; l'aperçu
  poster Windows profite du même correctif que Linux.
- **Robustesse** : les pages de challenge/vides ne sont plus écrites dans le
  cache TTL (French-Stream, Coflix, HiAnime, Anime-Sama) — plus de « aucun
  résultat » pendant plusieurs minutes après un blocage passager ; l'historique
  tolère une entrée corrompue ; la reprise Coflix retrouve le bon épisode même
  si le titre finit par « VF »/« VOSTFR ».
- **Confort** : détection Back multilingue (Retour/Annuler/Quitter) sans faux
  positif sur un titre comme « Back to the Future » ; YTS ne force plus Entrée
  après chaque film.

## 1.12.7

- **Correctif Python 3.9** : `str | None` évalué à l'import cassait toutes
  les installations en 3.9 (CI ubuntu+windows) — remplacé par `Optional`.
  Balayage complet : aucune autre syntaxe 3.10+ évaluée au runtime.
- Correctifs CI : import `Group` manquant sur le dashboard vide (nouveaux
  utilisateurs), test du repli étroit insensible à la console Windows
  legacy (coins carrés).

## 1.12.6

- **Xpass réparé (GoldenMS)** : nouveau protocole reversé (endpoint
  `/data/…` chiffré AES-256-GCM, clé SHA256) — 20 à 30 sources par film,
  vérifiées jouables. Mapple bascule sur le bootstrap `request-token`.
- **Interface vivante** : reflet en boucle sur le logo du splash (lettres
  seules), comète à traîne dégradée autour du panneau d'accueil (titre et
  sous-titre en couleur du thème, espacements symétriques), curseur qui
  respire, horloge HH:MM, barres à reflet défilant, skeletons shimmer sur
  les 13 chargements de listes, tip en machine à écrire, pop de streak,
  toasts de fin de download + cloche, titre d'onglet live (▶ + EQ) pendant
  la lecture mpv.
- **Dood** : miroir `d000d.com` reconnu.

## 1.12.5

- **Anime anglais (VO sous-titrée)** : HiAnime ajouté en 1er (recommandé), puis
  GoldenAnime et Anime-Sama sans badge. Chaîne vérifiée en direct
  (recherche → épisodes → serveurs → embed `window.__P` → m3u8 + sous-titres).
- **Films/séries anglais** : YTS (catalogue films à jour, données OV) et EZTV
  (derniers épisodes de séries) — Stream + Télécharger + Télécharger+Voir,
  choix de qualité, reprise/historique.
- **Nyaa modernisé** : scopes/catégories iconifiés et traduits, uploads de
  confiance, seeders minimum, pagination, taille/qualité/id, badge, `latest()`,
  historique ↑/↓, sélection multiple, téléchargement via barre + reprise.
- **« Derniers ajouts » à l'entrée de chaque provider concerné**
  (HiAnime, GoldenMS, GoldenAnime, Nyaa, YTS, EZTV) : trending AniList réparé
  (la liste ne s'affichait pas), garde anti-vide. Coflix garde la recherche
  directe.
- **Icônes** : table emoji↔Nerd complétée (`new`, `list`, `bulb`, `lock`,
  `verified`, `arrow_down`, `books`, `package`) ; plus d'emojis en dur dans les
  menus Nyaa/YTS/progression.
- **i18n** : nouvelles chaînes FR, test-garde `test_i18n_complete` vert.

## 1.12

- **Tous les providers vérifiés et réparés** : Coflix (nouveau layout
  `cfServers`, 0→7 lecteurs + comptes d'épisodes), sendvid (vrai flux
  `<source>`, placeholder 5 s rejeté), vidlink (qualités 360→1080p + subs),
  sibnet (Referer), nyaa (tailles), nouvelles clés `voe`/`lulustream`/`d0000d`,
  `waaw.to` filtré (JS requis).
- **Bilingue complet** : 669 clés FR, test-garde anti-régression qui échoue
  sur toute chaîne UI non traduite.
- **Fini les retours fantômes** : collage entre crochets (les collages
  molette ne naviguent plus), chafa ne lit plus le tty et n'interroge plus
  le terminal (`--probe off`), réponses du terminal avalées dans tous les
  lecteurs de touches, drain allongé à 200 ms. Retour en un seul Échap,
  Échap à l'accueil = quitter.
- **Posters Windows** : plus de sixel aveugle, repli blocs + section POSTERS
  dans `--doctor`.
- **Visuel** : match surligné, position/scrollbar, vus estompés, pastilles
  clavier couleur thème, sparkline 7j, tip du jour, durées, download stylé,
  aide 2 colonnes, compteurs, échelle couleur résolutions, splash +1 s.
- **Qualité sendvid affichée** (ffprobe 20 s, budget 26 s), doublons dédupliqués.

## 1.11.7

- **Sendvid réparé (Anime-Sama)** : l'extracteur renvoyait le meta `og:video`
  (une page HTML → « Failed to recognize file format », 0 Mo). Il lit
  désormais le vrai fichier signé `<source src>` (`videosN.sendvid.com`).
- **Qualité sendvid affichée** : le repli ffprobe (12 s) tuait les MP4
  throttlés (~15 s) → timeout 20 s + budget d'analyse 14 → 26 s, le menu
  montre `720p ~1.4 Mbps`.
- **Doublons dédupliqués** dans le menu des lecteurs (ex. ansembed ×2).
- **Posters Windows réparés** : `WT_SESSION` ne prouve pas que le Sixel
  expérimental est actif → plus de sixel aveugle (panneau vide) ; repli
  blocs + hint d'activation, section POSTERS dans `--doctor`.

## 1.11.4

Parité Windows = Linux.

- Recherche avec historique sur tous OS (prompt réécrit sans termios),
  annulation Esc-Esc des downloads sur Windows, installeur Windows
  complet (mpv, VLC, ffmpeg, aria2, chafa), notifications quotidiennes
  Windows (toast natif + tâche planifiée).
- Bannière de mise à jour d’origine restaurée.

## 1.11.3

Les liens/fonctionnalités arrivent enfin sur Windows.

- Cause racine : le fichier des portails était cherché en comptant
  `.. × 5` depuis `__file__` — juste sur Linux, faux d’un niveau sur
  Windows (`Lib/site-packages`) → fichier bundled jamais trouvé →
  repli sur URLs en dur périmées. Candidats désormais ancrés sur
  `sys.prefix`/`sysconfig` (juste partout), avec le chemin gagnant
  exposé dans `--doctor`.
- Timeout du remote 2s → 8s, `selectors.jsonc` livré dans le wheel,
  échecs de recherche French-Stream loggés avec la cause, `--doctor`
  affiche portails effectifs + URL par recherche.

## 1.11.2

Diagnostic des installs mixtes (version affichée neuve, code exécuté vieux).

- Nouveau module `install_health` : garde au démarrage qui compare la
  version embarquée au metadata et affiche la procédure de nettoyage si
  divergent, section INSTALL dans `freeflix --doctor` (mode, chemin du
  module, code vs metadata, launchers sur PATH).
- Bannière d’upgrade adaptée au mode : le `.exe` PyInstaller redirige
  vers les GitHub Releases au lieu de `uv tool upgrade`.
- Runbook d’upgrade Windows dans le README.

## 1.11.1

Sécurité + robustesse + nettoyage.

- **Sécurité** : jail `/player/subtitle` (allowlist tempdir/Downloads,
  cap 2 Mo, plus de CORS ouvert), garde SSRF durcie (schémas http/https
  seuls, formes IP obscures, verdict DNS + re-check des redirects),
  sockets mpv IPC en dir privé `0700` + cleanup (plus de fuite fd),
  pins sha256 pour configs/lua/shaders + extraction zip filtrée.
- **Players/scrapers** : guards `IndexError/KeyError` partout, matching
  hostname anti-faux-positifs, timeouts par défaut, qualités 2160/480/360
  honorées, `.temp` namespacé par subfolder, batch compté par label.
- **Nettoyage** : ~350 lignes mortes supprimées (extracteurs/cache/alias
  inutilisés, helpers orphelins, commentaires morts).

## 1.11

Réparation des lecteurs **Anime-Sama**, **French-Stream** et **French-Anime**.

- **Anime-Sama / ansembed** : la page embarque désormais un payload packé
  qui faisait jeter le bloc JWPlayer en clair par `packer.unpack()` →
  « Impossible de résoudre l'URL du flux ». L'extracteur retombe sur le
  HTML brut quand le code déobfusqué ne donne rien (vérifié : Mushoku
  Tensei, Bleach TYBW, Re:Zero, One Piece Egghead, Elusive Samurai…).
  Les saisons annoncées mais vides (`episodes.js` vide) sont sautées au
  lieu de crasher (« No episodes found. »).
- **French-Stream** : nouveaux extracteurs **dood** (`pass_md5`), **voe**
  (packer à substitution) et **kokoflix** (résolution de la redirection
  vers le vrai miroir playmogo/luluvdo). Les hôtes morts sont filtrés des
  menus : trakx.lol, multiup/netu, filemoon « Byse » SPA, `chamber_go`.
  Vérifié sur 20 films du moment — chacun a ≥3 lecteurs qui jouent
  (premium 20/20, vidzy 20/20).
- **French-Anime / luluvid** : le host tourne entre `luluvdo.com`,
  `luluvid.com` et `lulust.com` ; ce dernier n'était pas supporté donc
  invisible (ex. Kaiju No.8, Bleach). Ajouté comme miroir voe — vérifié
  sur 10 anime (720p).

## 1.10.10

Anime-Sama : les lecteurs des **derniers épisodes** rejouent (One Piece,
Mushoku Tensei, Youjo Senki…).

- **ansembed pris en charge** — c'était **le** lecteur qui marche pour les
  épisodes récents, mais il était marqué « non supporté ». Il sert un vrai HLS
  `vmget.online` (famille fsvid) ; on l'extrait maintenant et on envoie les
  headers `Origin` + `Referer` du player (comme le navigateur) → il joue.
- **uqload réparé** : Referer **dynamique** (le domaine tourne : `.is` → `.vc`)
  au lieu d'un domaine codé en dur, + `Origin` — il est passé à un HLS signé de
  la même famille fsvid.
- **embed4me** : décode le nouveau format multi-CDN (le stream a migré de
  `source` vers `hlsVideoTiktok` + `streamingConfig`). Note : quand embed4me
  route via le CDN **TikTok/Akamai** (anti-bot), il reste bloqué — mais
  **ansembed couvre** ces animes.
- Headers `Origin` + `Sec-Fetch-*` transmis par le proxy quand le CDN les exige
  (protection anti-hotlink).

## 1.10.9

- **Correctif Python 3.9** : `terminal_image.py` utilisait une annotation
  `str | None` évaluée à l'import → `TypeError` au lancement sur Python 3.9
  (1.10.8 crashait donc à l'import pour ces utilisateurs). Ajout de
  `from __future__ import annotations`. Aucun changement de comportement.

## 1.10.8

Posters **nets** (vrais pixels) au lieu des blocs Unicode flous — partout,
**y compris l'aperçu live dans la liste de recherche** — et en **haute
résolution** pour toutes les sources.

- Les posters s'affichent maintenant via le **meilleur protocole graphique**
  que le terminal supporte réellement : **kitty** (Kitty/Ghostty/WezTerm),
  **iTerm2** (macOS), ou **sixel** (Konsole, foot, Windows Terminal, xterm…),
  avec repli automatique sur les **blocs Unicode** partout ailleurs (SSH, cmd…).
  chafa reste l'encodeur — on quitte juste son *mode blocs*.
- **Détection fiable du sixel par interrogation du terminal (DA1)** : on ne
  force le sixel **que** s'il est réellement **activé** — sinon on afficherait
  du charabia d'échappement (Konsole livre le sixel *désactivé* par défaut).
- **Paramètres → Show Posters** affiche le protocole détecté et, sur
  Windows Terminal, **explique comment activer le sixel**. Nouvelle option
  « blocks » pour forcer les blocs.
- **Aperçu LIVE net dans la liste de recherche** : le poster de droite est
  désormais peint en **vrai sixel** (chafa écrit directement dans le terminal,
  positionné → résolution native, comme le poster plein écran), au lieu des
  blocs Unicode. Actif **par défaut** dès que le terminal a le sixel (Konsole,
  foot, Windows Terminal…). Détection Konsole par version (Konsole n'annonce
  pas le sixel en DA1, donc on se fie à `KONSOLE_VERSION` ≥ 22.12).
- **Sources en haute résolution** (fini les visages pixelisés) : les covers
  basse-déf sont récupérées en pleine résolution avant rendu —
  **TMDB** `w400 → original` (Coflix, French-Stream, Papystreaming,
  French-Manga), **IMDB/Amazon** `SX250 → SX1000` (GoldenMS via Cinemeta), et
  **AniList** demande `extraLarge` (GoldenAnime). Ces CDN rapides sont
  téléchargés en direct (sans redimensionnement wsrv qui coûtait le détail).

## 1.10.7

Réparation des lecteurs **premium** de French-Stream (fsvid.lol / vidzy).

- fsvid/vidzy a changé son obfuscation : le vrai `master.m3u8` est maintenant
  construit avec une **clé XOR positionnelle** `(0x3d + i*89 + H)` — où `H` est
  un hash du **hostname** de l'embed — appliquée au base64 **inversé**. L'ancien
  décodeur (clé fixe de 8 octets) ne matchait plus → les lecteurs *premium* et
  *vidzy* renvoyaient `None` et apparaissaient **cassés**.
- Le décodeur reproduit désormais exactement le nouvel algorithme (constantes
  lues dans le JS pour résister à un simple ajustement), avec repli sur l'ancien.
  → **premium** et **vidzy** rejouent, **et se téléchargent** (le download passe
  par le même résolveur, donc il récupère le vrai lien).
- **Historique de recherche sur TOUS les providers** : Coflix, French-Manga,
  GoldenAnime et GoldenMS mémorisent désormais les recherches et proposent le
  rappel ↑/↓ (« Recherches récentes »), comme Anime-Sama / French-Stream /
  Papystreaming l'avaient déjà — parité enfin complète.

## 1.10.6

Streaming plus rapide et plus fluide (comportement autoflix retrouvé).

- **Cache qui se remplit seconde par seconde** : les segments HLS sont de
  nouveau **streamés au fil des octets** au lieu d'être bufferisés en entier
  avant envoi — mpv reçoit un flux continu, le cache monte en douceur et la
  lecture démarre bien plus vite (fini les paliers de ~7 s = la durée d'un
  segment).
- **Robustesse conservée** : le flux passe toujours par `resilient_body`, qui
  **reprend en HTTP Range** sur une coupure et **re-résout un jeton expiré** —
  donc une très mauvaise connexion récupère et termine le segment, sans figer.

## 1.10.5

Passe design + robustesse/sécurité.

### 🎨 Design
- **Barres de progression fluides** : résolution 8× (glyphes de remplissage
  partiel) — fini l'effet « marches d'escalier ».
- **Curseur de menu modernisé** : barre d'accent + chevron `❯` au lieu du
  bloc inversé plein largeur ; lignes non sélectionnées lisibles aussi sur
  **terminal clair** (plus de blanc en dur).
- **« Continue watching » aligné** : titre · saison·épisode · barre en colonnes
  nettes (table sans bordure).
- **Fil d'Ariane raffiné** : chevrons en accent, dernier niveau en gras +
  tagline en sous-titre du panneau d'accueil.
- **4 nouveaux thèmes** : Everforest, Kanagawa, Solarized, et **Catppuccin
  Latte** (thème *clair* — corrige le header invisible sur fond clair).
- **Badges de statut** en pastilles colorées cohérentes ; état « aucun
  résultat » plus soigné.

### 🛡️ Robustesse & sécurité
- **Intégrité des binaires téléchargés** : mpv / ffmpeg / aria2 sont désormais
  vérifiés (**sha256** pour les versions figées, **plancher de taille** pour
  toutes) — un binaire corrompu ou altéré (MITM) est refusé avant installation.
- **Prefetch du stream** : pendant que le menu de sélection du lecteur est
  affiché, le flux probable est résolu en tâche de fond → lecture quasi
  instantanée.
- **Cache disque des segments (LRU, 200 Mo)** : un segment redemandé (retour
  arrière, ou nouvelle tentative après un 502) est servi sans re-téléchargement.

### 🧹 Hygiène & perf
- **Éviction du cache HTTP** : purge en tâche de fond des entrées périmées +
  plafond de taille (50 Mo) — le cache ne gonfle plus indéfiniment.
- **Session réseau partagée** réutilisée pour la résolution/probe (économise
  DNS + TLS).
- **Backoff exponentiel + jitter** sur les requêtes scrapers (meilleure
  récupération sur connexion instable).
- **Couverture de tests en CI** (cliquet anti-régression) + nouveaux tests.

## 1.10.2

Deux corrections sur les connexions instables.

### 🎬 Plus de désync audio/vidéo en lecture
- Quand la connexion sautait, un segment HLS pouvait arriver **tronqué** : mpv
  le lisait quand même et l'audio finissait décalé de la vidéo (impossible de
  suivre la suite). Désormais le proxy **bufferise chaque segment en entier**
  (reprise en Range + re-résolution du jeton si l'URL expire) et ne le sert
  **que complet** — sinon il renvoie 502 et le lecteur le redemande. Plus de
  segment à moitié → plus de décalage son/image.

### ⬇️ Plus de téléchargements « à trous » dans le dossier principal
- Sur connexion qui dérange, yt-dlp **sautait** les fragments manquants et
  produisait une vidéo incomplète qui sautait des passages — et elle atterrissait
  quand même dans Downloads. Maintenant chaque fragment est **réessayé fort**
  (`--fragment-retries 50`) et, si un fragment reste introuvable, le
  téléchargement **s'arrête** (`--abort-on-unavailable-fragments`) : le partiel
  reste dans `.temp/` (reprenable) et **rien d'incomplet n'est déposé** dans le
  dossier principal.

## 1.10.1

- **Cache disque « buffer loin devant »** : au lieu de ~2 min de cache en RAM,
  le lecteur peut mettre le flux en cache **sur disque très en avance**
  (jusqu'à ~30 min de marge) — réglable dans les paramètres. Une coupure réseau
  de plusieurs minutes ne casse plus la lecture.
- **Fin du spam de traceback** `ConnectionResetError` / `BrokenPipeError` :
  quand mpv ferme une connexion de segment, le proxy l'ignore silencieusement.

## 1.10.0

Grosse passe technique — plus rapide, plus robuste, plus léger, et testé.

### ⚡ Performance
- **Démarrage ~4× plus rapide** (~790 → ~180 ms) : la pile Crypto (AES) n'est
  plus importée au lancement mais seulement à la résolution.
- **Parsing HTML ~3× plus rapide** via **lxml** quand il est présent (`pip
  install freeflix-cli[speed]`), avec repli automatique sur html5lib — donc
  aucun risque pour l'install Termux/Android.

### 🛡️ Robustesse
- **Plus aucune requête ne peut se bloquer** : timeout de connexion (15 s) sur
  toutes les sessions réseau — un hôte mort ne fige plus jamais l'appli.
- **Filet de sécurité en CI** : `freeflix --doctor --sources` teste chaque
  source en direct (up / down / Cloudflare / cassée), et des tests de parsing
  figés (Coflix) attrapent une future migration de site **avant** le release.

### 🧱 Dette / léger
- **Flask retiré** : le proxy tourne désormais sur `http.server` de la stdlib
  (**−2 dépendances** : flask + werkzeug). Tout le comportement est préservé
  (réécriture m3u8, streaming résilient, Range, garde SSRF, lecteur web) et
  **vérifié par un test d'intégration de bout en bout**.
- **Binaire autonome** (PyInstaller) : un exécutable **sans Python** est
  construit pour Linux / Windows / macOS à chaque release et attaché à la page
  de release. `python -m freeflix_cli` fonctionne aussi.

### 🩺 Diagnostic
- **Journal `freeflix.log`** (rotatif) + **`freeflix --verbose`** : les erreurs
  (source, proxy, exceptions) sont tracées → fini de deviner quand ça coince.

## 1.9.13

### 📡 Streaming increvable (connexion instable + URL expirée)
- Le proxy récupère maintenant tout seul quand la connexion fait n'importe quoi.
  Le corps de réponse (HLS `/ts` **et** MP4 `/video`) **reconnecte via HTTP
  Range exactement où il s'était arrêté** dès que le lien stalle/coupe → mpv
  reçoit toujours des **segments complets** (fini le spam « Error decoding
  audio »). Il ne lâche qu'après **5 min sans le moindre octet** (le budget se
  réarme à chaque octet) → dès que la connexion repasse, ça charge.
- **URL / token expiré (403/410)** : le proxy **re-résout le flux** (token
  frais) et **ré-signe** l'URL qui a échoué → la lecture repart au lieu de
  mourir sur un lien périmé.
- **mpv** reçoit un **gros cache** (`--cache-secs=120`, readahead 120 s,
  network-timeout 120 s) pour jouer en avance et absorber les pauses pendant que
  le proxy reconnecte. libcurl détecte un transfert mort en 20 s (au lieu de 60).
- Prouvé par tests : coupure en plein transfert → fichier livré complet et
  identique ; segment 403 → récupéré via re-résolution.

## 1.9.12

### 🐛 « FreeFlix se ferme tout seul dès l'ouverture » — corrigé
- Au lancement, le terminal émet des séquences (réponses à ses requêtes d'init,
  événements focus) qui restaient dans le tampon d'entrée et étaient lues par le
  menu comme un **Échap** → l'accueil quittait aussitôt. Deux couches de
  correctif : (1) on **vide le tampon d'entrée** (`termios.tcflush`) au démarrage
  et avant le menu ; (2) à l'accueil, **Échap ne quitte plus** l'appli — on sort
  par l'entrée **« Exit »** (ou Ctrl-C). Dans les sous-menus, Échap = retour,
  comme avant.

### 🎨 Ajustements accueil
- **Splash de lancement retiré** (redondant + il déclenchait le bug ci-dessus).
- **Poster d'accueil retiré** (rendu bloc peu net à petite taille).
- Les **barres de progression %** de « Reprendre » s'affichent pour les épisodes
  regardés **à partir de cette version** (la durée est maintenant mémorisée) ;
  les anciens restent en `▸ Xm` jusqu'à leur prochaine lecture.

## 1.9.11

### 🎨 Esthétique
- **Logo de lancement** : un wordmark ASCII « FREEFLIX » coloré au thème
  s'affiche au démarrage (ignoré hors terminal / fenêtre trop étroite).
- **Accueil enrichi** : vraies **barres de progression** pour « Reprendre »
  (la durée de l'épisode est désormais mémorisée avec la position), et le
  **poster** du dernier titre regardé s'affiche à gauche quand il est déjà en
  cache (préchargé en arrière-plan → l'accueil reste instantané).
- **Panneaux** : bordures **arrondies** explicites + espacement cohérent
  (accueil + en-têtes) pour un rendu plus doux et uniforme.

## 1.9.10

### ⚙️ Réglages
- **Retirer le compte AniList** : le réglage du jeton AniList propose maintenant
  **Modifier** ou **Retirer**. Retirer le jeton **masque aussi le « Reprendre
  depuis AniList »** sur l'écran d'accueil.
- **Icônes uniquement sur les grands titres** de la page Réglages
  (Lecture / Téléchargements / Apparence / Comptes / À propos) — les
  sous-réglages n'ont plus d'icône, la liste est plus propre.

## 1.9.9

### ▶️ French-Stream : le lecteur « premium » (fsvid/vidzy) marche enfin
- Le site sert un flux **leurre** aux scrapers mais calcule le **vrai** flux à
  l'exécution du JS (payload base64 + XOR avec une clé). FreeFlix **reproduit ce
  déchiffrement** → il récupère maintenant **le vrai master.m3u8** multi-qualité
  / multi-langue (le même que le site), pour **fsvid.lol ET vidzy.org**.
- L'**analyse de résolution** fonctionne sur ces flux (variantes lues, non
  bloquées). Le filtre anti-leurre de 1.9.8 reste en secours si le déchiffrement
  échoue un jour.

## 1.9.8

### 🎭 French-Stream : fini la fausse vidéo « troll »
- Quand tu cliquais sur un film French-Stream, ça jouait parfois une **vidéo
  leurre** (`s1.fsvid.lol/troll/…`) au lieu du vrai contenu — c'est un piège
  anti-scraper que l'hébergeur maison (fsvid.lol) sert aux bots. FreeFlix
  **rejette maintenant ces flux leurre** (`/troll/`, `/fake/`, `/decoy/`…), donc
  ces lecteurs sont marqués indisponibles et la lecture bascule sur un
  hébergeur qui renvoie **le vrai stream** (uqload, etc.).

## 1.9.7

### 🖼️ Coflix : les pochettes reviennent + aperçu plus net
- Depuis la migration WordPress, l'API de recherche ne renvoyait **pas de
  pochette** → l'aperçu et la vignette après sélection étaient vides. Corrigé :
  - la recherche lit désormais la **grille de résultats du site** (`/?s=`) où
    chaque carte porte la **pochette** (image) **et** le titre (alt) ;
  - la page détail extrait la **pochette TMDB** (`/w500/`, y compris les URL
    `//image.tmdb.org` sans schéma que l'ancien filtre ratait).
- **Aperçu chafa plus net** : on passe `--work 9` (facteur de qualité max de
  chafa) aux deux rendus, en plus du truecolor. NB : l'aperçu reste en mode
  **symboles** (il est intégré dans l'interface texte) — il ne peut pas être en
  vraie image comme le plein écran, mais il est maintenant au maximum de netteté.

## 1.9.6

### 🎬 Coflix réparé (le site est passé sous WordPress)
- Coflix ne renvoyait **plus rien** : l'ancienne recherche `/suggest.php` renvoie
  désormais une erreur 500 et la mise en page des séries a changé. Corrigé :
  - **recherche** via l'API WordPress `/wp-json/wp/v2/search` ;
  - **séries/saisons/épisodes** relus depuis le nouveau thème (onglets de saison
    + panneaux d'épisodes) — tous les épisodes sont dans la page ;
  - `get_website_url` passe par le chemin résilient (retries + DoH) → un flake
    DNS sur le miroir ne casse plus la source.
  - Vérifié en direct : recherche OK, 8 saisons, **13 lecteurs** par épisode,
    9 lecteurs par film.

### 🖼️ Posters chafa plus nets selon les machines
- Sur certaines distros / sessions SSH, `COLORTERM` n'est pas transmis → chafa
  sous-estime les couleurs (256/16) → posters **flous / en bandes**. Quand le
  terminal déclare **truecolor**, on force maintenant `--colors full` (uniquement
  vers le haut, jamais vers le bas) → posters nets.

## 1.9.5

### 📱 Android : téléchargements + lecture des fichiers locaux
- Le **setup Android installe désormais `yt-dlp`** (en plus de ffmpeg/aria2/chafa).
  Sans lui, les téléchargements HLS échouaient (aria2c ne gère que les .mp4
  directs). *(Merci au retour terrain — Termux natif, Huawei.)*
- La **lecture d'un fichier déjà téléchargé** (gestionnaire de téléchargements)
  passe maintenant par **mpv-android** via un intent `file://` — au lieu de
  chercher un binaire mpv/vlc local qui n'existe pas sur Android.

## 1.9.4

### 📱 Lecture Android : « rien ne s'ouvrait » — corrigé + honnête
- Le lanceur Android renvoyait un **faux succès** (« Lecture dans Android… »)
  alors que rien ne se lançait. Il **vérifie maintenant réellement** que
  l'intent a été accepté, et essaie dans l'ordre **mpv-android → VLC →
  `termux-open` → sélecteur générique**.
- **Détection proot** : sous proot, le `am` d'Android **ne peut pas** lancer
  d'apps (limitation kernel/`app_process`, confirmée). FreeFlix l'explique
  désormais **clairement** — au lancement ET dès le setup — avec la marche à
  suivre : **lancer FreeFlix dans Termux** (`pip install curl_cffi --pre`,
  wheels Android beta) ou **Termux:X11 + mpv**.
- En cas d'échec, un **diagnostic** (`env=…  am=…  termux-open=…` + sortie de
  la commande) s'affiche pour comprendre pourquoi.

## 1.9.3

### 🛡️ Plus de crash quand une source est injoignable
- Une erreur réseau sur une source (**connexion resetée**, DNS/TLS, timeout)
  remontait **non-attrapée et fermait toute l'appli**. Désormais elle affiche un
  **panneau propre « source injoignable »** et revient à la liste des sources —
  quelle que soit la source. En plus, `get_website_url` (Anime-Sama) passe par
  le chemin résilient (retries + repli requête simple + **DoH**), donc un
  premier appel qui foire ne casse plus tout.

### 📱 Mode Android (Termux / proot)
- Nouveau `platform_android` : détecte **Termux / proot Android** et **délègue
  la lecture** à un lecteur Android externe (**mpv-android**, puis VLC) via un
  intent `am start` qui lit le proxy local `127.0.0.1` (loopback partagé →
  injection des headers + réécriture m3u8 conservées). Pas besoin d'écran.
- Nouveau lecteur **« android »** (proposé/défaut sur Android ; une préférence
  mpv/vlc desktop est redirigée automatiquement). Téléchargements vers
  `/sdcard/Download/FreeFlix`.
- **Setup de premier lancement Android** dédié : installe ffmpeg/aria2/chafa via
  `pkg`/`apt`, guide l'install de **mpv-android** + `termux-setup-storage` — au
  lieu du parcours desktop (mpv.conf/Anime4K/PRIME). Plus de téléchargement de
  binaires x86_64 sur Android.

## 1.9.2

Suite de l'audit d'optimisation — 4 chantiers, testés Linux + Windows (CI verte
sur py3.9/3.12).

### ⚡ Cache HTTP persistant (A3)
- Nouveau module `httpcache` : les lectures de catalogue (recherche, série,
  saison sur Anime-Sama — clé stable malgré le `?filever=` aléatoire) et les
  **métadonnées Cinemeta films/séries** sont mises en cache sur disque (TTL).
  La 2ᵉ recherche passe de ~1,8 s à **~30 ms**. Réglage **« Vider le cache HTTP »**.

### 🖼️ Posters fiables + Kitty/iTerm2 (B2)
- **Windows** : les pochettes ne s'affichaient **pas pendant la recherche**
  (seulement après sélection) — la sortie de chafa était décodée en cp1252 et
  levait une `UnicodeDecodeError`. Forcé en **UTF-8** → corrigé.
- **Linux & Windows** : posters **lents / parfois absents** — un échec de rendu
  n'est plus mis en cache à vie (retry après cooldown), téléchargement ramené à
  **1×8 s** (au lieu de jusqu'à 4×12 s), et 2→4 workers de rendu (chafa est un
  sous-processus, le GIL est libre).
- **Qualité photo** : détection Kitty / Ghostty / WezTerm / iTerm2 → chafa reçoit
  un vrai protocole graphique (avec garde de version), sinon autodétection.

### 🛡️ Résilience des extracteurs (#5)
- Nouveau `scraping/resilient.py` : les sélecteurs CSS fragiles vivent dans une
  table **hot-patchable** via un `data/selectors.jsonc` distant (récupéré en
  arrière-plan comme les portails), donc **une source cassée se répare sans
  release**. Extraction **multi-stratégies** (plusieurs sélecteurs essayés dans
  l'ordre). Anime-Sama recherche + série migrées dessus, valeurs actuelles en
  défaut (zéro régression tant qu'aucun patch n'est poussé).

### ▶️ mpv IPC — reprise temps réel + épisode suivant auto (binge)
- Nouveau `mpv_ipc.py` : dialogue avec mpv via `--input-ipc-server` (socket Unix
  / named pipe Windows). La position est enregistrée **en direct** (survit à un
  crash — le hook lua n'écrivait qu'à la sortie propre), et on connaît la raison
  d'arrêt (**fin de fichier vs quitté**).
- **Binge (Anime-Sama)** : quand un épisode se termine, le suivant se lance
  **automatiquement** après un compte à rebours annulable ; si tu as quitté en
  cours, il demande simplement. 100% additif : le résumé lua reste le repli.

## 1.9.0

Optimisation & robustesse — issue d'un audit complet de l'application, testé
sur Linux **et** Windows (nouvelle CI qui lint + teste sur les deux).

### ⚡ Démarrage plus rapide
- Le **proxy M3U8 (Flask) n'est plus importé ni démarré au lancement** : il est
  initialisé **paresseusement à la première lecture** (`proxy.ensure_started()`).
  Importer FreeFlix ne tire plus Flask/werkzeug (~100 ms + un port ouvert en
  moins au démarrage). Les options DNS partagées vivent désormais dans un module
  léger (`net_config`) pour que charger un scraper n'entraîne plus le proxy.
- Les badges d'épisodes (« déjà téléchargé ») **listent chaque dossier une seule
  fois** (cache 5 s) au lieu de faire ~6 appels `os.path.isfile` par ligne — une
  liste de 1000+ épisodes ne martèle plus le disque.

### 🔒 Sécurité
- **Garde anti-SSRF** sur le proxy local : il refuse toute URL cible pointant
  vers une IP loopback / privée / link-local / réservée (ex. `169.254.169.254`),
  pour qu'un process local ne puisse pas s'en servir comme proxy ouvert vers des
  services internes. Les CDN publics (les vrais flux) passent normalement.
- `clear_screen()` utilise l'échappement ANSI de Rich au lieu de lancer
  `clear`/`cls` (pas de sous-processus, non détournable via le PATH).

### 🩺 Fiabilité
- **Enregistrement atomique** de la progression (écriture temp + `os.replace`) :
  une coupure ne peut plus corrompre `progress.json`.
- **Badge « hors ligne »** dans le menu des sources : une vérification de santé
  en arrière-plan (jamais bloquante, résultat mis en cache) signale une source
  injoignable — une source protégée Cloudflare (403) reste comptée « en ligne ».
- Les sessions curl_cffi transitoires (sonde de qualité, estimation de durée)
  sont **fermées** proprement — plus de fuite de descripteurs.
- **Nettoyage périodique de `.temp/`** au démarrage (en tâche de fond) : les
  dossiers orphelins d'un téléchargement interrompu/planté sont purgés.

### 🧱 Plateformes
- **Détection d'architecture** (`x86_64` / `arm64`) : sur aarch64, le binaire
  ffmpeg géré bascule sur la build ARM64 (BtbN). Sous Linux mpv/aria2 viennent
  du gestionnaire de paquets (indépendant de l'arch), et sous Windows-on-ARM les
  builds x64 tournent via l'émulation intégrée.

### 🇫🇷 Traductions
- **Fin de la traduction FR de l'interface** : tous les messages `print_*`, les
  spinners et l'assistant de configuration passent par `t()` (75 chaînes
  ajoutées) — plus d'anglais résiduel dans les écrans courants.

### 🧪 Tests / CI
- Nouvelle **CI GitHub Actions** (Ubuntu + Windows, Python 3.9 & 3.12) : ruff
  puis pytest à chaque push/PR.
- Tests unitaires **multi-plateformes du décodeur clavier** (aurait attrapé la
  régression des flèches Windows de 1.8.4), plus des tests pour la garde SSRF, le
  démarrage paresseux du proxy et les badges de santé des sources.

### 🧹 Nettoyage
- Suppression de code mort (`get_language_flag`, `cloudflare.available`).

## 1.8.5

### 🪟 Windows: arrow keys work again (regression fix)
- 1.8.4's new Windows key reader broke the **arrow keys**: the classic-console
  special-key prefix (`\x00`/`\xe0`) was read behind a wrong `kbhit()` guard, and
  the VT escape sequence (`\x1b[A…`) wasn't always fully drained. Arrows now read
  reliably in both classic console and Windows Terminal (VT) mode, while focus
  events (`\x1b[I`/`\x1b[O`) are still ignored and a lone Esc still goes back.
## 1.8.4

### 🪟 Windows fixes (important)
- **"FreeFlix manipulates itself / Esc presses by itself" — fixed for real on
  Windows.** The previous fix was POSIX-only; on Windows the menus fell back to
  readchar, which mis-read Windows-Terminal **focus events** (`\x1b[I` / `\x1b[O`
  on Alt-Tab) as a stray Esc, stepping back through menus until it closed the
  app. There's now a dedicated **msvcrt reader** that drains the whole escape
  sequence and ignores focus/mouse events — applied to the menus AND the search
  results pane. Only a truly isolated Esc goes back.
- **Stops asking to install the players on every launch.** Once you've completed
  first-run setup, the full wizard no longer re-triggers (a silently-failed
  shader download used to make it re-prompt forever). Player detection also now
  finds mpv.net / VLC installed **outside PATH** (winget links dir, Program
  Files…), so an installed player is no longer reported missing.
## 1.8.3

### 🔎 Search history
- The search box now shows your **recent searches**; press **↑/↓ to recall** a
  previous query. History is deduped and capped.

### 🆕 New releases (background, personalised)
- A daemon thread checks — **without ever blocking the home** — whether the
  Anime-Sama shows in your history have a newer season/part. When they do, a
  **New releases** entry appears (and a home teaser), opening a **poster preview
  list** (chafa) that jumps straight into the new season.

### ⚙️ Settings, reorganised
- Settings are now grouped into **Playback / Downloads / Appearance / Accounts**
  (data-driven, no more brittle index dispatch). Type **`/`** to search settings.

### 🎨 Themes
- Four new themes (**Gruvbox, Tokyo Night, Rosé Pine, Monochrome**), a
  **custom accent colour**, and a **live preview** panel before you apply.

### ⬇️ Downloads manager
- "My Downloads" is now a manager: **disk-space + total-size summary**, play or
  **delete** finished files, and resume/delete interrupted ones — all in a loop.
## 1.8.2

### 🏠 Enriched home screen
- A **dashboard** now greets you at the top of the home menu: a **greeting**, a
  quick **stats line** (this week · streak · in-progress count) and a
  **Continue-watching carousel** listing your last shows with resume/watched/
  downloaded badges — all from local data, instant, no network.

### 🗂️ Sources
- **French-Anime** (ex French-Manga) moved to **2nd position** in the anime
  sources; **⭐ recommended** badge on **Anime-Sama** and **French-Stream**.
- All **source descriptions are now translated** (menu + startup splash) plus the
  remaining English messages in the Anime-Sama flow.

### ⏳ Startup
- The launch **progress bar fills visibly again** — the easing was too slow for
  the short splash, so the bar barely moved; it now climbs to 100% smoothly.

## 1.8.1.post1

Fixes shipped as a post-release of 1.8.1 (PyPI versions are immutable):

- **Anime-Sama missing seasons/parts** — the season parser stopped early and
  dropped later seasons (e.g. **Dr Stone** hid Saison 3 Partie 2 and Saison 4
  + parts 2/3). It now matches ALL `panneauAnime(...)` declarations on the page.
- **"FreeFlix closed by itself" / phantom Esc** — terminals (and mpv) that enable
  focus reporting send `\x1b[I` / `\x1b[O` on Alt-Tab, which a split read could
  mistake for a stray Esc. The key reader now drains the whole escape sequence
  and ignores focus/mouse/paste events; FreeFlix also disables those reports at
  startup and after every player exit.
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
