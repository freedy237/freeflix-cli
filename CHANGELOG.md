# Changelog

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
