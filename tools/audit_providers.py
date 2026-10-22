"""Live audit of every FreeFlix provider (network heavy — manual tool).

    python tools/audit_providers.py            # all providers
    python tools/audit_providers.py anime coflix

Checks the real user path for each source: live mirror → search → content →
players → stream resolution → resolution/bitrate. Prints one line per check
and a summary; exits 1 when a provider is broken.
"""

from __future__ import annotations

import sys
import time
import traceback

RESULTS = []


def record(provider, step, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} | {provider:<15} | {step:<20} | {detail}",
          flush=True)
    RESULTS.append((provider, step, ok, detail))


def timed(fn):
    start = time.monotonic()
    try:
        return fn(), time.monotonic() - start, None
    except Exception as exc:  # noqa: BLE001
        return None, time.monotonic() - start, exc


def audit_anime_sama():
    from freeflix_cli.scraping import anime_sama as s
    from freeflix_cli.scraping import player

    _, dt, err = timed(s.get_website_url)
    record("Anime-Sama", "mirror", bool(s.website_origin), f"{s.website_origin} {dt:.1f}s")
    if not s.website_origin:
        return
    res, dt, _ = timed(lambda: s.search("Dreamland"))
    record("Anime-Sama", "search", bool(res), f"{len(res or [])} results {dt:.1f}s")
    series, dt, err = timed(
        lambda: s.get_series(f"{s.website_origin}/catalogue/dreamland")
    )
    record("Anime-Sama", "series", bool(series and series.seasons),
           f"{len(getattr(series, 'seasons', []) or [])} seasons {dt:.1f}s")
    if not series or not series.seasons:
        return
    season, dt, _ = timed(lambda: s.get_season(series.seasons[0].url))
    langs = {k: len(v) for k, v in (getattr(season, "episodes", {}) or {}).items()}
    record("Anime-Sama", "season", bool(langs), f"{langs} {dt:.1f}s")
    if not langs:
        return
    ep = next(iter(season.episodes.values()))[0]
    p = ep.players[0]
    url, dt, err = timed(
        lambda: player.get_hls_link(p.url, {"Referer": s.website_origin})
    )
    record("Anime-Sama", "player", bool(url), f"{p.name} {dt:.1f}s {err or ''}")


def audit_french_stream():
    from freeflix_cli.scraping import french_stream as s
    from freeflix_cli.scraping import player
    from freeflix_cli.player_manager import analyze_stream_quality, format_quality_label

    res, dt, _ = timed(lambda: s.search("Nightborn"))
    record("French-Stream", "search", bool(res), f"{len(res or [])} {dt:.1f}s")
    if not res:
        return
    movie, dt, _ = timed(lambda: s.get_content(res[0].url))
    players = getattr(movie, "players", []) or []
    record("French-Stream", "players", bool(players),
           f"{[p.name for p in players]} {dt:.1f}s")
    ok_any = False
    for p in players[:3]:
        url, dt, _ = timed(lambda p=p: player.get_hls_link(p.url, {"Referer": p.url}))
        if not url:
            record("French-Stream", f"resolve:{p.name}", False, f"{dt:.1f}s")
            continue
        info, dt, _ = timed(lambda u=url: analyze_stream_quality(u, {}, 20))
        record("French-Stream", f"resolve:{p.name}", True,
               f"{format_quality_label(info or {})} {dt:.1f}s")
        ok_any = True
    record("French-Stream", "at-least-one", ok_any, "")


def audit_goldenms():
    from freeflix_cli.handlers.goldenms import search_cinemeta, get_cinemeta_details
    from freeflix_cli.scraping.goldenms import goldenms_extractor as x
    from freeflix_cli.player_manager import analyze_stream_quality, format_quality_label

    metas, dt, _ = timed(lambda: search_cinemeta("Nightborn", True))
    record("GoldenMS", "cinemeta", bool(metas), f"{len(metas or [])} {dt:.1f}s")
    if not metas:
        return
    detail, _, _ = timed(lambda: get_cinemeta_details(metas[0]["id"], True))
    tmdb = detail.get("moviedb_id")
    streams, dt, _ = timed(
        lambda: x.extract(title="Nightborn", tmdb_id=tmdb, year="2026")
    )
    valid = [r for r in (streams or []) if not str(r.get("url", "")).startswith("/")]
    record("GoldenMS", "extract", bool(valid),
           f"{[r['source'] for r in valid]} {dt:.1f}s")
    for r in valid[:3]:
        info, dt, _ = timed(
            lambda r=r: analyze_stream_quality(r["url"], r.get("headers") or {}, 20)
        )
        record("GoldenMS", f"stream:{r['source']}", bool((info or {}).get("ok")),
               f"{format_quality_label(info or {})} {dt:.1f}s")


def audit_hianime():
    from freeflix_cli.scraping.goldenanime import goldenanime as g

    shows, dt, _ = timed(lambda: g.latest_hianime(3))
    record("HiAnime", "latest", bool(shows), f"{len(shows or [])} {dt:.1f}s")
    if not shows:
        return
    slug = shows[0]["slug"]
    eps, dt, _ = timed(lambda: g.get_hianime_episodes(slug))
    record("HiAnime", "episodes", bool(eps), f"{len(eps or [])} {dt:.1f}s")
    if not eps:
        return
    streams, dt, _ = timed(lambda: g.extract_hianime_episode(slug, eps[0][0]))
    record("HiAnime", "streams", bool(streams),
           f"{[s['source'] for s in streams or []]} {dt:.1f}s")


def audit_goldenanime():
    from freeflix_cli.scraping.goldenanime import goldenanime as g

    results, dt, _ = timed(lambda: g.extract_vo(title="Frieren", episode=1))
    record("GoldenAnime", "extract", bool(results),
           f"{[r.get('source') for r in (results or [])][:3]} {dt:.1f}s")


def audit_coflix():
    from freeflix_cli.scraping import coflix as c
    from freeflix_cli.scraping import player

    _, dt, _ = timed(c.get_website_url)
    res, dt, _ = timed(lambda: c.search("one piece"))
    record("Coflix", "search", bool(res), f"{len(res or [])} {dt:.1f}s")
    if not res:
        return
    series, _, _ = timed(lambda: c.get_series(res[0].url))
    seasons = getattr(series, "seasons", []) or []
    record("Coflix", "series", bool(seasons), f"{len(seasons)} seasons")
    if not seasons:
        return
    season, dt, _ = timed(lambda: c.get_season(seasons[0].url))
    eps = getattr(season, "episodes", []) or []
    record("Coflix", "season", bool(eps), f"{len(eps)} episodes {dt:.1f}s")
    if not eps:
        return
    details, dt, _ = timed(lambda: c.get_episode(eps[0].url))
    players = getattr(details, "players", []) or []
    record("Coflix", "players", bool(players), f"{len(players)} {dt:.1f}s")
    if players:
        url, dt, _ = timed(
            lambda: player.get_hls_link(players[0].url,
                                        {"Referer": "https://lecteurvideo.com/"})
        )
        record("Coflix", "resolve", bool(url), f"{dt:.1f}s")


def audit_french_manga():
    from freeflix_cli.scraping import french_manga as f

    res, dt, _ = timed(lambda: f.search("One Piece"))
    record("French-Anime", "search", bool(res), f"{len(res or [])} {dt:.1f}s")


def audit_papystreaming():
    from freeflix_cli.scraping import papystreaming as p

    res, dt, _ = timed(lambda: p.search("nightborn"))
    record("Papystreaming", "search", bool(res),
           f"{len(res or [])} {dt:.1f}s blocked={p.blocked_by_cloudflare}")


def audit_yts():
    from freeflix_cli.scraping import yts

    res, dt, _ = timed(lambda: yts.latest(5))
    record("YTS", "latest", bool(res), f"{len(res or [])} {dt:.1f}s")


def audit_eztv():
    from freeflix_cli.scraping import eztv

    res, dt, _ = timed(lambda: eztv.latest(5))
    record("EZTV", "latest", bool(res), f"{len(res or [])} {dt:.1f}s")


def audit_nyaa():
    from freeflix_cli.scraping import nyaa

    res, dt, _ = timed(lambda: nyaa.search("Frieren"))
    record("Nyaa", "search", bool(res), f"{len(res or [])} {dt:.1f}s")


AUDITS = {
    "anime-sama": audit_anime_sama,
    "french-stream": audit_french_stream,
    "goldenms": audit_goldenms,
    "hianime": audit_hianime,
    "goldenanime": audit_goldenanime,
    "coflix": audit_coflix,
    "french-manga": audit_french_manga,
    "papystreaming": audit_papystreaming,
    "yts": audit_yts,
    "eztv": audit_eztv,
    "nyaa": audit_nyaa,
}


def main():
    wanted = sys.argv[1:] or list(AUDITS)
    for name in wanted:
        fn = AUDITS.get(name)
        if fn is None:
            print(f"unknown provider: {name}")
            continue
        try:
            fn()
        except Exception:  # noqa: BLE001
            record(name, "crash", False, traceback.format_exc().splitlines()[-1])

    print("\n=== SUMMARY ===")
    bad = [r for r in RESULTS if not r[2]]
    print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} checks OK")
    for provider, step, _ok, detail in bad:
        print(f"FAIL {provider} | {step} | {detail}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
