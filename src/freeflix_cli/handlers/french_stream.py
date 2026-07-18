from ..scraping import french_stream, player
from ..scraping.objects import FrenchStreamMovie, FrenchStreamSeason
from ..cli_utils import (
    select_from_list,
    select_with_preview,
    make_preview,
    print_info,
    print_warning,
    get_user_input,
    console,
    pause,
    spinner,
    crumb,
)
from ..tracker import tracker
from ..icons import icon
from ..i18n import t
from .playback import play_episode_flow, download_episodes_batch, _pick_player_for_batch
from ..player_manager import episode_badges


def resolve_url(url, base):
    """Helper to resolve partial URLs."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return base.rstrip("/") + "/" + url.lstrip("/")


def handle_french_stream():
    """Handle French-Stream provider flow."""
    query = get_user_input(
        t("Search query (or 'exit' to back)"),
        header=f"{icon('flag_fr')} French-Stream",
        history=tracker.get_search_history(),
    )
    if query and query.lower() != "exit":
        tracker.add_search_query(query)
    if not query or query.lower() == "exit":
        return

    with spinner(f"{t('Searching for')} {query}…"):
        results = french_stream.search(query)

    if not results:
        print_warning(t("No results found."))
        print_info(t("French-Stream may be unreachable or blocking the request."))
        pause()
        return

    # Preview pane : poster + genres beside the result list (type to filter).
    previews = [
        make_preview(
            cover=getattr(r, "img", ""),
            title=r.title,
            lines=[", ".join(getattr(r, "genres", []) or [])],
            panel_title="French-Stream",
        )
        for r in results
    ]
    choice_idx = select_with_preview(
        [r.title for r in results], f"{icon('tv')} {t('Search Results:')}", previews
    )
    if choice_idx >= len(results):  # Esc / Back
        return
    selection = results[choice_idx]

    with spinner(f"Loading {selection.title}…"):
        content = french_stream.get_content(selection.url)

    # Poster at selection (movie thumbnail, or the search-result image).
    from .. import terminal_image
    terminal_image.show_poster(
        getattr(content, "img", "") or getattr(selection, "img", ""),
        title=getattr(content, "title", selection.title),
        info_lines=[", ".join(getattr(selection, "genres", []) or [])],
    )

    if isinstance(content, FrenchStreamMovie):
        console.print(f"\n[bold]{icon('movie')} Movie:[/bold] [cyan]{content.title}[/cyan]")
        if not content.players:
            print_warning(t("No players found."))
            pause()
            return
        supported_players = [p for p in content.players if player.is_supported(p.url)]
        if not supported_players:
            print_warning(t("No supported players found."))
            pause()
            return

        success = play_episode_flow(
            provider_name="French-Stream",
            series_title=content.title,
            season_title="Movie",
            series_url=content.url,
            season_url=content.url,
            logo_url=content.img,
            headers={"Referer": french_stream.website_origin},
            episode=content,
        )

    elif isinstance(content, FrenchStreamSeason):
        console.print(f"\n[bold]{icon('tv')} Series:[/bold] [cyan]{content.title}[/cyan]")

        # Check for saved progress
        saved_progress = tracker.get_series_progress("French-Stream", content.title)
        if saved_progress:
            choice = select_from_list(
                [
                    f"{t('Resume')} {saved_progress['season_title']} - {saved_progress['episode_title']}",
                    t("Browse Episodes"),
                ],
                f"{t('Found saved progress for')} {content.title} :",
            )
            if choice == 0:
                resume_french_stream(saved_progress)
                return

        # episodes is dict {lang: [Episode]}
        langs = list(content.episodes.keys())
        if not langs:
            print_warning(t("No episodes found."))
            pause()
            return

        while True:  # ── Language ──
            if len(langs) == 1:
                lang = langs[0]
            else:
                l_idx = select_from_list(
                    langs + [t("← Back")], f"{icon('globe')} {t('Select Language:')}"
                )
                if l_idx >= len(langs):
                    return  # back → source menu
                lang = langs[l_idx]
            episodes = content.episodes[lang]

            ep_idx = 0
            while True:  # ── Episode ──
                with crumb(content.title), crumb(lang):
                    ep_labels = [
                        e.title + episode_badges(content.title, content.title, e.title)
                        for e in episodes
                    ]
                    ep_idx = select_from_list(
                        ep_labels + [f"{icon('download')} {t('Download')}", t("← Back")],
                        f"{icon('tv')} {t('Select Episode:')}",
                        default_index=min(ep_idx, len(episodes) - 1),
                    )
                if ep_idx == len(episodes):  # Download ALL
                    preferred = _pick_player_for_batch(episodes, {"Referer": french_stream.website_origin})
                    if preferred is None:
                        continue
                    download_episodes_batch(
                        provider_name="French-Stream",
                        series_title=content.title,
                        season_title=content.title,
                        episodes=episodes,
                        series_url=content.url,
                        season_url=content.url,
                        logo_url=getattr(content, "img", None),
                        headers={"Referer": french_stream.website_origin},
                        preferred_player=preferred,
                    )
                    continue
                if ep_idx > len(episodes):
                    break  # back to the language picker

                while True:  # ── Play (with next-episode chaining) ──
                    selected_episode = episodes[ep_idx]
                    if not selected_episode.players:
                        print_warning(t("No players found for this episode."))
                        pause()
                        break
                    supported = [
                        p for p in selected_episode.players if player.is_supported(p.url)
                    ]
                    if not supported:
                        print_warning(t("No supported players found."))
                        pause()
                        break
                    success = play_episode_flow(
                        provider_name="French-Stream",
                        series_title=content.title,
                        season_title=content.title,
                        series_url=content.url,
                        season_url=content.url,
                        headers={"Referer": french_stream.website_origin},
                        episode=selected_episode,
                    )
                    if success and ep_idx + 1 < len(episodes) and (
                        select_from_list(
                            [t("Yes"), t("No")],
                            f"{t('Play next episode:')} {episodes[ep_idx + 1].title}?",
                        ) == 0
                    ):
                        ep_idx += 1
                        continue
                    break
                # back to the episode picker

            if len(langs) == 1:
                return  # single language → back exits the handler


def resume_french_stream(data):
    """Resume French-Stream playback."""
    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    data["series_url"] = resolve_url(data["series_url"], french_stream.website_origin)
    data["season_url"] = resolve_url(data["season_url"], french_stream.website_origin)
    if "episode_url" in data:
        data["episode_url"] = resolve_url(
            data["episode_url"], french_stream.website_origin
        )

    # We load content from SERIES URL (or movie url)
    content = french_stream.get_content(data["series_url"])

    if isinstance(content, FrenchStreamMovie):
        if not content.players:
            return
        # Movie Resume
        if not content.players:
            return

        play_episode_flow(
            provider_name="French-Stream",
            series_title=content.title,
            season_title="Movie",
            series_url=content.url,
            season_url=content.url,
            logo_url=content.img,
            headers={"Referer": french_stream.website_origin},
            episode=content,
        )
        return

    elif isinstance(content, FrenchStreamSeason):
        langs = list(content.episodes.keys())
        if not langs:
            return

        # Ask language (simple assumption: user knows which lang they watched, or we could save it)
        if len(langs) == 1:
            lang = langs[0]
        else:
            lang = langs[select_from_list(langs, "🌍 Select Language:")]

        episodes = content.episodes[lang]

        start_ep_idx = 0
        for i, ep in enumerate(episodes):
            if ep.title == data["episode_title"]:
                start_ep_idx = i
                break

        options = [
            (
                f"Continue (Next: {episodes[start_ep_idx+1].title})"
                if start_ep_idx + 1 < len(episodes)
                else "No next episode"
            ),
            f"Watch again ({data['episode_title']})",
            "Cancel",
        ]
        choice = select_from_list(options, t("What would you like to do?"))
        if choice == 2:
            return
        elif choice == 0:
            if start_ep_idx + 1 < len(episodes):
                start_ep_idx += 1
            else:
                return

        ep_idx = start_ep_idx
        while True:
            selected_episode = episodes[ep_idx]
            if not selected_episode.players:
                return

            success = play_episode_flow(
                provider_name="French-Stream",
                series_title=content.title,
                season_title=content.title,
                series_url=content.url,
                season_url=content.url,
                headers={"Referer": french_stream.website_origin},
                episode=selected_episode,
            )

            if success:
                if ep_idx + 1 < len(episodes):
                    if (
                        select_from_list(
                            [t("Yes"), t("No")], f"{t('Play next:')} {episodes[ep_idx+1].title} ?"
                        )
                        == 0
                    ):
                        ep_idx += 1
                        continue
            break
