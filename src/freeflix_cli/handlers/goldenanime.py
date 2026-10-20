from ..scraping.goldenanime import goldenanime
from ..scraping.subtitles import subtitle_extractor
from ..cli_utils import (
    clear_screen,
    select_from_list,
    plural,
    select_with_preview,
    crumb,
    make_preview,
    print_info,
    print_warning,
    print_success,
    get_user_input,
    pause,
    spinner,
)
from ..player_manager import play_video, analyze_stream_quality, format_quality_label
from ..tracker import tracker
from ..icons import icon
from ..i18n import t
from ..scraping.utils import clean_text
from ..languages import get_language_label
from ..anilist import anilist_client
from ..scraping import player as player_scraper

from curl_cffi import requests
import re


def _cover(media: dict) -> str:
    """Best AniList cover URL: extraLarge (sharpest) → large → medium. AniList
    file names differ per size, so the URL can't be upgraded after the fact —
    we must pick the big one here (the GraphQL query now fetches extraLarge)."""
    ci = (media or {}).get("coverImage") or {}
    return ci.get("extraLarge") or ci.get("large") or ci.get("medium") or ""


def search_imdb_id(title: str):
    import urllib.parse

    try:
        url_series = f"https://v3-cinemeta.strem.io/catalog/series/top/search={urllib.parse.quote(title)}.json"
        r_series = requests.get(url_series, timeout=5, impersonate="chrome").json()
        metas = r_series.get("metas", [])

        url_movie = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={urllib.parse.quote(title)}.json"
        r_movie = requests.get(url_movie, timeout=5, impersonate="chrome").json()
        metas.extend(r_movie.get("metas", []))

        if metas:
            choices = []
            valid_metas = []
            for m in metas[:7]:  # Top 7 results
                name = m.get("name")
                year = m.get("year", t("Unknown"))
                m_type = m.get("type", "series")
                imdb = m.get("imdb_id")
                if imdb:
                    choices.append(f"{name} ({year}) - {m_type}")
                    valid_metas.append(m)

            if valid_metas:
                choices.append(t("Enter manually"))
                choices.append(t("Skip Subtitles"))

                idx = select_from_list(choices, f"{t('Select IMDB match for')} '{title}':")
                if idx < len(valid_metas):
                    selected = valid_metas[idx]
                    return selected["imdb_id"], selected["type"] == "movie"
                elif idx == len(valid_metas):
                    manual = get_user_input(t("Enter IMDB ID manually (e.g. tt0388629)"))
                    return manual, False
                else:
                    return None, False
    except Exception as e:
        print_warning(f"{t('Auto IMDB search failed:')} {e}")

    manual = get_user_input(
        t("Enter IMDB ID manually (e.g. tt0388629, leave blank to skip)")
    )
    return manual, False


def handle_goldenanime():
    """Handle GoldenAnime provider flow.

    Back stack : results ← episodes ← streams, one level per Esc.
    (Also fixes an old crash: searching by AniList ID never initialised
    ``results``.)
    """
    mode = select_from_list(
        [f"{icon('new')} {t('Latest uploads')}",
         f"{icon('search')} {t('Search by title')}", t("← Back")],
        f"{icon('sparkle')} GoldenAnime (VO)",
    )
    if mode == 2:
        return
    from_latest = (mode == 0)
    last_query = ""

    while True:  # ── Search level ──
        clear_screen()  # each new search starts clean
        if from_latest:
            query = ""
        else:
            query = get_user_input(
                t("Search query (Title or AniList ID) (or 'exit' to back)"),
                default=last_query or None,
                header=f"{icon('sparkle')} GoldenAnime (VO)",
                history=tracker.get_search_history(),
            )
            if query and not query.isdigit() and query.lower() != "exit":
                tracker.add_search_query(query)
            if not query or query.lower() == "exit":
                return
            last_query = query

        results = []
        if query.isdigit():
            anilist_id = int(query)
            print_info(f"{t('Fetching AniList data for ID:')} [cyan]{anilist_id}[/cyan]")
            media = anilist_client.get_media_with_relations(anilist_id)
            if media:
                results = [media]
        elif not query:
            print_info(f"{t('Loading trending anime…')}")
            results = anilist_client.trending(10)
        else:
            print_info(f"{t('Searching AniList by Title:')} [cyan]{query}[/cyan]")
            results = anilist_client.search_media(query)

        if not results:
            print_warning(t("No results found."))
            pause()
            if from_latest:
                return
            continue

        # Shared match picker (search + trending).
        def _ani_lines(m):
            out = []
            bits = []
            if m.get("seasonYear"):
                bits.append(str(m["seasonYear"]))
            if m.get("format"):
                bits.append(str(m["format"]))
            if m.get("episodes"):
                bits.append(f"{m['episodes']} {t('eps')}")
            if bits:
                out.append(" · ".join(bits))
            if m.get("genres"):
                out.append(", ".join(m["genres"][:3]))
            return out

        previews = [
            make_preview(
                cover=_cover(m),
                title=m["title"]["english"] or m["title"]["romaji"],
                lines=_ani_lines(m),
                panel_title="GoldenAnime",
            )
            for m in results
        ]
        labels = [
            f"{m['title']['english'] or m['title']['romaji']} "
            f"({m.get('seasonYear', '?')}) - {m.get('episodes', '?')} {t('eps')}"
            for m in results
        ]

        while True:  # ── Results level ──
            m_idx = select_with_preview(
                labels, f"{icon('sparkle')} {t('Select AniList Match:')}", previews
            )
            if m_idx >= len(results):
                break  # → search input (search) / provider menu (latest)

            match = results[m_idx]
            anilist_id = match["id"]
            title = clean_text(
                match["title"]["english"] or match["title"]["romaji"]
            )
            max_episodes = match.get("episodes")
            cover_url = _cover(match)

            from .. import terminal_image
            terminal_image.show_poster(
                cover_url,
                info_lines=[
                    f"{max_episodes} {plural(max_episodes, 'episode', 'episodes')}"
                    if max_episodes else ""
                ],
            )

            while True:  # ── Episodes level ──
                episode = 1
                if max_episodes:
                    ep_options = [
                        f"{t('Episode')} {i}" for i in range(1, max_episodes + 1)
                    ] + [t("Manual Input"), t("← Back")]
                    with crumb(title):
                        ep_idx = select_from_list(
                            ep_options, f"{icon('tv')} {t('Select Episode:')}"
                        )
                    if ep_idx < max_episodes:
                        episode = ep_idx + 1
                    elif ep_idx == max_episodes:
                        ep_input = get_user_input(t("Episode number"))
                        if not ep_input or not ep_input.isdigit():
                            continue
                        episode = int(ep_input)
                    else:
                        break  # → results
                else:
                    ep_input = get_user_input(t("Episode number (default 1)"))
                    episode = int(ep_input) if ep_input and ep_input.isdigit() else 1

                handle_goldenanime_episode(
                    title=title, anilist_id=anilist_id,
                    start_episode=episode, cover_url=cover_url,
                )
                # Back from the stream/next menu → episode list again.

        if from_latest:
            return  # latest is a single feed: Back leaves the provider


def _flow_goldenanime_stream(
    title: str, anilist_id: int, episode: int, cover_url: str = None
):
    """Common logic for searching streams, subtitles, and playing."""
    with spinner(t("Searching for streams…")):
        results = goldenanime.extract_vo(
            title=title, anilist_id=anilist_id, episode=episode
        )

    if not results:
        print_warning(t("No results found."))
        pause()
        return

    # Filter: only keep direct streams (m3u8 / master URLs) or supported embedded players
    def _is_valid(r):
        url = r.get("url", "")
        return (
            r.get("type").lower() == "m3u8"
            or r.get("type").lower() == "mp4"
            or ".m3u8" in url
            or "master" in url.lower()
            or player_scraper.is_supported(url)
        )

    valid_results = [r for r in results if _is_valid(r)]

    if not valid_results:
        print_warning(
            t("No supported streams found (no direct M3U8 or recognised players).")
        )
        pause()
        return

    if len(valid_results) < len(results):
        skipped = len(results) - len(valid_results)
        print_info(f"[dim]{t('Skipped')} {skipped} {t('unsupported stream(s).')}[/dim]")

    # Analyse each stream's real resolutions + bitrate (like the other
    # sources), shown next to the source. Direct m3u8/mp4 are probed
    # directly ; runs in parallel with a total time budget.
    def _ga_headers(r):
        h = {"Referer": goldenanime.sudatchi_base + "/"}
        if "Allanime" in r.get("source", ""):
            h["Referer"] = goldenanime.allanime_referer + "/"
        if "Animetsu" in r.get("source", ""):
            h["Referer"] = goldenanime.animetsu_base + "/"
            h["Origin"] = goldenanime.animetsu_base
        if isinstance(r.get("headers"), dict):
            for k, v in r["headers"].items():
                if v:
                    h[k] = v
        return h

    quality_map = {}
    if tracker.get_analyze_players():
        from concurrent.futures import (
            ThreadPoolExecutor, as_completed, TimeoutError as _FT,
        )

        ex = ThreadPoolExecutor(max_workers=min(16, max(1, len(valid_results))))
        futs = {
            ex.submit(analyze_stream_quality, r["url"], _ga_headers(r), 25): i
            for i, r in enumerate(valid_results)
        }
        with spinner(t("Analyzing streams (resolutions, bitrate)…")):
            try:
                for fut in as_completed(futs, timeout=40):
                    i = futs[fut]
                    try:
                        quality_map[i] = format_quality_label(fut.result())
                    except Exception:
                        quality_map[i] = "✗"
            except _FT:
                pass
        ex.shutdown(wait=False)

    stream_labels = []
    for i, r in enumerate(valid_results):
        base = f"{r['source']} - {r['quality']} ({r['type']})"
        q = quality_map.get(i)
        if q and q != "✓":
            base += f"  —  {q}"
        stream_labels.append(base)

    choice_idx = select_from_list(
        stream_labels + [t("← Back")], f"{icon('tv')} {t('Select Stream:')}"
    )

    if choice_idx == len(valid_results):  # Back
        return

    selection = valid_results[choice_idx]

    # Subtitles logic
    subtitle_url = None
    # Subtitles follow the chosen content (anime) language : English pick →
    # English subs, French pick → French subs. Fall back to interface lang.
    user_lang = tracker.get_anime_language() or tracker.get_language() or "en"
    lang_name = get_language_label(user_lang)

    want_subs = 1  # default: No
    if tracker.get_subtitle_search():
        want_subs = select_from_list(
            [t("Yes"), t("No")], f"{t('Search subtitles in')} {lang_name} ?"
        )
    if want_subs == 0:
        # Try to resolve title if missing
        search_title = title
        if not search_title and anilist_id:
            media = anilist_client.get_media_with_relations(anilist_id)
            if media:
                search_title = media.get("title", {}).get("english") or media.get(
                    "title", {}
                ).get("romaji")

        imdb_id = None
        is_movie = False
        if search_title:
            imdb_id, is_movie = search_imdb_id(search_title)
        else:
            imdb_id = get_user_input(
                t("Enter IMDB ID manually (e.g. tt0388629, leave blank to skip)")
            )

        if imdb_id:
            season = None
            skip_subs = False
            if not is_movie:
                # Detect season from title for smart default
                default_season_idx = 0
                if search_title:
                    match = re.search(r"Season\s+(\d+)", search_title, re.IGNORECASE)
                    if match:
                        detected_season = int(match.group(1))
                        # Range 1-10 mapped to 0-9 index
                        if 1 <= detected_season <= 10:
                            default_season_idx = detected_season - 1

                season_options = [f"{t('Season')} {i}" for i in range(1, 11)] + [
                    t("Manual Input"),
                    t("← Back"),
                ]
                s_idx = select_from_list(
                    season_options,
                    t("Select Season (for subtitles mapping):"),
                    default_index=default_season_idx,
                )
                skip_subs = False
                if s_idx < 10:
                    season = s_idx + 1
                elif s_idx == 10:
                    season_input = get_user_input(t("Season number (default 1)"))
                    season = (
                        int(season_input)
                        if season_input and season_input.isdigit()
                        else 1
                    )
                else:
                    skip_subs = True  # ← Back : skip subtitle search

            if not skip_subs:
                print_info(f"{t('Searching for')} {lang_name} {t('subtitles...')}")
                subs = subtitle_extractor.search(
                    imdb_id=imdb_id, season=season, episode=episode, lang_filter=user_lang
                )
                if subs:
                    # Show a shortened list to make it faster
                    sub_choices = [
                        f"{s['source']} - {s.get('lang', lang_name)}" for s in subs[:5]
                    ] + [t("None")]
                    sub_idx = select_from_list(sub_choices, f"📝 {t('Select Subtitle:')}")
                    if sub_idx < len(sub_choices) - 1:
                        subtitle_url = subs[sub_idx]["url"]
                        print_info(f"{t('Selected subtitle from:')} {subs[sub_idx]['source']}")
                else:
                    print_warning(f"{t('No')} {lang_name} {t('subtitles found.')}")

    print_info(f"{t('Loading stream from')} [cyan]{selection['source']}[/cyan]...")

    headers = {
        "Referer": goldenanime.sudatchi_base + "/",
    }
    if "Allanime" in selection["source"]:
        headers["Referer"] = goldenanime.allanime_referer + "/"
    if "Animetsu" in selection["source"]:
        headers["Referer"] = goldenanime.animetsu_base + "/"
        headers["Origin"] = goldenanime.animetsu_base

    # Propagate any per-source headers the scraper attached (some sources
    # carry their own Referer/Origin/Cookie that must reach the CDN).
    if isinstance(selection.get("headers"), dict):
        for k, v in selection["headers"].items():
            if v:
                headers[k] = v

    display_title = title if title else f"AniList ID {anilist_id}"

    # Handle specific API URLs that return JSON instead of M3U8 directly
    final_url = selection["url"]
    sudatchi_api_domain = goldenanime.sudatchi_base.replace("https://", "")
    if (
        sudatchi_api_domain + "/api/streams" in final_url
        or "sudatchi.com/api/streams" in final_url
    ):
        try:
            resp = requests.get(final_url, headers=headers, impersonate="chrome", timeout=15).json()
            if isinstance(resp, list) and len(resp) > 0:
                final_url = resp[0].get("url", final_url)
        except Exception:
            pass

    is_direct = (
        selection["type"].lower() == "m3u8"
        or "m3u8" in final_url
        or selection["type"].lower() == "mp4"
    )

    success = play_video(
        final_url,
        headers=headers,
        title=f"{display_title} - {t('Episode')} {episode}",
        subtitle_url=subtitle_url,
        is_direct=is_direct,
        is_mp4=selection["type"].lower() == "mp4",
    )

    if success:
        # Save local progress with rich metadata
        tracker.save_progress(
            provider="GoldenAnime",
            series_title=display_title,
            season_title="VO",
            episode_title=f"Episode {episode}",
            series_url=f"anilist:{anilist_id}" if anilist_id else "",
            season_url="",
            episode_url="",  # URL expires; re-search on resume
            logo_url=cover_url,
        )
        print_success(t("Local progress saved."))

        # Sync AniList if authenticated
        if anilist_id:
            token = tracker.get_anilist_token()
            if token:
                anilist_client.set_token(token)
                if anilist_client.update_progress(anilist_id, episode):
                    print_success(f"{t('AniList updated to episode')} {episode}!")
                else:
                    print_warning(t("Could not update AniList."))

    else:
        print_warning(t("Playback failed or was cancelled."))
        pause()
        return False

    return True


def handle_goldenanime_episode(
    title: str, anilist_id: int, start_episode: int, cover_url: str = None
):
    """Loop: play episode, then propose next, or stop."""
    episode = start_episode
    while True:
        success = _flow_goldenanime_stream(
            title=title, anilist_id=anilist_id, episode=episode, cover_url=cover_url
        )
        if success:
            next_ep = episode + 1
            choice = select_from_list(
                [f"▶ {t('Play Episode')} {next_ep}", t("← Back")],
                f"{t('Episode')} {episode} {t('finished:')}",
            )
            if choice == 0:
                episode = next_ep
                continue
        break


def resume_goldenanime(data):
    """Resume GoldenAnime playback from history."""
    title = data["series_title"]
    episode_str = data["episode_title"].replace("Episode ", "")
    episode = int(episode_str) if episode_str.isdigit() else 1

    # Recover anilist_id from series_url field (stored as "anilist:12345")
    anilist_id = None
    series_url = data.get("series_url", "")
    if series_url.startswith("anilist:"):
        id_str = series_url.replace("anilist:", "")
        if id_str.isdigit():
            anilist_id = int(id_str)
    elif series_url.isdigit():
        # Fallback for broken history entries where the prefix was stripped
        anilist_id = int(series_url)
    # Legacy fallback: title used to encode the ID
    elif title and title.startswith("AniList ID "):
        id_str = title.replace("AniList ID ", "")
        if id_str.isdigit():
            anilist_id = int(id_str)
            title = None

    display_title = title if title else f"AniList ID {anilist_id}"
    print_info(f"{t('Found progress:')} [cyan]{display_title}[/cyan] - {t('Episode')} {episode}")

    options = [
        f"▶ {t('Continue')} ({t('Episode')} {episode + 1})",
        f"🔁 {t('Watch again')} ({t('Episode')} {episode})",
        t("← Cancel"),
    ]
    choice = select_from_list(options, t("What would you like to do?"))

    if choice == 2:  # Cancel
        return
    elif choice == 0:  # Next
        episode += 1

    handle_goldenanime_episode(
        title=title, anilist_id=anilist_id, start_episode=episode
    )
