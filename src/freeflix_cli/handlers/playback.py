from ..cli_utils import (
    select_from_list,
    print_info,
    print_warning,
    print_error,
    print_success,
)
from ..player_manager import play_video
from ..tracker import tracker
from ..scraping import player
from ..i18n import t


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

    while True:
        # Player Selection Menu
        player_options = [
            f"{p.name} : {p.url.split('/')[2].split('.')[-2]}"
            for p in supported_players
        ]
        player_options.append(t("← Back"))

        player_idx = select_from_list(
            player_options,
            t("🎮 Select Player:"),
        )

        if player_idx == len(supported_players):  # Back selected
            return False

        selected_player = supported_players[player_idx]

        # Construct title for player window
        window_title = f"{series_title} - {season_title} - {episode.title}"

        success = play_video(
            selected_player.url,
            headers=headers,
            title=window_title,
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
    window_title = f"{series_title} - {season_title} - {episode.title}"

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
