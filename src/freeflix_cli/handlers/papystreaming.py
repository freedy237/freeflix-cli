"""Papystreaming provider handler (French movies & series, TMDB-based)."""

from __future__ import annotations

from ..scraping import papystreaming
from .goldenms import _flow_goldenms_stream, search_cinemeta, get_cinemeta_details
from ..cli_utils import (
    select_from_list,
    select_with_preview,
    make_preview,
    get_user_input,
    print_warning,
    pause,
    spinner,
)
from ..icons import icon
from ..i18n import t


def _pick_season_episode(title: str, year: str):
    """Show SELECTABLE seasons/episodes (via Cinemeta, keyed by title+year),
    so the user picks from a list instead of typing numbers. Returns
    (season, episode), or (None, None) if backed out. Falls back to manual
    entry when Cinemeta has no episode list for the title."""
    videos = []
    try:
        with spinner(t("Loading seasons…")):
            metas = search_cinemeta(title, is_movie=False)
            meta = None
            if metas:
                meta = next(
                    (m for m in metas
                     if year and year in str(m.get("releaseInfo", ""))),
                    metas[0],
                )
            if meta:
                full = get_cinemeta_details(meta.get("id", ""), is_movie=False)
                videos = full.get("videos", []) or []
    except Exception:
        videos = []

    if not videos:
        s = get_user_input(t("Season number"), default="1")
        e = get_user_input(t("Episode number"), default="1")
        return (int(s) if s and s.isdigit() else 1,
                int(e) if e and e.isdigit() else 1)

    season_map: dict = {}
    for v in videos:
        s = v.get("season")
        if not s:
            continue
        season_map.setdefault(s, []).append(
            (v.get("episode") or 0, v.get("name") or f"Episode {v.get('episode')}")
        )
    seasons = sorted(season_map)

    s_opts = [f"{t('Season')} {s}" for s in seasons] + [t("← Back")]
    s_idx = select_from_list(s_opts, f"{icon('tv')} {t('Select Season:')}")
    if s_idx >= len(seasons):
        return (None, None)
    season = seasons[s_idx]

    eps = sorted(season_map[season], key=lambda x: x[0])
    e_opts = [f"E{ep[0]:02d} - {ep[1]}" for ep in eps] + [t("← Back")]
    e_idx = select_from_list(e_opts, f"{icon('tv')} {t('Select Episode:')}")
    if e_idx >= len(eps):
        return (None, None)
    return (season, eps[e_idx][0])


def handle_papystreaming():
    """Search Papystreaming, then resolve + play via the shared resolvers."""
    query = get_user_input(
        "Search query (or 'exit' to back)",
        header=f"{icon('movie')} Papystreaming",
    )
    if not query or query.lower() == "exit":
        return

    with spinner(f"{t('Searching for')} {query}…"):
        results = papystreaming.search(query)
    if not results:
        print_warning(t("No results found."))
        pause()
        return

    # Preview pane : poster + type/year beside the result list.
    previews = [
        make_preview(
            cover=r["poster"],
            title=r["title"],
            lines=[
                ("Film" if r["media_type"] == "movie" else "Série")
                + (f" · {r['year']}" if r["year"] else "")
            ],
            panel_title="Papystreaming",
        )
        for r in results
    ]
    labels = [r["title"] + (f" ({r['year']})" if r["year"] else "") for r in results]
    idx = select_with_preview(
        labels, f"{icon('tv')} {t('Search Results:')}", previews
    )
    if idx >= len(results):  # Esc / Back
        return
    sel = results[idx]

    is_movie = sel["media_type"] == "movie"
    season = episode = None
    if not is_movie:
        season, episode = _pick_season_episode(sel["title"], sel["year"])
        if season is None:  # backed out of the season/episode picker
            return

    _flow_goldenms_stream(
        title=sel["title"],
        tmdb_id=sel["tmdb_id"],
        imdb_id="",
        year=sel["year"] or None,
        season=season,
        episode=episode,
        is_movie=is_movie,
        logo_url=sel["poster"],
    )
