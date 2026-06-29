"""
Tiny i18n helper.

Wrap user-facing strings with `t("English source")`. When tracker
language is "fr", the dict below provides the French translation ;
otherwise the original string is returned untouched, so new strings
never break the app.

Add a key here once and prefix every call site with t(...).
"""

_FR = {
    # ── Home menu ────────────────────────────────────────────────
    "FreeFlix CLI - Home": "FreeFlix CLI — Accueil",
    "What would you like to do?": "Que veux-tu faire ?",
    "▶ Continue from AniList": "▶ Continuer depuis AniList",
    "📜 My History": "📜 Mon historique",
    "📁 My Downloads": "📁 Mes téléchargements",
    "📊 My Stats": "📊 Mes stats",
    "📊 My Stats:": "📊 Mes stats",
    # ── Theme ──
    "Theme": "Thème",
    "Select theme:": "Choisis un thème :",
    "Theme set to:": "Thème défini sur :",
    # ── Stats dashboard ──
    "Viewing statistics": "Statistiques de visionnage",
    "No viewing history yet — watch something first!":
        "Aucun historique pour l'instant — regarde quelque chose d'abord !",
    "Total watched": "Total regardé",
    "Today": "Aujourd'hui",
    "This week": "Cette semaine",
    "This month": "Ce mois",
    "Day streak": "Jours d'affilée",
    "By source": "Par source",
    "Favorite genres": "Genres favoris",
    "Most watched": "Les plus regardés",
    "🌍 Browse Providers": "🌍 Parcourir les sources",
    "⚙ Settings (AniList)": "⚙ Paramètres",
    "❌ Exit": "❌ Quitter",
    "Select a Provider:": "Choisis une source :",
    "Goodbye!": "Au revoir !",

    # ── Common navigation ───────────────────────────────────────
    "← Back": "← Retour",
    "← Cancel": "← Annuler",
    "Cancel": "Annuler",
    "Back": "Retour",
    "Yes": "Oui",
    "No": "Non",

    # ── History ─────────────────────────────────────────────────
    "No history found.": "Aucun historique trouvé.",
    "Select an entry to resume or delete:": "Choisis une entrée à reprendre ou à supprimer :",
    "Action:": "Action :",
    "▶ Resume": "▶ Reprendre",
    "❌ Delete": "❌ Supprimer",
    "Entry deleted.": "Entrée supprimée.",

    # ── Downloads browser ───────────────────────────────────────
    "Select a file to play:": "Choisis un fichier à lire :",

    # ── Provider flows ──────────────────────────────────────────
    "🎌 Anime-Sama": "🎌 Anime-Sama",
    "Search query (or 'exit' to back)": "Recherche (ou « exit » pour revenir)",
    "📺 Search Results:": "📺 Résultats de recherche :",
    "Search Results:": "Résultats de recherche :",
    "Select Match:": "Choisis un résultat :",
    "Select AniList Match:": "Choisis le résultat AniList :",
    "Sources": "Sources",
    "Anime / Manga": "Anime / Manga",
    "Movies & Series": "Films & Séries",
    "Other": "Autres",
    "Select Season:": "Choisis la saison :",
    "Select Episode:": "Choisis l'épisode :",
    "Season number": "Numéro de saison",
    "Episode number": "Numéro d'épisode",
    "Season": "Saison",
    "Loading seasons…": "Chargement des saisons…",
    "📺 Select Season:": "📺 Choisis la saison :",
    "🌍 Select Language:": "🌍 Choisis la langue :",
    "📺 Select Episode:": "📺 Choisis l'épisode :",
    "🎮 Select video player:": "🎮 Choisis le lecteur :",
    "📺 Choisis la qualité :": "📺 Choisis la qualité :",
    "Auto (best)": "Auto (meilleure)",
    "This source is Cloudflare-protected and can't be played from the terminal.":
        "Cette source est protégée par Cloudflare et ne peut pas être lue depuis le terminal.",
    "→ Pick ANOTHER source from the list (e.g. Vidlink, another server), or try again later.":
        "→ Choisis une AUTRE source dans la liste (ex: Vidlink, un autre serveur), ou réessaie plus tard.",
    "🎮 Select Player:": "🎮 Choisis le lecteur :",
    "No results found.": "Aucun résultat trouvé.",
    "No seasons found.": "Aucune saison trouvée.",
    "No episodes found.": "Aucun épisode trouvé.",
    "No players found for this episode.": "Aucun lecteur trouvé pour cet épisode.",
    "No supported players found.": "Aucun lecteur supporté.",
    "Mark which episode as watched?": "Marquer quel épisode comme vu ?",
    "✓ Mark an episode as watched (no play)": "✓ Marquer un épisode comme vu (sans le lire)",
    "Download ALL episodes": "Télécharger TOUS les épisodes",
    "Download": "Télécharger",
    "Select episodes to download:": "Choisis les épisodes à télécharger :",
    "already downloaded": "déjà téléchargé",
    "Interrupted downloads": "Téléchargements interrompus",
    "interrupted": "interrompu",
    "Resume download": "Reprendre le téléchargement",
    "Delete partial": "Supprimer le partiel",
    "Download completed.": "Téléchargement terminé.",
    "Could not resume — the stream link may have expired; "
    "re-download it from the source.":
        "Reprise impossible — le lien a peut-être expiré ; "
        "relance-le depuis la source.",
    "Partial deleted.": "Partiel supprimé.",
    "selected": "sélectionné(s)",
    "Space: select": "Espace : sélectionner",
    "a: all": "a : tout",
    "Enter: confirm": "Entrée : valider",
    "Esc: back": "Échap : retour",
    "Analyzing available qualities…": "Analyse des qualités disponibles…",
    "Estimating episode size…": "Estimation de la taille par épisode…",
    "Select quality for batch download:": "Choisis la qualité pour le téléchargement complet :",
    "Marked as watched.": "Marqué comme vu.",
    "Play next episode:": "Lire l'épisode suivant :",
    "Continue": "Continuer",
    "Watch again": "Revoir",
    "No next episode": "Pas d'épisode suivant",
    "No next episode found.": "Pas d'épisode suivant trouvé.",

    # ── Settings ────────────────────────────────────────────────
    "Settings": "Paramètres",
    "Select Setting:": "Choisis un paramètre :",
    "Update AniList Token": "Modifier le jeton AniList",
    "Update Language": "Modifier la langue",
    "Update Anime Language": "Modifier la langue des animes",
    "Languages": "Langues",
    "Show Posters": "Afficher les pochettes",
    "recommended": "recommandé",
    "Icon Style": "Style d'icônes",
    "Cloudflare token": "Token Cloudflare",
    "Data used": "Données consommées",
    "Download subtitles": "Télécharger les sous-titres",
    "Subtitle download:": "Téléchargement des sous-titres :",
    "Search for subtitles?": "Chercher des sous-titres ?",
    "Searching for subtitles…": "Recherche de sous-titres…",
    "No subtitles found.": "Aucun sous-titre trouvé.",
    "Could not find subtitles for this title.": "Impossible de trouver des sous-titres pour ce titre.",
    "Select Subtitle:": "Choisis le sous-titre :",
    "Selected subtitle from:": "Sous-titre choisi depuis :",
    "None": "Aucun",
    "Analyzing players (resolutions, bitrate)…": "Analyse des lecteurs (résolutions, débit)…",
    "Analyze players (resolutions/bitrate)": "Analyser les lecteurs (résolutions/débit)",
    "Player analysis:": "Analyse des lecteurs :",
    "If a source is Cloudflare-blocked, pass the check in your browser,": "Si une source est bloquée par Cloudflare, passe le test dans ton navigateur,",
    "then paste the 'cf_clearance' cookie value + your User-Agent here.": "puis colle ici la valeur du cookie 'cf_clearance' + ton User-Agent.",
    "(cf_clearance is tied to your IP + User-Agent — both must match.)": "(cf_clearance est lié à ton IP + User-Agent — les deux doivent correspondre.)",
    "Other host…": "Autre site…",
    "Clear all tokens": "Effacer tous les tokens",
    "Which source?": "Quelle source ?",
    "Host (e.g. coflix.cymru)": "Site (ex. coflix.cymru)",
    "Paste cf_clearance cookie value": "Colle la valeur du cookie cf_clearance",
    "Paste your browser User-Agent (recommended)": "Colle ton User-Agent de navigateur (recommandé)",
    "All Cloudflare tokens cleared.": "Tous les tokens Cloudflare effacés.",
    "Cloudflare token saved for": "Token Cloudflare enregistré pour",
    "Auto-solver (FlareSolverr)": "Solveur auto (FlareSolverr)",
    "Set FlareSolverr URL (auto-solve)": "Définir l'URL FlareSolverr (résolution auto)",
    "FlareSolverr auto-solves Cloudflare. Leave empty to disable.": "FlareSolverr résout Cloudflare automatiquement. Laisse vide pour désactiver.",
    "FlareSolverr URL [http://localhost:8191]": "URL FlareSolverr [http://localhost:8191]",
    "FlareSolverr URL updated.": "URL FlareSolverr mise à jour.",
    "My History": "Mon historique",
    "My Downloads": "Mes téléchargements",
    "My Stats": "Mes stats",
    "Browse Providers": "Parcourir les sources",
    "Settings (AniList)": "Paramètres",
    "Exit": "Quitter",
    "Continue from AniList": "Continuer depuis AniList",
    "Icon Style:": "Style d'icônes :",
    "Nerd Font needs a Nerd Font selected in your terminal.": "Le mode Nerd Font nécessite une Nerd Font sélectionnée dans ton terminal.",
    "Restart FreeFlix to apply icons everywhere.": "Redémarre FreeFlix pour appliquer les icônes partout.",
    "Anime language:": "Langue des animes :",
    "Anime language updated to:": "Langue des animes mise à jour vers :",
    "Choose default Player": "Choisir le lecteur par défaut",
    "Download Quality": "Qualité de téléchargement",
    "OpenSubtitles API Key": "Clé API OpenSubtitles",
    "Parallel Downloads": "Téléchargements parallèles",
    "Daily New-Episode Notifications": "Notifications quotidiennes",
    "Select Language:": "Choisis la langue :",
    "Select default player:": "Choisis le lecteur par défaut :",
    # Player method display names (mpv/vlc keep their proper names)
    "download": "télécharger",
    "manual": "manuel",
    "browser": "navigateur",
    "Select download quality:": "Choisis la qualité :",
    "Enter new AniList Token": "Saisis le nouveau jeton AniList",
    "Enter OpenSubtitles API key": "Saisis la clé API OpenSubtitles",
    "Token saved.": "Jeton enregistré.",
    "OpenSubtitles key saved.": "Clé OpenSubtitles enregistrée.",
    "Max parallel downloads:": "Téléchargements parallèles max :",
    "Disable daily notifications?": "Désactiver les notifications quotidiennes ?",
    "Enable daily notifications?": "Activer les notifications quotidiennes ?",
    "Notifications enabled (runs daily).": "Notifications activées (exécution quotidienne).",
    "Notifications disabled.": "Notifications désactivées.",
    "Failed to disable notifications.": "Échec de désactivation des notifications.",
    "Language updated to:": "Langue mise à jour vers :",
    "Player updated to:": "Lecteur mis à jour vers :",
    "Download quality set to:": "Qualité de téléchargement :",
    "Parallel downloads set to": "Téléchargements parallèles :",
    "Nvidia offload:": "Offload Nvidia :",
    "Nvidia GPU offload": "Offload GPU Nvidia",
    "Nvidia GPU offload:": "Offload GPU Nvidia :",
    "On laptops with Intel/AMD iGPU + Nvidia dGPU, route":
        "Sur laptops avec iGPU Intel/AMD + dGPU Nvidia, on route",
    "mpv to the Nvidia card for far better Anime4K perf.":
        "mpv vers la carte Nvidia pour de bien meilleurs FPS sur Anime4K.",

    # ── Playback feedback ───────────────────────────────────────
    "Try another server/player": "Essayer un autre serveur/lecteur",
    "← Back to main menu": "← Retour au menu principal",
    "The player failed. What would you like to do?": "Le lecteur a échoué. Que veux-tu faire ?",
    "The download failed. What would you like to do?": "Le téléchargement a échoué. Que veux-tu faire ?",
    "Try another player": "Essayer un autre lecteur",
    "Retry with same player": "Réessayer le même lecteur",
    "Try another player/backend": "Essayer un autre lecteur/backend",
    "Retry download": "Réessayer le téléchargement",

    # ── Resume / continue-watching banner ───────────────────────
    "▶ Resume:": "▶ Reprendre :",

    # ── About panel ─────────────────────────────────────────────
    "About": "À propos",
    "Watch movies, series and anime from your terminal.\n":
        "Films, séries et anime directement depuis ton terminal.\n",
    "License": "Licence",
    "Author": "Auteur",
    "Based on": "Basé sur",
    "by": "par",
    "Anime4K shaders by": "Shaders Anime4K par",

    # ── Update notifier ─────────────────────────────────────────
    "A new version of FreeFlix is available!": "Une nouvelle version de FreeFlix est dispo !",
    "Update available": "Mise à jour disponible",
    "Installed": "Installée",
    "Latest": "Dernière",
    "Upgrade with one of": "Mets à jour avec une de ces commandes",

    # ── Misc ────────────────────────────────────────────────────
    "Resuming": "Reprise de",
    "Loading": "Chargement",
    "Searching for": "Recherche de",
    "First Launch Setup": "Configuration initiale",
    "Please select your preferred language.": "Choisis ta langue préférée.",
    "This will filter available providers and set default subtitle languages.":
        "Elle filtrera les sources disponibles et définira la langue des sous-titres par défaut.",
    "Language set to:": "Langue définie sur :",
    "Choice:": "Choix :",
}


def t(text: str) -> str:
    """Translate a string based on the current tracker language."""
    try:
        from .tracker import tracker
    except ImportError:
        return text
    lang = tracker.get_language() or "en"
    if lang == "fr":
        return _FR.get(text, text)
    return text
