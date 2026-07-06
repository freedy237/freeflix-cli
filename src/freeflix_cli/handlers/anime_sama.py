from ..scraping import anime_sama
from ..cli_utils import (
    select_from_list,
    select_with_preview,
    make_preview,
    print_info,
    print_warning,
    print_success,
    print_error,
    get_user_input,
    pause,
    spinner,
    crumb,
)
from ..tracker import tracker
from ..anilist import anilist_client
from ..i18n import t
from ..icons import icon
from .playback import play_episode_flow, download_episodes_batch, _pick_player_for_batch
from ..player_manager import episode_badges
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
            [t("Yes"), t("No")],
            f"{t('Link to AniList for auto-tracking?')} ({series.title})",
        )
        if link_choice == 0:
            results = anilist_client.search_media(series.title)
            if results:
                media_options = [
                    f"{m['title']['english'] or m['title']['romaji']} ({m['seasonYear']})"
                    for m in results
                ] + [t("Cancel")]
                m_idx = select_from_list(media_options, t("Select AniList Match:"))
                if m_idx < len(results):
                    media_id = results[m_idx]["id"]
                    tracker.set_anilist_mapping(
                        "Anime-Sama", series.title, media_id, season.title
                    )
                    print_success(
                        f"Linked to {results[m_idx]['title']['english'] or results[m_idx]['title']['romaji']}!"
                    )
            else:
                print_warning(t("No matches found on AniList."))

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
                        [t("Yes"), t("No")],
                        f"{t('Switch AniList mapping to sequel')} '{sequel_title}' ?",
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
            print_error(t("Failed to update AniList."))


def handle_anime_sama():
    """Handle Anime-Sama provider flow."""
    anime_sama.get_website_url()

    query = get_user_input(
        t("Search query (or 'exit' to back)"),
        header=f"{icon('anime')} Anime-Sama",
        history=tracker.get_search_history(),
    )
    if query and query.lower() != "exit":
        tracker.add_search_query(query)
    if not query or query.lower() == "exit":
        return

    try:
        with spinner(f"{t('Searching for')} {query}…"):
            results = anime_sama.search(query)
    except Exception as e:
        print_error(f"Search failed (network/source issue): {type(e).__name__}")
        print_info(t("The source may be down or rate-limiting — try again in a moment."))
        pause()
        return

    if not results:
        print_warning(t("No results found."))
        pause()
        return

    # Preview pane : poster + genres beside the result list (type to filter).
    previews = [
        make_preview(
            cover=getattr(r, "img", ""),
            title=r.title,
            lines=[", ".join(r.genres)] if r.genres else [],
            panel_title="Anime-Sama",
        )
        for r in results
    ]
    labels = [r.title for r in results]
    choice_idx = select_with_preview(
        labels, f"{icon('tv')} {t('Search Results:')}", previews
    )
    if choice_idx >= len(results):  # Esc / Back
        return
    selection = results[choice_idx]

    try:
        with spinner(f"{t('Loading')} {selection.title}…"):
            series = anime_sama.get_series(selection.url)
    except Exception as e:
        print_error(f"Failed to load (network/source issue): {type(e).__name__}")
        print_info(t("The source may be down or rate-limiting — try again in a moment."))
        pause()
        return

    if not series.seasons:
        print_warning(t("No seasons found."))
        pause()
        return

    # Anime poster + summary at selection.
    from .. import terminal_image
    terminal_image.show_poster(
        getattr(series, "img", ""),
        title=series.title,
        info_lines=[
            f"{len(series.seasons)} {t('season(s)')}",
            ", ".join(getattr(series, "genres", []) or []),
        ],
    )

    # Check for saved progress for this specific series
    saved_progress = tracker.get_series_progress("Anime-Sama", series.title)
    if saved_progress:
        choice = select_from_list(
            [
                f"{t('Resume')} {saved_progress['season_title']} - {saved_progress['episode_title']}",
                t("Browse Seasons"),
            ],
            f"{t('Found saved progress for')} {series.title} :",
        )
        if choice == 0:
            resume_anime_sama(saved_progress)
            return

    # Season → Language → Episode, each level with a Back option that steps
    # UP one level (Back at the season picker leaves the series entirely).
    back = t("← Back")
    while True:  # ── Season ──
        with crumb(series.title):
            season_idx = select_from_list(
                [s.title for s in series.seasons] + [back],
                f"{icon('tv')} {t('Select Season:')}",
            )
        if season_idx >= len(series.seasons):
            return  # leave the series → back to source menu

        selected_season_access = series.seasons[season_idx]
        print_info(f"{t('Loading')} [cyan]{selected_season_access.title}[/cyan]…")
        try:
            season = anime_sama.get_season(selected_season_access.url)
        except Exception as e:
            print_error(f"Failed to load season (network/source issue): {type(e).__name__}")
            print_info(t("The source may be down or rate-limiting — try again in a moment."))
            pause()
            continue  # back to season picker

        langs = list(season.episodes.keys())  # {lang: [Episode]}
        if not langs:
            print_warning(t("No episodes found."))
            pause()
            continue

        while True:  # ── Language ──
            if len(langs) == 1:
                selected_lang = langs[0]
            else:
                with crumb(series.title), crumb(season.title):
                    lang_idx = select_from_list(
                        langs + [back], f"{icon('globe')} {t('Select Language:')}"
                    )
                if lang_idx >= len(langs):
                    break  # back to season picker
                selected_lang = langs[lang_idx]
            episodes = season.episodes[selected_lang]

            ep_idx = 0
            while True:  # ── Episode ──
                with crumb(series.title), crumb(season.title), crumb(selected_lang):
                    ep_labels = [
                        e.title + episode_badges(series.title, season.title, e.title)
                        for e in episodes
                    ]
                    ep_idx = select_from_list(
                        ep_labels + [f"{icon('download')} {t('Download')}", back],
                        f"{icon('tv')} {t('Select Episode:')}",
                        default_index=min(ep_idx, len(episodes) - 1),
                    )
                if ep_idx == len(episodes):  # Download ALL
                    preferred = _pick_player_for_batch(episodes, {"Referer": anime_sama.website_origin})
                    if preferred is None:
                        continue
                    download_episodes_batch(
                        provider_name="Anime-Sama",
                        series_title=series.title,
                        season_title=season.title,
                        episodes=episodes,
                        series_url=series.url,
                        season_url=selected_season_access.url,
                        logo_url=series.img,
                        headers={"Referer": anime_sama.website_origin},
                        preferred_player=preferred,
                    )
                    continue
                if ep_idx > len(episodes):
                    break  # back to language picker

                # ── Play (with next-episode chaining) ──
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
                        anilist_callback=lambda _se=season, _ep=selected_episode:
                            _update_anilist_progress(series, _se, _ep),
                        genres=getattr(series, "genres", None),
                    )
                    if not success:
                        break  # play returned Back → episode picker
                    if ep_idx + 1 < len(episodes) and select_from_list(
                        [t("Yes"), t("No")],
                        f"{t('Play next episode:')} {episodes[ep_idx + 1].title}?",
                    ) == 0:
                        ep_idx += 1
                        continue
                    break  # done watching → episode picker
                # loop back to the episode picker

            # Back out of the episode picker :
            if len(langs) == 1:
                break  # single language → step back to the season picker
            # else: re-show the language picker


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
            print_warning(t("No next episode found."))
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
            anilist_callback=lambda _ep=selected_episode:
                _update_anilist_progress(series_dummy, season, _ep),
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
