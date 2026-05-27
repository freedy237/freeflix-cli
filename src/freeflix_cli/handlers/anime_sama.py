from ..scraping import anime_sama, player
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    print_success,
    print_error,
    get_user_input,
    console,
    pause,
)
from ..player_manager import play_video
from ..tracker import tracker
from ..anilist import anilist_client
from .playback import play_episode_flow
from ..i18n import t
import re


def _update_anilist_progress(series, season, selected_episode):
    # --- AniList Progress Update ---
    anilist_token = tracker.get_anilist_token()
    if not anilist_token:
        return

    # Try to extract episode number
    episode_num = 1
    match = re.search(r"(\d+)", selected_episode.title)
    if match:
        episode_num = int(match.group(1))

    # Check if we have a mapping
    media_id = tracker.get_anilist_mapping("Anime-Sama", series.title, season.title)

    if not media_id:
        # Ask user if they want to link
        link_choice = select_from_list(
            ["Yes", "No"],
            f"Link '{series.title}' to AniList for auto-tracking?",
        )
        if link_choice == 0:
            results = anilist_client.search_media(series.title)
            if results:
                media_options = [
                    f"{m['title']['english'] or m['title']['romaji']} ({m['seasonYear']})"
                    for m in results
                ] + ["Cancel"]
                m_idx = select_from_list(media_options, "Select AniList Match:")
                if m_idx < len(results):
                    media_id = results[m_idx]["id"]
                    tracker.set_anilist_mapping(
                        "Anime-Sama", series.title, media_id, season.title
                    )
                    print_success(
                        f"Linked to {results[m_idx]['title']['english'] or results[m_idx]['title']['romaji']}!"
                    )
            else:
                print_warning("No matches found on AniList.")

    if media_id:
        # Update progress with overflow detection
        print_info(f"Updating AniList to episode {episode_num}...")
        anilist_client.set_token(anilist_token)

        # Fetch media details to check total episodes
        media_details = anilist_client.get_media_with_relations(media_id)

        if (
            media_details
            and media_details.get("episodes")
            and episode_num > media_details["episodes"]
        ):
            total_eps = media_details["episodes"]
            print_warning(
                f"Episode {episode_num} exceeds max episodes ({total_eps}) for this AniList entry."
            )

            # Check for SEQUEL relation
            sequel = None
            relations = media_details.get("relations", {}).get("edges", [])
            for rel in relations:
                if rel["relationType"] == "SEQUEL" and rel["node"]["format"] in [
                    "TV",
                    "ONA",
                    "MOVIE",
                ]:
                    sequel = rel["node"]
                    break

            if sequel:
                sequel_title = sequel["title"]["english"] or sequel["title"]["romaji"]
                print_info(f"Found sequel: [cyan]{sequel_title}[/cyan]")

                if (
                    select_from_list(
                        ["Yes", "No"],
                        f"Switch AniList mapping to sequel '{sequel_title}'?",
                    )
                    == 0
                ):
                    # Calculate new relative episode number?
                    new_ep_num = episode_num
                    if episode_num > total_eps:
                        new_ep_num = episode_num - total_eps

                    print_info(
                        f"Updating mapping to use Episode {new_ep_num} on new entry..."
                    )
                    tracker.set_anilist_mapping(
                        "Anime-Sama", series.title, sequel["id"], season.title
                    )
                    media_id = sequel["id"]
                    episode_num = new_ep_num

        if anilist_client.update_progress(media_id, episode_num):
            print_success("AniList updated!")
        else:
            print_error("Failed to update AniList.")


def handle_anime_sama():
    """Handle Anime-Sama provider flow."""
    anime_sama.get_website_url()

    print_header(t("🎌 Anime-Sama"))
    query = get_user_input(t("Search query (or 'exit' to back)"))
    if not query or query.lower() == "exit":
        return

    print_info(f"{t('Searching for')}: [cyan]{query}[/cyan]")
    results = anime_sama.search(query)

    if not results:
        print_warning(t("No results found."))
        pause()
        return

    choice_idx = select_from_list(
        [f"{r.title} ({', '.join(r.genres)})" for r in results], t("📺 Search Results:")
    )
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    series = anime_sama.get_series(selection.url)

    if not series.seasons:
        print_warning(t("No seasons found."))
        pause()
        return

    # Check for saved progress for this specific series
    saved_progress = tracker.get_series_progress("Anime-Sama", series.title)
    if saved_progress:
        choice = select_from_list(
            [
                f"Resume {saved_progress['season_title']} - {saved_progress['episode_title']}",
                "Browse Seasons",
            ],
            f"Found saved progress for {series.title}:",
        )
        if choice == 0:
            resume_anime_sama(saved_progress)
            return

    season_idx = select_from_list(
        [s.title for s in series.seasons], t("📺 Select Season:")
    )
    selected_season_access = series.seasons[season_idx]

    print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
    season = anime_sama.get_season(selected_season_access.url)

    # episodes is dict {lang: [Episode]}
    langs = list(season.episodes.keys())
    if not langs:
        print_warning(t("No episodes found."))
        pause()
        return

    lang_idx = select_from_list(langs, t("🌍 Select Language:"))
    selected_lang = langs[lang_idx]
    episodes = season.episodes[selected_lang]

    BATCH_LABEL = f"📥 {t('Download ALL episodes')} ({len(episodes)})"
    MARK_LABEL = t("✓ Mark an episode as watched (no play)")
    ep_options = [BATCH_LABEL, MARK_LABEL] + [e.title for e in episodes]
    ep_choice = select_from_list(ep_options, t("📺 Select Episode:"))

    if ep_choice == 0:
        from .playback import download_episodes_batch
        download_episodes_batch(
            provider_name="Anime-Sama",
            series_title=series.title,
            season_title=season.title,
            episodes=episodes,
            series_url=series.url,
            season_url=selected_season_access.url,
            logo_url=series.img,
            headers={"Referer": anime_sama.website_origin},
        )
        pause()
        return

    if ep_choice == 1:
        mark_options = [e.title for e in episodes] + [t("← Cancel")]
        mark_choice = select_from_list(mark_options, t("Mark which episode as watched?"))
        if mark_choice == len(episodes):
            return
        marked = episodes[mark_choice]
        tracker.save_progress(
            provider="Anime-Sama",
            series_title=series.title,
            season_title=season.title,
            episode_title=marked.title,
            series_url=series.url,
            season_url=selected_season_access.url,
            episode_url=marked.url if hasattr(marked, "url") else "",
            logo_url=series.img,
        )
        # Also push to AniList if user is logged in (same logic as real playback)
        try:
            _update_anilist_progress(series, season, marked)
        except Exception as e:
            print_warning(f"AniList sync skipped: {e}")
        print_success(f"Marked '{marked.title}' as watched.")
        pause()
        return

    ep_idx = ep_choice - 2  # Adjust for batch + mark options

    while True:
        selected_episode = episodes[ep_idx]

        success = play_episode_flow(
            provider_name="Anime-Sama",
            series_title=series.title,
            season_title=season.title,
            episode=selected_episode,
            series_url=series.url,
            season_url=selected_season_access.url,
            logo_url=series.img,
            headers={"Referer": anime_sama.website_origin},
            anilist_callback=lambda: _update_anilist_progress(
                series, season, selected_episode
            ),
        )

        if success:
            if ep_idx + 1 < len(episodes):
                next_ep = episodes[ep_idx + 1]
                choice = select_from_list(
                    ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                )
                if choice == 0:
                    ep_idx += 1
                    continue
            break
        else:
            return  # Back


def resume_anime_sama(data):
    """Resume Anime-Sama playback."""
    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    # We need to reload just the season to find the episode link/player
    # We have season_url saved.
    anime_sama.get_website_url()

    # Re-fetch season
    season_url = data["season_url"]
    if season_url.startswith("/") or not season_url.startswith("http"):
        season_url = anime_sama.website_origin.rstrip("/") + season_url

    print_info(f"Loading Season: {season_url}")
    try:
        season = anime_sama.get_season(season_url)
    except Exception as e:
        print_error(f"Could not load season: {e}")
        return

    langs = list(season.episodes.keys())
    if not langs:
        print_error(
            "No episodes could be loaded from this season — the site layout "
            "may have changed or the history entry has a stale URL."
        )
        print_info(f"URL tried: {season_url}")
        pause()
        return

    # If only one language, pick it. If multiple, ask.
    if len(langs) == 1:
        selected_lang = langs[0]
    else:
        lang_idx = select_from_list(langs, "🌍 Select Language:")
        selected_lang = langs[lang_idx]

    episodes = season.episodes[selected_lang]

    # Find the episode index
    start_ep_idx = 0
    saved_ep_title = data["episode_title"]

    for i, ep in enumerate(episodes):
        if ep.title == saved_ep_title:
            start_ep_idx = i
            break

    # Propose to continue (next episode) or watch again
    options = [
        (
            f"Continue (Next: {episodes[start_ep_idx+1].title})"
            if start_ep_idx + 1 < len(episodes)
            else "No next episode"
        ),
        f"Watch again ({saved_ep_title})",
        "Cancel",
    ]
    choice = select_from_list(options, "What would you like to do?")

    if choice == 2:  # Cancel
        return
    elif choice == 0:  # Continue
        if start_ep_idx + 1 < len(episodes):
            start_ep_idx += 1
        else:
            print_warning("No next episode found.")
            pause()
            return

    # Start loop
    ep_idx = start_ep_idx

    # Create dummy series object for callback
    class SeriesDummy:
        def __init__(self, t):
            self.title = t

    series_dummy = SeriesDummy(data["series_title"])

    while True:
        selected_episode = episodes[ep_idx]

        success = play_episode_flow(
            provider_name="Anime-Sama",
            series_title=data["series_title"],
            season_title=season.title,
            episode=selected_episode,
            series_url=data["series_url"],
            season_url=data["season_url"],
            logo_url=data.get("logo_url"),
            headers={"Referer": anime_sama.website_origin},
            anilist_callback=lambda: _update_anilist_progress(
                series_dummy, season, selected_episode
            ),
        )

        if success:
            if ep_idx + 1 < len(episodes):
                next_ep = episodes[ep_idx + 1]
                choice = select_from_list(
                    ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                )
                if choice == 0:
                    ep_idx += 1
                    continue
            break
        else:
            return  # Back
