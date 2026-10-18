from ..scraping import coflix, player
from ..scraping.objects import CoflixMovie, CoflixSeries
import re as _re
from ..cli_utils import (
    clear_screen,
    select_from_list,
    select_with_preview,
    make_preview,
    print_info,
    print_error,
    print_warning,
    get_user_input,
    pause,
    crumb,
)
from ..tracker import tracker
from ..icons import icon
from ..i18n import t
from .. import terminal_image
from .playback import play_episode_flow, download_episodes_batch, _pick_player_for_batch
from ..player_manager import episode_badges
from ..cli_utils import skeleton, spinner


def handle_coflix():
    """Handle Coflix provider flow."""
    coflix.get_website_url()

    while True:
        clear_screen()  # each new search starts clean
        query = get_user_input(
            t("Search query (or 'exit' to back)"),
            header=f"{icon('movie')} Coflix",
            history=tracker.get_search_history(),
        )
        if not query or query.lower() == "exit":
            break
        tracker.add_search_query(query)

        with skeleton(f"{t('Searching for')} {query}…"):
            try:
                results = coflix.search(query)
            except Exception as e:
                if "429" in str(e):
                    print_warning(
                        t("Coflix is rate-limiting / blocking searches right now "
                          "(HTTP 429). Wait a few minutes, or use another source.")
                    )
                else:
                    print_warning(f"{t('Search error:')} {e}")
                pause()
                continue

        if not results:
            print_warning(t("No results found."))
            pause()
            continue

        # Preview pane : poster + genres beside the result list (type to filter).
        previews = [
            make_preview(
                cover=getattr(r, "img", ""),
                title=r.title,
                lines=[", ".join(getattr(r, "genres", []) or [])],
                panel_title="Coflix",
            )
            for r in results
        ]
        while True:  # ── Results level ──
            choice_idx = select_with_preview(
                [r.title for r in results], f"{icon('tv')} {t('Search Results:')}", previews
            )

            if choice_idx >= len(results):  # Esc / Back
                break  # → search input

            selection = results[choice_idx]

            try:
                with spinner(f"{t('Loading')} {selection.title}…"):
                    content = coflix.get_content(selection.url)
            except Exception as e:
                print_error(f"{t('Error loading content:')} {e}")
                pause()
                continue

            # Poster + title at selection.
            terminal_image.show_poster(
                getattr(content, "img", "") or getattr(selection, "img", ""),
                info_lines=[", ".join(getattr(content, "genres", []) or [])],
            )

            if isinstance(content, CoflixMovie):
                # The selection menu already printed the title — no duplicate header.
                # Check for saved progress (Movie Resume Fix)
                saved_progress = tracker.get_series_progress("Coflix", content.title)
                if saved_progress:
                    choice = select_from_list(
                        [t("Watch again/Resume"), t("Cancel")],
                        f"{t('Found saved progress for')} {content.title} :",
                    )
                    if choice == 0:
                        resume_coflix(saved_progress)
                        continue

                if not content.players:
                    print_warning(t("No players found."))
                    pause()
                    continue
                supported_players = [
                    p for p in content.players if player.is_supported(p.url)
                ]
                if not supported_players:
                    print_warning(t("No supported players found."))
                    pause()
                    continue

                headers = {"Referer": "https://lecteurvideo.com/"}
                play_episode_flow(
                    provider_name="Coflix",
                    series_title=content.title,
                    season_title="Movie",
                    series_url=content.url,
                    season_url=content.url,
                    logo_url=content.img,
                    headers=headers,
                    episode=content,  # Movie object should behave like Episode if it has players
                )

            elif isinstance(content, CoflixSeries):
                if not content.seasons:
                    print_warning(t("No seasons found."))
                    pause()
                    continue

                # Check for saved progress for this specific series
                saved_progress = tracker.get_series_progress("Coflix", content.title)
                if saved_progress:
                    choice = select_from_list(
                        [
                            f"{t('Resume')} {saved_progress['season_title']} - {saved_progress['episode_title']}",
                            t("Browse Seasons"),
                        ],
                        f"{t('Found saved progress for')} {content.title} :",
                    )
                    if choice == 0:
                        resume_coflix(saved_progress)
                        continue

                while True:  # ── Season ──
                    with crumb(content.title):
                        season_idx = select_from_list(
                            [s.title for s in content.seasons] + [t("← Back")],
                            f"{icon('tv')} {t('Select Season:')}",
                        )
                    if season_idx >= len(content.seasons):
                        break  # back to the search prompt

                    selected_season_access = content.seasons[season_idx]
                    print_info(f"{t('Loading')} [cyan]{selected_season_access.title}[/cyan]...")
                    try:
                        season = coflix.get_season(selected_season_access.url)
                    except Exception as e:
                        print_error(f"{t('Error loading season:')} {e}")
                        pause()
                        continue  # back to the season picker
                    if not season.episodes:
                        print_warning(t("No episodes found."))
                        pause()
                        continue

                    while True:  # ── Episode ──
                        with crumb(content.title), crumb(season.title):
                            ep_labels = [
                                e.title + episode_badges(content.title, season.title, e.title)
                                for e in season.episodes
                            ]
                            ep_idx = select_from_list(
                                ep_labels + [f"{icon('download')} {t('Download')}", t("← Back")],
                                f"{icon('tv')} {t('Select Episode:')}",
                            )
                        if ep_idx == len(season.episodes):  # Download ALL
                            headers = {"Referer": "https://lecteurvideo.com/"}
                            with spinner(t("Preparing episodes for download…")):
                                full_episodes = []
                                for e in season.episodes:
                                    try:
                                        ep_details = coflix.get_episode(e.url)
                                        full_episodes.append(ep_details)
                                    except Exception:
                                        print_warning(f"{t('Could not load')} {e.title}, {t('skipping')}.")
                            preferred = _pick_player_for_batch(full_episodes, headers)
                            if preferred is None:
                                continue
                            download_episodes_batch(
                                provider_name="Coflix",
                                series_title=content.title,
                                season_title=selected_season_access.title,
                                episodes=full_episodes,
                                series_url=content.url,
                                season_url=selected_season_access.url,
                                logo_url=content.img,
                                headers=headers,
                                preferred_player=preferred,
                            )
                            continue
                        if ep_idx > len(season.episodes):
                            break  # back to the season picker

                        while True:  # ── Play (with next-episode chaining) ──
                            selected_episode = season.episodes[ep_idx]
                            headers = {"Referer": "https://lecteurvideo.com/"}
                            try:
                                ep_details = coflix.get_episode(selected_episode.url)
                            except Exception as e:
                                print_error(f"{t('Error loading episode:')} {e}")
                                pause()
                                break
                            success = play_episode_flow(
                                provider_name="Coflix",
                                series_title=content.title,
                                season_title=selected_season_access.title,
                                episode=ep_details,
                                series_url=content.url,
                                season_url=selected_season_access.url,
                                logo_url=content.img,
                                headers=headers,
                            )
                            if success and ep_idx + 1 < len(season.episodes) and (
                                select_from_list(
                                    [t("Yes"), t("No")],
                                    f"{t('Play next episode:')} {season.episodes[ep_idx + 1].title}?",
                                ) == 0
                            ):
                                ep_idx += 1
                                continue
                            break
                        # back to the episode picker


def resume_coflix(data):
    """Resume Coflix playback."""
    # Ensure origin is set so we can resolve relative URLs
    coflix.get_website_url()

    def resolve_url(u):
        if not u:
            return ""
        if u.startswith("http"):
            return u
        return coflix.website_origin.rstrip("/") + "/" + u.lstrip("/")

    # Resolve URLs in data
    data["series_url"] = resolve_url(data["series_url"])
    data["season_url"] = resolve_url(data["season_url"])

    print_info(f"{t('Resuming')} [cyan]{data['series_title']}[/cyan]...")

    # Handle Movie
    if data["season_title"] == "Movie":
        print_info(f"{t('Loading Movie:')} {data['series_url']}")
        try:
            content = coflix.get_content(data["series_url"])
        except Exception as e:
            print_error(f"{t('Could not load movie:')} {e}")
            pause()
            return

        if not isinstance(content, CoflixMovie):
            print_error(t("Expected a Movie but got something else."))
            pause()
            return

        options = [t("Watch again"), t("Cancel")]
        choice = select_from_list(options, t("What would you like to do?"))

        if choice == 1:
            return

        # Watch again
        headers = {"Referer": "https://lecteurvideo.com/"}
        play_episode_flow(
            provider_name="Coflix",
            series_title=content.title,
            season_title="Movie",
            series_url=content.url,
            season_url=content.url,
            logo_url=content.img,
            headers=headers,
            episode=content,
        )
        return

    # Handle Series (Existing Logic)
    print_info(f"{t('Loading Season:')} {data['season_url']}")
    try:
        season = coflix.get_season(data["season_url"])
    except Exception as e:
        print_error(f"{t('Could not load season:')} {e}")
        pause()
        return

    if not season.episodes:
        print_warning(t("No episodes found in season."))
        pause()
        return

    # Find episode index : exact title first, then by trailing episode number
    # (titles like "Épisode 5 VF" used to match the FIRST episode because only
    # the last whitespace token was compared).
    start_ep_idx = 0
    saved_ep_title = data["episode_title"]

    def _ep_num(title):
        nums = _re.findall(r"\d+", title or "")
        return nums[-1] if nums else None

    for i, ep in enumerate(season.episodes):
        if ep.title == saved_ep_title:
            start_ep_idx = i
            break
    else:
        target = _ep_num(saved_ep_title)
        if target is not None:
            for i, ep in enumerate(season.episodes):
                if _ep_num(ep.title) == target:
                    start_ep_idx = i
                    break

    options = [
        (
            f"{t('Continue')} ({t('Next:')} {season.episodes[start_ep_idx+1].title})"
            if start_ep_idx + 1 < len(season.episodes)
            else t("No next episode")
        ),
        f"{t('Watch again')} ({saved_ep_title})",
        t("Cancel"),
    ]
    choice = select_from_list(options, t("What would you like to do?"))

    if choice == 2:
        return
    elif choice == 0:
        if start_ep_idx + 1 < len(season.episodes):
            start_ep_idx += 1
        else:
            return

    ep_idx = start_ep_idx

    while True:
        selected_episode = season.episodes[ep_idx]
        headers = {"Referer": "https://lecteurvideo.com/"}

        try:
            ep_details = coflix.get_episode(selected_episode.url)
        except Exception as e:
            print_error(f"{t('Error loading episode:')} {e}")
            pause()
            break

        success = play_episode_flow(
            provider_name="Coflix",
            series_title=data["series_title"],
            season_title=data["season_title"],
            episode=ep_details,
            series_url=data["series_url"],
            season_url=data["season_url"],
            logo_url=data.get("logo_url"),
            headers=headers,
        )

        if success:
            playback_success = True
        else:
            return

        if playback_success:
            if ep_idx + 1 < len(season.episodes):
                if (
                    select_from_list(
                        [t("Yes"), t("No")],
                        f"{t('Play next:')} {season.episodes[ep_idx+1].title}?",
                    )
                    == 0
                ):
                    ep_idx += 1
                    continue
            break
