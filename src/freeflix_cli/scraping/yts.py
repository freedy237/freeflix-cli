"""
YTS movie provider — big, up-to-date English movie catalog via the public
YTS JSON API (no scraping, no Cloudflare wall).

``search()`` / ``latest()`` return dicts :
    {"tmdb_like_id", "title", "year", "rating", "runtime", "genres",
     "synopsis", "poster", "yts_url",
     "qualities": [{"quality", "size", "size_bytes", "seeds", "peers",
                    "hash", "date", "magnet"}]}
Mirrors are tried in order (yts.mx is often DNS-dead — see module list).
"""

from __future__ import annotations

import urllib.parse

from curl_cffi import requests as cffi_requests
from ..net_config import DNS_OPTIONS
from .config import portals
from .. import httpcache
from .utils import clean_text

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

MIRRORS = [
    "https://yts.lt",
    "https://yts.mx",
    "https://yts.am",
    "https://yts.ag",
]

# Public trackers baked into every magnet (same list as the Nyaa handler).
TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
]


def _base() -> str:
    return portals.get("yts", MIRRORS[0]).rstrip("/")


def _magnet(hash_: str, title: str) -> str:
    tr = "".join(f"&tr={urllib.parse.quote(t, safe='')}" for t in TRACKERS)
    return (f"magnet:?xt=urn:btih:{hash_}"
            f"&dn={urllib.parse.quote(title or 'movie')}{tr}")


def _clean(movie: dict) -> dict | None:
    if not isinstance(movie, dict):
        return None
    quals = []
    for t in movie.get("torrents") or []:
        if not isinstance(t, dict) or not t.get("hash"):
            continue
        quals.append({
            "quality": t.get("quality") or "?",
            "size": t.get("size") or "",
            "size_bytes": t.get("size_bytes") or 0,
            "seeds": t.get("seeds") or 0,
            "peers": t.get("peers") or 0,
            "hash": t["hash"],
            "date": (t.get("date_uploaded") or "")[:10],
            "magnet": _magnet(
                t["hash"],
                f"{movie.get('title_english') or movie.get('title', '')} "
                f"[{t.get('quality')}]"),
        })
    if not quals:
        return None
    quals.sort(key=lambda q: q["size_bytes"])
    return {
        "yts_id": movie.get("id"),
        "title": clean_text(movie.get("title_english") or movie.get("title") or "?"),
        "year": movie.get("year") or "",
        "rating": movie.get("rating") or 0,
        "runtime": movie.get("runtime") or 0,
        "genres": movie.get("genres") or [],
        "synopsis": (movie.get("synopsis") or "")[:220],
        "poster": movie.get("medium_cover_image") or "",
        "yts_url": movie.get("url") or "",
        "imdb": movie.get("imdb_code") or "",
        "qualities": quals,
    }


def _fetch(path: str, params: dict) -> list[dict]:
    import json as _json
    ckey = "yts:" + path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    cached = httpcache.get(ckey, 300)
    if cached is not None:
        try:
            return _json.loads(cached)
        except ValueError:
            pass
    bases = [_base()] + [b for b in MIRRORS if b != _base()]
    for base in bases:
        try:
            r = scraper.get(base + path, params=params, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            if data.get("status") != "ok":
                continue
            movies = (data.get("data") or {}).get("movies") or []
            out = [c for c in (_clean(m) for m in movies) if c]
            if out:
                httpcache.store(ckey, _json.dumps(out))
                return out
        except Exception:
            continue
    return []


def search(query: str, limit: int = 20) -> list[dict]:
    """Search YTS by title."""
    if not (query or "").strip():
        return []
    return _fetch("/api/v2/list_movies.json", {
        "query_term": query.strip(), "limit": limit,
        "sort_by": "like_count", "order_by": "desc",
        "with_rt_ratings": False,
    })


def latest(limit: int = 20) -> list[dict]:
    """Newest YTS uploads (the up-to-date catalog)."""
    return _fetch("/api/v2/list_movies.json", {
        "limit": limit, "sort_by": "date_added", "order_by": "desc",
        "with_rt_ratings": False,
    })
