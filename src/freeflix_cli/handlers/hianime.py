"""HiAnime provider handler (English anime, sub + dub).

Same UX model as the other providers : search with history, poster
previews, episode picker, per-episode streams, resume + next-episode loop.
Resolution rides ``AnimeExtractor.search_hianime_*`` (ani-cli's chain).
"""

from ..scraping.goldenanime import goldenanime
from ..cli_utils import (
    clear_screen,
    select_from_list,
    select_with_preview,
    make_preview,
    print_info,
    print_warning,
    print_success,
    get_user_input,
    pause,
    skeleton,
    spinner,
    crumb,
)
from ..player_manager import play_video
from ..tracker import tracker
from ..icons import icon
from ..i18n import t


def _play_stream(provider_title, slug, episode, stream, cover_url):
    """Play one resolved HiAnime stream ; save progress on success."""
    headers = dict(stream.get("headers") or {})
    subs = stream.get("subtitles") or []
    subtitle_url = subs[0]["url"] if subs else None
    ok = play_video(
        stream["url"],
        headers=headers,
        title=f"{provider_title} - {t('Episode')} {episode}",
        subtitle_url=subtitle_url,
        is_direct=True,
        is_mp4=False,
    )
    if ok:
        tracker.save_progress(
            provider="HiAnime",
            series_title=provider_title,
            season_title="VO",
            episode_title=f"Episode {episode}",
            series_url=f"hianime:{slug}",
            season_url="",
            episode_url="",
            logo_url=cover_url,
        )
        print_success(t("Local progress saved."))
        return True
    print_warning(t("Playback failed or was cancelled."))
    pause()
    return False


def handle_hianime_episode(title, slug, start_episode, cover_url=None,
                           total_eps=None):
    """Episode loop : pick a stream, play, propose the next one."""
    episode = start_episode
    while True:
        with spinner(t("Loading stream from HiAnime…")):
            streams = goldenanime.extract_hianime_episode(slug, episode)
        if not streams:
            print_warning(t("No results found."))
            pause()
            return
        labels = [
            f"{s['source']} [{s['quality']}]"
            + (f"  ·  {len(s.get('subtitles') or [])} subs" if s.get("subtitles") else "")
            for s in streams
        ] + [t("← Back")]
        c_idx = select_from_list(labels, f"{icon('tv')} {t('Select Stream:')}")
        if c_idx >= len(streams):
            return
        if not _play_stream(title, slug, episode, streams[c_idx], cover_url):
            return
        nxt = episode + 1
        if total_eps and nxt > total_eps:
            return
        choice = select_from_list(
            [f"▶ {t('Play Episode')} {nxt}", t("← Back")],
            f"{t('Episode')} {episode} {t('finished:')}",
        )
        if choice == 0:
            episode = nxt
            continue
        return


def handle_hianime():
    """Handle HiAnime provider flow (English, sub/dub).

    Back stack : results ← episodes ← streams, one level per Esc.
    Backing out of a show re-shows the SAME results (no refetch).
    """
    mode = select_from_list(
        [f"{icon('new')} {t('Latest uploads')}",
         f"{icon('search')} {t('Search by title')}", t("← Back")],
        f"{icon('sparkle')} HiAnime (EN)",
    )
    if mode == 2:
        return
    from_latest = (mode == 0)
    last_query = ""
    while True:  # ── Search level (search mode) / single pass (latest) ──
        clear_screen()  # each new search starts clean
        if from_latest:
            query = ""
        else:
            query = get_user_input(
                t("Search query (or 'exit' to back)"),
                default=last_query or None,
                header=f"{icon('sparkle')} HiAnime (EN)",
                history=tracker.get_search_history(),
            )
            if query and query.lower() != "exit":
                tracker.add_search_query(query)
            if not query or query.lower() == "exit":
                return
            last_query = query

        if from_latest:
            with skeleton(f"{t('Loading latest movies…')}"):
                shows = goldenanime.latest_hianime(15)
        else:
            with skeleton(f"{t('Searching for')} {query}…"):
                shows = goldenanime.search_hianime_shows(query)
        if not shows:
            print_warning(t("No results found."))
            pause()
            if from_latest:
                return
            continue

        previews = [
            make_preview(
                cover=s.get("poster", ""),
                title=s["title"],
                lines=[f"SUB {s.get('sub') or '?'} · DUB {s.get('dub') or '?'}"],
                panel_title="HiAnime",
            )
            for s in shows
        ]
        labels = [s["title"] for s in shows]

        while True:  # ── Results level ──
            c_idx = select_with_preview(
                labels, f"{icon('tv')} {t('Search Results:')}", previews
            )
            if c_idx >= len(shows):
                break  # → search input (search mode) / provider menu (latest)
            sel = shows[c_idx]

            from .. import terminal_image
            terminal_image.show_poster(sel.get("poster", ""))

            with spinner(f"{t('Loading')} {sel['title']}…"):
                episodes = goldenanime.get_hianime_episodes(sel["slug"])
            if not episodes:
                print_warning(t("No episodes found."))
                pause()
                continue

            total = len(episodes)
            ep_idx = (len(episodes) - 1 if from_latest and episodes else 0)
            while True:  # ── Episodes level ──
                with crumb(sel["title"]):
                    ep_labels = [f"{t('Episode')} {n}" for n, _eid in episodes] + [
                        t("← Back")
                    ]
                    e_idx = select_from_list(
                        ep_labels, f"{icon('tv')} {t('Select Episode:')}",
                        default_index=min(ep_idx, len(episodes) - 1),
                    )
                if e_idx >= len(episodes):
                    break  # → results
                ep_idx = e_idx
                handle_hianime_episode(
                    sel["title"], sel["slug"], episodes[e_idx][0],
                    cover_url=sel.get("poster", ""), total_eps=total,
                )
                # Back from the stream/next menu → episodes list again.

        if from_latest:
            return  # latest is a single feed: Back leaves the provider


def resume_hianime(data):
    """Resume HiAnime playback from history."""
    title = data.get("series_title", "")
    slug = (data.get("series_url", "") or "").removeprefix("hianime:")
    ep_str = (data.get("episode_title") or "").replace("Episode ", "")
    episode = int(ep_str) if ep_str.isdigit() else 1

    print_info(f"{t('Found progress:')} [cyan]{title}[/cyan] - {t('Episode')} {episode}")
    options = [
        f"▶ {t('Continue')} ({t('Episode')} {episode + 1})",
        f"🔁 {t('Watch again')} ({t('Episode')} {episode})",
        t("← Cancel"),
    ]
    choice = select_from_list(options, t("What would you like to do?"))
    if choice == 2:
        return
    start = episode + 1 if choice == 0 else episode
    with spinner(f"{t('Loading')} {title}…"):
        episodes = goldenanime.get_hianime_episodes(slug) if slug else []
    total = len(episodes) or None
    handle_hianime_episode(title, slug, start,
                           cover_url=data.get("logo_url"), total_eps=total)
