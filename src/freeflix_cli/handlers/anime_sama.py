from ..scraping import anime_sama
from ..cli_utils import (
    clear_screen,
    select_from_list,
    select_with_preview,
    make_preview,
    print_info,
    print_warning,
    print_success,
    print_error,
    get_user_input,
    pause,
    plural,
    skeleton,
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
                        f"{t('Linked to')} {results[m_idx]['title']['english'] or results[m_idx]['title']['romaji']}!"
                    )
            else:
                print_warning(t("No matches found on AniList."))

    if media_id:
        # Update progress with overflow detection
        print_info(f"{t('Updating AniList to episode')} {episode_num}...")
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
                f"{t('Episode')} {episode_num} {t('exceeds max episodes')} ({total_eps}) {t('for this AniList entry.')}"
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
                print_info(f"{t('Found sequel:')} [cyan]{sequel_title}[/cyan]")

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
                        f"{t('Updating mapping to use episode')} {new_ep_num} {t('on new entry...')}"
                    )
                    tracker.set_anilist_mapping(
                        "Anime-Sama", series.title, sequel["id"], season.title
                    )
                    media_id = sequel["id"]
                    episode_num = new_ep_num

        if anilist_client.update_progress(media_id, episode_num):
            print_success(t("AniList updated!"))
        else:
            print_error(t("Failed to update AniList."))


def _planning_menu() -> None:
    """Anime-Sama → Planning / Recherche."""
    while True:
        choice = select_from_list(
            [
                f"{icon('calendar')} {t('Weekly planning')}",
                f"{icon('search')} {t('Search an anime')}",
                t("← Back"),
            ],
            f"{icon('anime')} Anime-Sama",
        )
        if choice == 0:
            handle_anime_sama_planning()
            continue
        if choice == 1:
            _search_flow()
            continue
        return


def handle_anime_sama_planning() -> None:
    """Live weekly planning: day → anime (poster preview) → series actions.

    The grid is fetched from Anime-Sama on every visit (5-minute cache), never
    hard-coded. Only animes are listed (scans/webtoons dropped), and each entry
    shows its day, hour and whether it is already out.
    """
    from ..scraping import anime_sama_planning as planning

    anime_sama.get_website_url()
    lang = tracker.get_anime_language() or ""
    try:
        with spinner(t("Loading the planning…")):
            entries = planning.get_planning()
    except Exception as e:
        print_error(f"{t('Planning unavailable:')} {type(e).__name__}")
        print_info(t("The source may be down or rate-limiting — try again in a moment."))
        pause()
        return

    if lang in ("vostfr", "vf"):
        filtered = [e for e in entries if not e.lang or e.lang == lang.upper()]
        entries = filtered or entries
    if not entries:
        print_warning(t("No anime in the planning right now."))
        pause()
        return

    groups = planning.group_by_day(entries)
    start = planning.today_index(entries)
    while True:  # ── Day level ──
        day_labels = []
        for day, date_label, items in groups:
            out = sum(1 for e in items if e.released)
            day_labels.append(
                f"{icon('calendar')} {day} {date_label}  "
                f"[{t('out')} {out}/{len(items)}]"
            )
        day_labels.append(t("← Back"))
        day_idx = select_from_list(
            day_labels,
            f"{icon('calendar')} {t('Planning of the moment')}",
            default_index=start,
        )
        if day_idx >= len(groups):
            return
        start = day_idx
        day, date_label, items = groups[day_idx]

        # The day's posters are already on disk (persistent cache) → previews
        # are instant; missing ones are fetched in parallel.
        try:
            from .. import terminal_image as _ti
            _ti.prefetch_many([e.img for e in items])
        except Exception:
            pass

        while True:  # ── Entry level (poster preview) ──
            previews = [
                make_preview(
                    cover=e.img,
                    title=e.title,
                    lines=[
                        f"{icon('calendar')} {e.when_label}",
                        (
                            f"{icon('check')} {t('Released')}"
                            if e.released
                            else f"{icon('hourglass')} {t('Not yet released')}"
                        ),
                        e.lang,
                    ],
                    panel_title=f"Anime-Sama · {day} {date_label}",
                )
                for e in items
            ]
            labels = [
                f"{icon('check') if e.released else icon('clock')} "
                + f"{e.hour_label + ' · ' if e.has_hour else ''}"
                + e.title + (f"  [{e.lang}]" if e.lang else "")
                for e in items
            ]
            with crumb(f"{icon('anime')} Anime-Sama", day, date_label):
                idx = select_with_preview(
                    labels, f"{icon('calendar')} {day} {date_label}", previews
                )
            if idx >= len(items):
                break  # → day list
            # Coming back from an anime: before drawing the LIST again, check
            # whether the site swapped a poster. The cached file is then
            # refreshed and the list redrawn once with the new art.
            _planning_entry_actions(items[idx], day, date_label)
            changed = _changed_covers(items)
            if changed:
                try:
                    from .. import terminal_image as _ti
                    for img in changed:
                        _ti.refresh_cover(img)
                except Exception:
                    pass


def _cover_versions(items) -> tuple:
    """Poster fingerprints for the current day (detects updated covers)."""
    return tuple(_cover_version(e.img) for e in items)


def _cover_version(img: str):
    try:
        from .. import terminal_image
        return terminal_image.cover_version(img)
    except Exception:
        return None


def _changed_covers(items) -> list:
    """Posters the site replaced since they were cached (re-download later)."""
    try:
        from .. import terminal_image
    except Exception:
        return []
    out = []
    for e in items:
        try:
            if terminal_image.cover_changed(e.img):
                out.append(e.img)
        except Exception:
            continue
    return out


def _planning_entry_actions(entry, day, date_label) -> None:
    """Pick what to do with one planned anime."""
    state = (
        f"{icon('check')} {t('Released')}" if entry.released
        else f"{icon('hourglass')} {t('Not yet released')}"
    )
    print_info(
        f"[bold cyan]{entry.title}[/bold cyan]  "
        f"[dim]{day} {date_label} · {entry.hour_label} · {state}[/dim]"
    )
    choice = select_from_list(
        [
            f"{icon('play')} {t('Follow the latest released episode')}",
            f"{icon('list')} {t('Browse seasons')}",
            t("← Back"),
        ],
        entry.title,
    )
    if choice >= 2:
        return
    try:
        with spinner(f"{t('Loading')} {entry.title}…"):
            series = anime_sama.get_series(entry.url)
    except Exception as e:
        print_error(f"{t('Failed to load (network/source issue):')} {type(e).__name__}")
        pause()
        return
    if not series.seasons:
        print_warning(t("No seasons found."))
        pause()
        return
    if choice == 0:
        _follow_latest_episode(series)
    else:
        _anime_sama_series_flow(series)


def _follow_latest_episode(series) -> None:
    """Open the newest season at its last released episode (with sync check).

    The planning announces a release at an hour, but the episode file can
    land a few minutes later: we verify the newest season actually has
    episodes, warn when it doesn't yet, and fall back to the previous season
    that does.
    """
    ordered = list(reversed(series.seasons))
    for season_access in ordered:
        try:
            with spinner(f"{t('Loading')} {season_access.title}…"):
                season = anime_sama.get_season(season_access.url)
        except Exception:
            continue
        langs = list(season.episodes.keys())
        if not langs:
            continue
        if tracker.get_anime_language() in langs:
            lang = tracker.get_anime_language()
        else:
            lang = langs[0]
        episodes = season.episodes.get(lang) or []
        if not episodes:
            continue
        if season_access is ordered[0] and len(ordered) > 1:
            # Newest season is announced but still empty → be explicit.
            print_info(t("The announced episode isn't online yet."))
        ep = episodes[-1]
        play_episode_flow(
            provider_name="Anime-Sama",
            series_title=series.title,
            season_title=season.title,
            episode=ep,
            series_url=series.url,
            season_url=season_access.url,
            logo_url=series.img,
            headers={"Referer": anime_sama.website_origin},
            genres=getattr(series, "genres", None),
            anilist_callback=lambda _se=season, _ep=ep:
                _update_anilist_progress(series, _se, _ep),
        )
        return
    print_warning(t("No episodes found."))
    pause()


def handle_anime_sama():
    """Handle Anime-Sama provider flow.

    First menu: weekly planning or classic search. Navigation is a strict
    stack (one Back = one level up, state kept): search → results → seasons
    → episodes → players. Backing out of a series shows the SAME results
    again (no refetch); backing out of the results returns to the search
    prompt (pre-filled), and Esc there leaves the source.
    """
    _planning_menu()


def _search_flow():
    anime_sama.get_website_url()

    last_query = ""
    while True:  # ── Search level ──
        clear_screen()  # each new search starts clean
        query = get_user_input(
            t("Search query (or 'exit' to back)"),
            default=last_query or None,
            header=f"{icon('anime')} Anime-Sama",
            history=tracker.get_search_history(),
        )
        if not query or query.lower() == "exit":
            return
        last_query = query
        tracker.add_search_query(query)

        try:
            with skeleton(f"{t('Searching for')} {query}…"):
                results = anime_sama.search(query)
        except Exception as e:
            print_error(f"{t('Search failed (network/source issue):')} {type(e).__name__}")
            print_info(t("The source may be down or rate-limiting — try again in a moment."))
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
                lines=[", ".join(r.genres)] if r.genres else [],
                panel_title="Anime-Sama",
            )
            for r in results
        ]
        labels = [r.title for r in results]

        while True:  # ── Results level ──
            choice_idx = select_with_preview(
                labels, f"{icon('tv')} {t('Search Results:')}", previews
            )
            if choice_idx >= len(results):  # Esc / Back → search prompt
                break
            selection = results[choice_idx]

            try:
                with spinner(f"{t('Loading')} {selection.title}…"):
                    series = anime_sama.get_series(selection.url)
            except Exception as e:
                print_error(f"{t('Failed to load (network/source issue):')} {type(e).__name__}")
                print_info(t("The source may be down or rate-limiting — try again in a moment."))
                pause()
                continue

            if not series.seasons:
                print_warning(t("No seasons found."))
                pause()
                continue

            # Anime poster + summary at selection.
            from .. import terminal_image
            terminal_image.show_poster(
                getattr(series, "img", ""),
                # Title already printed by the selection menu just above.
                info_lines=[
                    f"{len(series.seasons)} {plural(len(series.seasons), 'season', 'seasons')}",
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
                    continue  # back to the same results list

            _anime_sama_series_flow(series)
            continue  # Back at seasons (or finished) → results again


def _anime_sama_series_flow(series) -> bool:
    """Season → language → episode → player flow for one series.

    Returns True when the user is done with the series (so the caller shows
    the results again), False when Back was pressed at the SEASON level.
    Every deeper Back goes exactly one level up."""
    back = t("← Back")
    while True:  # ── Season ──
        with crumb(series.title):
            season_idx = select_from_list(
                [s.title for s in series.seasons] + [back],
                f"{icon('tv')} {t('Select Season:')}",
            )
        if season_idx >= len(series.seasons):
            return False  # back to results

        selected_season_access = series.seasons[season_idx]
        print_info(f"{t('Loading')} [cyan]{selected_season_access.title}[/cyan]…")
        try:
            season = anime_sama.get_season(selected_season_access.url)
        except Exception as e:
            print_error(f"{t('Failed to load season (network/source issue):')} {type(e).__name__}")
            print_info(t("The source may be down or rate-limiting — try again in a moment."))
            pause()
            continue  # back to season picker

        langs = list(season.episodes.keys())
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
                        langs + [back], f"{icon('globe')} {t('Select Language:')}",
                        clear_on_back=False,  # stay inside the series view
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
                        clear_on_back=False,  # stay inside the series view
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
                    if ep_idx + 1 < len(episodes):
                        from ..player_manager import last_playback_finished_naturally
                        from ..cli_utils import confirm_or_timeout
                        nxt = episodes[ep_idx + 1].title
                        if last_playback_finished_naturally():
                            go = confirm_or_timeout(
                                f"{t('Next episode')}: {nxt}", seconds=6, default=True)
                        else:
                            go = select_from_list(
                                [t("Yes"), t("No")],
                                f"{t('Play next episode:')} {nxt}?") == 0
                        if go:
                            ep_idx += 1
                            continue
                    break  # declined, or no next → back to episode picker

            if len(langs) == 1:
                break  # single language → step back to the season picker


def resume_anime_sama(data):
    """Resume Anime-Sama playback."""
    print_info(f"{t('Resuming')} [cyan]{data['series_title']}[/cyan]...")

    # We need to reload just the season to find the episode link/player
    # We have season_url saved.
    anime_sama.get_website_url()

    # Re-fetch season
    season_url = data["season_url"]
    if season_url.startswith("/") or not season_url.startswith("http"):
        season_url = anime_sama.website_origin.rstrip("/") + season_url

    print_info(f"{t('Loading Season:')} {season_url}")
    try:
        season = anime_sama.get_season(season_url)
    except Exception as e:
        print_error(f"{t('Could not load season:')} {e}")
        return

    langs = list(season.episodes.keys())
    if not langs:
        return

    # If only one language, pick it. If multiple, ask.
    if len(langs) == 1:
        selected_lang = langs[0]
    else:
        lang_idx = select_from_list(
            langs + [t("← Back")], t("🌍 Select Language:")
        )
        if lang_idx >= len(langs):
            return  # → history list
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
            f"{t('Continue')} ({t('Next:')} {episodes[start_ep_idx+1].title})"
            if start_ep_idx + 1 < len(episodes)
            else t("No next episode")
        ),
        f"{t('Watch again')} ({saved_ep_title})",
        t("Cancel"),
    ]
    choice = select_from_list(options, t("What would you like to do?"))

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
                    [t("Yes"), t("No")], f"{t('Play next episode:')} {next_ep.title}?"
                )
                if choice == 0:
                    ep_idx += 1
                    continue
            break
        else:
            return  # Back
