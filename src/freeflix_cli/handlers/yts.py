"""YTS provider handler (English movies, up-to-date, via public API)."""

from ..scraping import yts
from ..scraping import eztv
from .goldenms import search_cinemeta, get_cinemeta_details
from .goldenms import _flow_goldenms_stream
from ..cli_utils import (
    select_from_list,
    select_with_preview,
    make_preview,
    print_warning,
    print_success,
    get_user_input,
    pause,
    skeleton,
    crumb,
)
from ..icons import icon
from ..i18n import t
from ..tracker import tracker
from . import nyaa as nyaa_handler
from .goldenanime import _flow_goldenanime_stream
import re as _re


def _guess_show(release: str):
    """(clean_title, season, episode) from a release name like
    '[Breeze] Solo Leveling S01 v2 …' or '[SubsPlease] One Piece - 1090 …'."""
    t = _re.sub(r"\[[^\]]*\]", " ", release or "")
    t = _re.sub(r"\([^)]*\)", " ", t)
    season, episode = None, 1
    m = _re.search(r"[Ss](\d{1,2})[Ee](\d{1,4})", t)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
    else:
        m = _re.search(r"\b[Ss](\d{1,2})\b", t)
        if m:
            season = int(m.group(1))
        m = _re.search(r"\b[Ee](\d{1,4})\b", t)
        if m:
            episode = int(m.group(1))
        else:
            m = _re.search(r"(?:^|\s|-)(\d{3,4})(?:\s|$)", t)
            if m:
                episode = int(m.group(1))
    t = _re.sub(r"[Ss]\d{1,2}[Ee]\d{1,4}.*$", "", t)
    t = _re.sub(r"\b(1080p|720p|480p|2160p|4k|uhd|bd|hevc|x265|x264|av1|opus|aac|multi|dual|audio|sub|subs|vostfr|vf|vo|web|bluray|hdtv|remux|repack|v2|v3)\b",
                " ", t, flags=_re.I)
    t = _re.sub(r"\s+", " ", t).strip(" -–—:;,.!?")
    return t or release, season, episode


def _stream_via_goldenanime(release_title: str) -> None:
    """Offer a stream for a torrent release through the GoldenAnime
    resolvers (HiAnime sub/dub + friends)."""
    from ..cli_utils import select_from_list as _sel
    from ..i18n import t as _t
    clean, _season, ep = _guess_show(release_title)
    ans = _sel([f"{_t('Stream:')} {clean} ({_t('Episode')} {ep})",
                _t("← Back")],
               f"{icon('play')} {_t('Stream via GoldenAnime?')}")
    if ans != 0:
        return
    _flow_goldenanime_stream(title=clean, anilist_id=None, episode=ep,
                             cover_url=None)


def _pick_quality(movie: dict):
    """Quality menu (720p/1080p/2160p + size + seeders)."""
    opts = [
        f"{q['quality']}  ·  {q['size']}  ·  S:{q['seeds']}"
        + (f"  ·  {q['date']}" if q.get("date") else "")
        for q in movie["qualities"]
    ] + [t("← Back")]
    idx = select_from_list(
        opts, f"{icon('download')} {t('Select quality:')} {movie['title'][:50]}"
    )
    if idx >= len(movie["qualities"]):
        return None
    return movie["qualities"][idx]


def _play_results(results, prompt_title):
    """Preview list → quality → Download / Download+Watch / Back."""
    previews = [
        make_preview(
            cover=r.get("poster", ""),
            title=r["title"],
            lines=[
                f"{r['year']} · {icon('star')} {r['rating']} · "
                f"{r['runtime']}min" if r.get("runtime") else f"{r['year']}",
                ", ".join(r.get("genres", [])[:3]),
            ],
            panel_title="YTS",
        )
        for r in results
    ]
    labels = [
        f"{r['title']} ({r['year']})  {icon('star')} {r['rating']}  "
        f"[{r['qualities'][-1]['quality']}]"
        for r in results
    ]
    idx = select_with_preview(labels, prompt_title, previews)
    if idx >= len(results):
        return
    movie = results[idx]
    if not any(q.get("seeds") for q in movie["qualities"]):
        print_warning(t("Warning: 0 seeders — this torrent may never complete."))
    with crumb(movie["title"]):
        q = _pick_quality(movie)
        if q is None:
            return
        actions = [f"{icon('play')} {t('Stream')}", f"{icon('download')} {t('Download')}", f"{icon('play')} {t('Download + Watch')}",
                   t("← Back")]
        act = select_from_list(actions, f"{movie['title'][:55]} [{q['quality']}]")
        if act == 0:
            _stream_movie(movie)
        elif act == 1:
            nyaa_handler._download_torrent(q["magnet"], movie["title"], watch=False)
        elif act == 2:
            nyaa_handler._download_and_watch(q["magnet"], movie["title"])
    pause()


def _stream_movie(movie: dict) -> None:
    """Stream a YTS movie through the GoldenMS resolvers (Vidlink…)."""
    imdb = movie.get("imdb") or ""
    tmdb = None
    try:
        if imdb:
            det = get_cinemeta_details(imdb, True)
            tmdb = det.get("moviedb_id")
    except Exception:
        tmdb = None
    _flow_goldenms_stream(
        title=movie["title"],
        tmdb_id=tmdb,
        imdb_id=imdb,
        year=int(movie["year"]) if str(movie.get("year") or "").isdigit() else None,
        season=None,
        episode=None,
        is_movie=True,
        logo_url=movie.get("poster", ""),
    )


def handle_yts():
    """YTS flow : Latest movies, title search, or series (EZTV)."""
    mode = select_from_list(
        [f"{icon('new')} {t('Latest uploads')}", f"{icon('search')} {t('Search by title')}",
         f"{icon('tv')} {t('Series episodes (EZTV)')}", t("← Back")],
        f"{icon('movie')} YTS (EN)",
    )
    if mode == 0:
        with skeleton(f"{t('Loading latest movies…')}"):
            results = yts.latest(20)
        if results:
            _play_results(results, f"{icon('movie')} {t('Latest movies:')}")
            print_success(t("Done."))
            return
        print_warning(t("Latest is empty right now — falling back to search."))
    if mode <= 1:
        query = get_user_input(
            t("Search query (or 'exit' to back)"),
            header=f"{icon('movie')} YTS (EN)",
            history=tracker.get_search_history(),
        )
        if query and query.lower() != "exit":
            tracker.add_search_query(query)
        if not query or query.lower() == "exit":
            return
        with skeleton(f"{t('Searching for')} {query}…"):
            results = yts.search(query)
        if not results:
            print_warning(t("No results found."))
            pause()
            return
        _play_results(results, f"{icon('tv')} {t('Search Results:')}")
    elif mode == 2:
        _handle_series()
    else:
        return
    print_success(t("Done."))


def _play_latest(latest: list) -> None:
    """Pick one fresh episode → Stream / Download / Download+Watch."""
    opts = [
        f"{r.get('show', '')[:45]} S{int(r.get('season') or 0):02d}"
        f"E{int(r.get('episode') or 0):02d}  ·  {r['quality']}  ·  "
        f"{r['size']}  ·  S:{r['seeds']}"
        for r in latest
    ] + [t("← Back")]
    idx = select_from_list(opts, f"{icon('new')} {t('Latest episodes')}")
    if idx >= len(latest):
        return
    r = latest[idx]
    try:
        s, e = int(r.get("season") or 0), int(r.get("episode") or 0)
    except (TypeError, ValueError):
        s, e = 0, 0
    if not r.get("seeds"):
        print_warning(t("Warning: 0 seeders — this torrent may never complete."))
    actions = [f"{icon('play')} {t('Stream')}",
               f"{icon('download')} {t('Download')}",
               f"{icon('play')} {t('Download + Watch')}", t("← Back")]
    act = select_from_list(actions, (r.get("show") or r["filename"])[:60])
    if act == 0:
        _flow_goldenms_stream(
            title=r.get("show") or "", tmdb_id=None,
            imdb_id=r.get("imdb", ""), year=None,
            season=s or None, episode=e or None, is_movie=False,
            logo_url="",
        )
    elif act == 1:
        nyaa_handler._download_torrent(r["magnet"], r["filename"], watch=False)
    elif act == 2:
        nyaa_handler._download_and_watch(r["magnet"], r["filename"])


def _handle_series():
    """Series flow : latest episodes or title search → season/episode."""
    from .papystreaming import _pick_season_episode
    mode = select_from_list(
        [f"{icon('new')} {t('Latest episodes')}",
         f"{icon('search')} {t('Search by title')}", t("← Back")],
        f"{icon('tv')} EZTV (EN)",
    )
    if mode == 2:
        return
    if mode == 0:
        with skeleton(t("Searching EZTV…")):
            latest = eztv.latest(20)
        if not latest:
            print_warning(t("No results found."))
            pause()
            return
        _play_latest(latest)
        pause()
        return
    query = get_user_input(
        t("Search query (or 'exit' to back)"),
        header=f"{icon('tv')} EZTV (EN)",
        history=tracker.get_search_history(),
    )
    if query and query.lower() != "exit":
        tracker.add_search_query(query)
    if not query or query.lower() == "exit":
        return
    with skeleton(f"{t('Searching for')} {query}…"):
        metas = [m for m in search_cinemeta(query, False) if m.get("imdb_id")]
    if not metas:
        print_warning(t("No results found."))
        pause()
        return
    labels = [f"{m.get('name')} ({m.get('year', '?')})" for m in metas[:10]]
    m_idx = select_from_list(labels + [t("← Back")],
                             f"{icon('tv')} {t('Search Results:')}")
    if m_idx >= len(metas[:10]):
        return
    meta = metas[m_idx]
    with crumb(meta.get("name", "")):
        season, episode = _pick_season_episode(
            meta.get("name", ""), str(meta.get("year") or ""))
        if season is None:
            return
        with skeleton(t("Searching EZTV…")):
            rels = eztv.episode_torrents(meta["imdb_id"], season, episode)
        if not rels:
            print_warning(t("No releases found (try another episode)."))
            pause()
            return
        opts = [
            f"{r['quality']}  ·  {r['size']}  ·  S:{r['seeds']}  ·  "
            f"{r['filename'][:60]}"
            for r in rels[:15]
        ] + [t("← Back")]
        r_idx = select_from_list(opts, f"S{season:02d}E{episode:02d}")
        if r_idx >= len(rels[:15]):
            return
        rel = rels[r_idx]
        if not rel.get("seeds"):
            print_warning(t("Warning: 0 seeders — this torrent may never complete."))
        actions = [f"{icon('play')} {t('Stream')}", f"{icon('download')} {t('Download')}", f"{icon('play')} {t('Download + Watch')}",
                   t("← Back")]
        act = select_from_list(actions, rel["filename"][:60])
        if act == 0:
            _flow_goldenms_stream(
                title=meta.get("name", ""), tmdb_id=None,
                imdb_id=meta.get("imdb_id", ""), year=None,
                season=season, episode=episode, is_movie=False,
                logo_url="",
            )
        elif act == 1:
            nyaa_handler._download_torrent(rel["magnet"], rel["filename"], watch=False)
        elif act == 2:
            nyaa_handler._download_and_watch(rel["magnet"], rel["filename"])
    pause()
