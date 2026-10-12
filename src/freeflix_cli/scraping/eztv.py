"""
EZTV series provider — up-to-date English TV episodes via the public
EZTV JSON API (no scraping, no Cloudflare wall).

``episode_torrents(imdb_id, season, episode)`` returns dicts :
    {"title", "filename", "quality", "size_bytes", "size", "seeds",
     "peers", "date", "hash", "magnet", "torrent_url"}
Mirrors are tried in order.
"""

from __future__ import annotations

import urllib.parse

from curl_cffi import requests as cffi_requests
from ..net_config import DNS_OPTIONS
from .config import portals

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

MIRRORS = [
    "https://eztvx.to",
    "https://eztv.re",
]

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
]


def _base() -> str:
    return portals.get("eztv", MIRRORS[0]).rstrip("/")


def _size(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return ""


def _magnet(hash_: str, title: str, magnet_url: str = "") -> str:
    if magnet_url and magnet_url.startswith("magnet:"):
        return magnet_url
    tr = "".join(f"&tr={urllib.parse.quote(t, safe='')}" for t in TRACKERS)
    return (f"magnet:?xt=urn:btih:{hash_}"
            f"&dn={urllib.parse.quote(title or 'episode')}{tr}")


def _clean(t: dict) -> dict | None:
    if not isinstance(t, dict) or not t.get("hash"):
        return None
    filename = t.get("filename") or t.get("title") or ""
    return {
        "title": t.get("title") or filename,
        "filename": filename,
        "quality": "2160p" if "2160p" in filename else (
            "1080p" if "1080p" in filename else (
                "720p" if "720p" in filename else "?")),
        "size_bytes": t.get("size_bytes") or 0,
        "size": _size(t.get("size_bytes")),
        "seeds": t.get("seeds") or 0,
        "peers": t.get("peers") or 0,
        "date": t.get("date_released_unix") or 0,
        "hash": t["hash"],
        "magnet": _magnet(t["hash"], filename, t.get("magnet_url") or ""),
        "torrent_url": t.get("torrent_url") or "",
        "season": t.get("season"),
        "episode": t.get("episode"),
        "imdb": t.get("imdb_id") or "",
        "show": t.get("title") or "",
    }


def latest(limit: int = 30, max_pages: int = 2) -> list[dict]:
    """Newest episode uploads across all shows (sorted: newest first)."""
    bases = [_base()] + [b for b in MIRRORS if b != _base()]
    for base in bases:
        out = []
        try:
            for page in range(1, max_pages + 1):
                r = scraper.get(
                    base + "/api/get-torrents",
                    params={"limit": 100, "page": page},
                    timeout=15,
                )
                if r.status_code != 200:
                    break
                batch = (r.json().get("torrents") or [])
                if not batch:
                    break
                for t in batch:
                    c = _clean(t)
                    if c:
                        c["show"] = t.get("title") or ""
                        out.append(c)
                if len(batch) < 100:
                    break
            if out:
                out.sort(key=lambda x: x.get("date") or 0, reverse=True)
                return out[:limit]
        except Exception:
            continue
    return []


def episode_torrents(imdb_id: str, season: int, episode: int,
                     limit: int = 100, max_pages: int = 5) -> list[dict]:
    """All releases for one S/E (sorted: seeds desc). Never raises.

    NOTE: the API ignores the imdb_id filter, so pages are scanned and
    matched client-side (imdb numbers compared digit-wise).
    """
    want = "".join(c for c in str(imdb_id or "") if c.isdigit()).lstrip("0")
    if not want:
        return []
    bases = [_base()] + [b for b in MIRRORS if b != _base()]
    for base in bases:
        out = []
        try:
            for page in range(1, max_pages + 1):
                r = scraper.get(
                    base + "/api/get-torrents",
                    params={"imdb_id": imdb_id, "limit": limit, "page": page},
                    timeout=15,
                )
                if r.status_code != 200:
                    break
                batch = (r.json().get("torrents") or [])
                if not batch:
                    break
                for t in batch:
                    if "".join(c for c in str(t.get("imdb_id"))
                               if c.isdigit()).lstrip("0") != want:
                        continue
                    try:
                        if int(t.get("season") or -1) != int(season):
                            continue
                        if int(t.get("episode") or -1) != int(episode):
                            continue
                    except (TypeError, ValueError):
                        continue
                    c = _clean(t)
                    if c:
                        out.append(c)
                if len(batch) < limit:
                    break
            if out:
                out.sort(key=lambda x: x["seeds"], reverse=True)
                return out
        except Exception:
            continue
    return []
