from ..scraping import french_stream, player
from ..scraping.objects import FrenchStreamMovie, FrenchStreamSeason
from ..cli_utils import (
    clear_screen,
    select_from_list,
    select_with_preview,
    make_preview,
    print_info,
    print_warning,
    get_user_input,
    pause,
    skeleton,
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
    """Handle French-Stream provider flow.

    Back stack : results ← languages ← episodes ← players, one level per Esc.
    """
    last_query = ""
    while True:  # ── Search level ──
        clear_screen()  # each new search starts clean
        query = get_user_input(
            t("Search query (or 'exit' to back)"),
            default=last_query or None,
            header=f"{icon('flag_fr')} French-Stream",
            history=tracker.get_search_history(),
        )
        if not query or query.lower() == "exit":
            return
        last_query = query
        tracker.add_search_query(query)

        with skeleton(f"{t('Searching for')} {query}…"):
            results = french_stream.search(query)

        if not results:
            print_warning(t("No results found."))
            print_info(t("French-Stream may be unreachable or blocking the request."))
            pause()
            continue

        previews = [
            make_preview(
                cover=getattr(r, "img", ""),
                title=r.title,
                lines=[", ".join(getattr(r, "genres", []) or [])],
                panel_title="French-Stream",
            )
            for r in results
        ]

        while True:  # ── Results level ──
            choice_idx = select_with_preview(
                [r.title for r in results],
                f"{icon('tv')} {t('Search Results:')}", previews,
            )
            if choice_idx >= len(results):
                break  # → search input
            selection = results[choice_idx]

            try:
                with spinner(f"{t('Loading')} {selection.title}…"):
                    content = french_stream.get_content(selection.url)
            except Exception:
                print_warning(t("Failed to load (network/source issue)."))
                pause()
                continue

            from .. import terminal_image
            terminal_image.show_poster(
                getattr(content, "img", "") or getattr(selection, "img", ""),
                info_lines=[", ".join(getattr(selection, "genres", []) or [])],
            )

            if isinstance(content, FrenchStreamMovie):
                if not content.players:
                    print_warning(t("No players found."))
                    pause()
                    continue
                if not [p for p in content.players if player.is_supported(p.url)]:
                    print_warning(t("No supported players found."))
                    pause()
                    continue
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
                continue  # Back from players → results

            # ── Series ──
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
                    continue  # → results

            langs = list(content.episodes.keys())
            if not langs:
                print_warning(t("No episodes found."))
                pause()
                continue

            while True:  # ── Language level ──
                if len(langs) == 1:
                    lang = langs[0]
                else:
                    l_idx = select_from_list(
                        langs + [t("← Back")],
                        f"{icon('globe')} {t('Select Language:')}",
                    )
                    if l_idx >= len(langs):
                        break  # → results
                    lang = langs[l_idx]
                episodes = content.episodes[lang]
                ep_idx = 0

                while True:  # ── Episodes level ──
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
                        preferred = _pick_player_for_batch(
                            episodes, {"Referer": french_stream.website_origin}
                        )
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
                        break  # → language (or results when single)

                    play_episode_flow(
                        provider_name="French-Stream",
                        series_title=content.title,
                        season_title=content.title,
                        series_url=content.url,
                        season_url=content.url,
                        headers={"Referer": french_stream.website_origin},
                        episode=episodes[ep_idx],
                    )
                    # Back from players → episodes list again.

                if len(langs) == 1:
                    break  # → results


def resume_french_stream(data):
    """Resume French-Stream playback."""
    print_info(f"{t('Resuming')} [cyan]{data['series_title']}[/cyan]...")

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
            l_idx = select_from_list(
                langs + [t("← Back")], t("🌍 Select Language:")
            )
            if l_idx >= len(langs):
                return  # → history list
            lang = langs[l_idx]

        episodes = content.episodes[lang]

        start_ep_idx = 0
        for i, ep in enumerate(episodes):
            if ep.title == data["episode_title"]:
                start_ep_idx = i
                break

        options = [
            (
                f"{t('Continue')} ({t('Next:')} {episodes[start_ep_idx+1].title})"
                if start_ep_idx + 1 < len(episodes)
                else t("No next episode")
            ),
            f"{t('Watch again')} ({data['episode_title']})",
            t("Cancel"),
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
