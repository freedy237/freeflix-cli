# Utilisation

## Lancer

```bash
freeflix            # interface
freeflix --setup    # refaire le choix des langues + dépendances
freeflix --doctor   # diagnostic
freeflix --doctor --sources   # audit live de chaque source
freeflix --verbose  # DEBUG dans la console (toujours dans le log)
```

Au premier lancement : langue des animes (VO/VF), langue de l'interface,
puis installation des dépendances (mpv, ffmpeg, yt-dlp, aria2c, chafa,
police Nerd) et des shaders Anime4K.

## Accueil

| Entrée | Rôle |
|---|---|
| **Reprendre** | reprend le dernier épisode/film à la seconde près (mpv) |
| **Continuer depuis AniList** | reprend un anime suivi sur AniList (token requis) |
| **Parcourir les sources** | la liste des 10 sources, filtrée par langue de contenu |
| **Nouveautés** | nouveaux épisodes des animes suivis/regardés |
| **Mon historique** | reprendre, marquer vu ou supprimer une entrée |
| **Mes téléchargements** | lire les fichiers de `~/Downloads/FreeFlix/` |
| **Mes stats** | temps, séries, genres, activité 7 jours |
| **Réglages** | AniList, langues, lecteur, qualité, sous-titres, thème, cache |
| **Quitter** | quitte et restaure le terminal |

## Navigation

- `↑` / `↓` : naviguer (ou molette), `Entrée` : choisir.
- `Échap` : revenir d'un niveau. La dernière ligne d'un menu est toujours
  « Retour / Annuler / Quitter ».
- `/` : filtrer la liste affichée, `?` : aide contextuelle.
- `q` : quitter un écran de lecture (comportement mpv).
- Souris : survol, clic, molette, clic droit = retour, pagination cliquable.
- `Ctrl-C` : annuler l'opération en cours (téléchargement, scraping).

## Sources

Anime : Anime-Sama (FR + multi-langues), French-Anime (VF/VOSTFR), HiAnime
(EN sub/dub), GoldenAnime (VO + sous-titres), Nyaa (torrents).
Films/séries : GoldenMS, French-Stream, Coflix, Papystreaming (catalogue EN),
YTS/EZTV (torrents).
Certaines sources proposent **Derniers ajouts** en plus de la recherche.

### Planning Anime-Sama

Menu de la source → **Planning du moment** : grille des 7 jours, posters,
épisodes sortis ou à venir. Sur un anime :

- **Suivre cet anime** : il entre dans Nouveautés sans lancer d'épisode ;
- **Parcourir les saisons** : flux normal (saison → langue → épisode).

### Nouveautés

Un épisode est annoncé quand il est **réellement sorti** (état `released` du
planning), qu'il est plus récent que le dernier vu, et que l'anime est suivi
ou présent dans l'historique. Ouvrir l'élément le retire du badge ; l'épisode
de la semaine suivante réapparaît tout seul.

## Lecture

Avant de lancer, chaque lecteur est analysé : résolution, débit, et durée
réelle. Un flux < 90 s est marqué `⚠` (pub/placeholder) et n'est pas pris
pour un épisode. Menu lecteur : mpv, VLC, navigateur, téléchargement seul.

Qualité : `auto` (meilleure disponible), 1080p, 720p, 480p. En HLS, mpv est
plafonné à la variante choisie (`--hls-bitrate`) ; en DASH, mpv uniquement.

### Raccourcis mpv

`CTRL+1` Anime4K VL, `CTRL+2` Anime4K S, `CTRL+0` off, `#` audio, `j`
sous-titres, `_`/`ALT+V` vidéo, `i` stats, `Échap` retour FreeFlix.

## Téléchargements

- Un épisode ou une saison entière (1–4 workers en parallèle).
- Staging `~/Downloads/FreeFlix/.temp/` → vérification durée/taille →
  déplacement atomique. Un fichier incomplet devient `.incomplete` et peut
  être repris ; un fichier partiel n'est jamais publié.
- Reprise après coupure réseau ou changement d'opérateur.
- `Échap Échap` (ou double-clic sur la barre) annule proprement.

## Langues

Deux réglages distincts :

- **langue de l'interface** (FR/EN) : traduit tous les menus ;
- **langue des animes** (VO/VF) : filtre les sources et les langues de flux.

Les changer dans Réglages reconstruit immédiatement la liste des sources.

## Thèmes et accessibilité

12 thèmes, **Cinema Noir** par défaut. `FREEFLIX_REDUCED_MOTION=1` (ou le
réglage) fige les animations. Thème `mono` pour les terminaux à fort contraste.
Aucune information n'est portée par la couleur seule ; les messages ont un
glyphe et un libellé.
