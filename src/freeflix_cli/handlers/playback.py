from ..cli_utils import (
    select_from_list,
    print_info,
    print_warning,
    print_error,
    print_success,
    spinner,
)
from ..player_manager import play_video, analyze_stream_quality, format_quality_label, clean_season_title, clean_episode_title
from ..tracker import tracker
from ..scraping import player
from ..i18n import t
from ..icons import icon


def _search_subtitle(series_title, season_title, episode_title):
    """
    Offer + fetch an external subtitle for any source (parity with
    GoldenAnime, which had this exclusively). Resolves an IMDb id via
    Cinemeta, searches the subtitle extractor, lets the user pick.
    Returns a subtitle URL or None.
    """
    import re as _re
    import urllib.parse as _up
    from curl_cffi import requests as _rq
    from ..scraping.subtitles import subtitle_extractor

    lang = tracker.get_anime_language() or tracker.get_language() or "en"
    if select_from_list([t("Yes"), t("No")], t("Search for subtitles?")) != 0:
        return None

    imdb_id, is_movie = None, False
    try:
        for typ in ("series", "movie"):
            u = (f"https://v3-cinemeta.strem.io/catalog/{typ}/top/"
                 f"search={_up.quote(series_title)}.json")
            metas = _rq.get(u, timeout=6, impersonate="chrome").json().get("metas", [])
            for m in metas:
                if m.get("imdb_id"):
                    imdb_id, is_movie = m["imdb_id"], (typ == "movie")
                    break
            if imdb_id:
                break
    except Exception:
        imdb_id = None

    if not imdb_id:
        print_warning(t("Could not find subtitles for this title."))
        return None

    season = episode = None
    if not is_movie:
        m = _re.search(r"(\d+)", episode_title or "")
        episode = int(m.group(1)) if m else 1
        m2 = _re.search(r"(\d+)", season_title or "")
        season = int(m2.group(1)) if m2 else 1

    try:
        with spinner(t("Searching for subtitles…")):
            subs = subtitle_extractor.search(
                imdb_id=imdb_id, season=season, episode=episode, lang_filter=lang
            )
    except Exception:
        subs = None

    if not subs:
        print_warning(t("No subtitles found."))
        return None

    choices = [f"{s['source']} - {s.get('lang', lang)}" for s in subs[:6]] + [t("None")]
    idx = select_from_list(choices, f"{icon('subtitle')} {t('Select Subtitle:')}")
    if idx < len(subs[:6]):
        print_info(f"{t('Selected subtitle from:')} {subs[idx]['source']}")
        return subs[idx]["url"]
    return None


def play_episode_flow(
    provider_name: str,
    series_title: str,
    season_title: str,
    episode: object,
    series_url: str,
    season_url: str,
    logo_url: str = None,
    headers: dict = None,
    anilist_callback: callable = None,
    genres=None,
) -> bool:
    """
    Handle the playback flow for a single episode:
    1. Check for players.
    2. Ask user to select a player.
    3. Play the video.
    4. Save progress if successful.
    5. Call optional AniList callback if successful.

    Returns:
        bool: True if playback was successful, False otherwise (back/cancel).
    """

    if not episode.players:
        print_warning(t("No players found for this episode."))
        return False

    supported_players = [p for p in episode.players if player.is_supported(p.url)]
    if not supported_players:
        print_warning(t("No supported players found."))
        return False

    # Default headers if not provided
    if headers is None:
        headers = {}

    # Optionally analyse every player up front : resolutions + the bitrate
    # needed for stable playback, shown next to each player. Runs in
    # parallel (thread-safe extractor) behind a spinner.
    quality_map = {}
    if tracker.get_analyze_players():
        from concurrent.futures import (
            ThreadPoolExecutor,
            as_completed,
            TimeoutError as _FTimeout,
        )

        # Hard TOTAL budget : a single slow/hanging host (some embeds take
        # 25 s+) must not stall the whole menu. Collect what's done within
        # the budget ; stragglers just get no annotation, and we DON'T wait
        # for them on exit (shutdown(wait=False)).
        ANALYSIS_BUDGET = 14
        ex = ThreadPoolExecutor(max_workers=8)
        futs = {
            ex.submit(analyze_stream_quality, p.url, headers): p
            for p in supported_players
        }
        with spinner(t("Analyzing players (resolutions, bitrate)…")):
            try:
                for fut in as_completed(futs, timeout=ANALYSIS_BUDGET):
                    p = futs[fut]
                    try:
                        quality_map[p.url] = format_quality_label(fut.result())
                    except Exception:
                        quality_map[p.url] = "✗"
            except _FTimeout:
                pass  # budget hit — remaining players show no quality tag
        ex.shutdown(wait=False)

    # Offer external subtitles (all sources now, not just GoldenAnime).
    subtitle_url = None
    if tracker.get_subtitle_search():
        subtitle_url = _search_subtitle(
            series_title, season_title, getattr(episode, "title", "")
        )

    while True:
        # Player Selection Menu
        player_options = []
        for p in supported_players:
            host = p.url.split("/")[2].split(".")[-2]
            label = f"{p.name} : {host}"
            q = quality_map.get(p.url)
            if q:
                label += f"  —  {q}"
            player_options.append(label)
        player_options.append(t("← Back"))

        player_idx = select_from_list(
            player_options,
            t("🎮 Select Player:"),
        )

        if player_idx == len(supported_players):  # Back selected
            return False

        selected_player = supported_players[player_idx]

        # Construct title for player window (de-duplicate season + episode)
        clean_season = clean_season_title(series_title, season_title)
        clean_episode = clean_episode_title(series_title, season_title, episode.title)
        window_title = f"{series_title} - {clean_season} - {clean_episode}"

        success = play_video(
            selected_player.url,
            headers=headers,
            title=window_title,
            subtitle_url=subtitle_url,
        )

        if success:
            # Save Local Progress

            tracker.save_progress(
                provider=provider_name,
                series_title=series_title,
                season_title=season_title,
                episode_title=episode.title,
                series_url=series_url,
                season_url=season_url,
                episode_url=episode.url if hasattr(episode, "url") else "",
                logo_url=logo_url,
            )

            # Stats event (episodes/day, by provider, by genre)
            try:
                tracker.record_watch(provider_name, series_title, genres)
            except Exception:
                pass

            # AniList Hook
            if anilist_callback:
                anilist_callback()

            return True
        else:
            # Playback failed
            retry = select_from_list(
                [t("Try another server/player"), t("← Back to main menu")],
                t("What would you like to do?"),
            )
            if retry == 1:  # Back
                return False
            # Loop continues to select list


def _download_one_episode(
    provider_name: str,
    series_title: str,
    season_title: str,
    episode,
    series_url: str,
    season_url: str,
    logo_url: str,
    headers: dict,
    label: str,
) -> bool:
    """Worker: download a single episode, trying each supported player URL."""
    if not getattr(episode, "players", None):
        print_warning(f"{label} — no players, skipping.")
        return False

    supported_players = [p for p in episode.players if player.is_supported(p.url)]
    if not supported_players:
        print_warning(f"{label} — no supported players, skipping.")
        return False

    print_info(f"⬇ {label} — starting download")
    clean_season = clean_season_title(series_title, season_title)
    clean_episode = clean_episode_title(series_title, season_title, episode.title)
    window_title = f"{series_title} - {clean_season} - {clean_episode}"

    for sp in supported_players:
        ok = play_video(
            sp.url,
            headers=headers,
            title=window_title,
            force_player="download",
        )
        if ok:
            tracker.save_progress(
                provider=provider_name,
                series_title=series_title,
                season_title=season_title,
                episode_title=episode.title,
                series_url=series_url,
                season_url=season_url,
                episode_url=episode.url if hasattr(episode, "url") else "",
                logo_url=logo_url,
            )
            print_success(f"✓ {label} done")
            return True
        print_warning(f"   server {sp.name} failed, trying next…")

    print_error(f"✗ {label} all servers failed")
    return False


def download_episodes_batch(
    provider_name: str,
    series_title: str,
    season_title: str,
    episodes: list,
    series_url: str,
    season_url: str,
    logo_url: str = None,
    headers: dict = None,
) -> dict:
    """
    Download every episode in `episodes` non-interactively.
    Honors tracker.get_parallel_downloads() : N workers in parallel.
    Returns {episode_title: bool} indicating per-episode success.
    """
    if headers is None:
        headers = {}

    parallel = tracker.get_parallel_downloads()
    total = len(episodes)
    results: dict = {ep.title: False for ep in episodes}

    if parallel <= 1:
        for idx, episode in enumerate(episodes, start=1):
            label = f"[{idx}/{total}] {episode.title}"
            results[episode.title] = _download_one_episode(
                provider_name, series_title, season_title, episode,
                series_url, season_url, logo_url, headers, label,
            )
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print_info(f"Running {parallel} downloads in parallel…")
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            future_to_episode = {}
            for idx, episode in enumerate(episodes, start=1):
                label = f"[{idx}/{total}] {episode.title}"
                future = executor.submit(
                    _download_one_episode,
                    provider_name, series_title, season_title, episode,
                    series_url, season_url, logo_url, headers, label,
                )
                future_to_episode[future] = episode

            for future in as_completed(future_to_episode):
                ep = future_to_episode[future]
                try:
                    results[ep.title] = future.result()
                except Exception as e:
                    print_error(f"✗ {ep.title} crashed: {e}")
                    results[ep.title] = False

    succeeded = sum(1 for v in results.values() if v)
    print_info(f"\nBatch complete: {succeeded}/{total} episodes downloaded.")
    return results
