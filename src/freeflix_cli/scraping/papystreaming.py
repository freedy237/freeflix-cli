"""
Papystreaming — French movie/series catalog.

Papystreaming is a TMDB-based French site : every title lives at
``/movie/<tmdb_id>`` or ``/tv/<tmdb_id>``. Its own player is JS-rendered (not
scrapable without a browser), but since it hands us the TMDB id we resolve the
actual stream through the shared GoldenMS extractors (Vidlink/Hexa/…) — so this
source gives a clean **French search** on top of the proven resolvers.

``search()`` returns a list of dicts :
    {"title", "tmdb_id", "media_type" ("movie"|"tv"), "poster", "year"}
"""

from __future__ import annotations

import re
import urllib.parse

from curl_cffi import requests as cffi_requests
from ..net_config import DNS_OPTIONS
from bs4 import BeautifulSoup
from .config import portals

# Portail hot-patchable (changement de miroir sans release), comme les
# autres scrapers — avec le domaine actuel en repli.
BASE = portals.get("papystreaming", "https://papystreaming.fr").rstrip("/")
scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_CARD = re.compile(r"/(movie|tv)/(\d+)(?:[/?#]|$)")


def _title_year(anchor, img) -> tuple[str, str]:
    """Clean title + year from a result card. The anchor text reads like
    'Film 8.2 Matrix 1999' ; the <img alt> holds the clean title."""
    raw = anchor.get_text(" ", strip=True)
    year_m = _YEAR.search(raw)
    year = year_m.group(0) if year_m else ""

    title = (img.get("alt") or "").strip() if img else ""
    if not title:
        # Fallback : strip the 'Film 8.2 ' / 'Série 6.1 ' prefix and the year.
        title = re.sub(r"^(?:Film|S[ée]rie)\s+[\d.]+\s*", "", raw)
        title = _YEAR.sub("", title).strip(" -·")
    return title, year


def search(query: str) -> list[dict]:
    """Search Papystreaming. Returns [] on any network/parse error."""
    from .. import cloudflare
    try:
        r = cloudflare.cf_get(
            scraper,
            BASE + "/search?q=" + urllib.parse.quote(query),
            headers={"Referer": BASE + "/"},
            timeout=15,
        )
        if r is None:
            return []
        r.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(r.text or "", "html.parser")
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for a in soup.find_all("a", href=True):
        m = _CARD.search(a["href"])
        if not m:
            continue
        media_type, tmdb_id = m.group(1), m.group(2)
        key = (media_type, tmdb_id)
        if key in seen:
            continue

        img = a.find("img")
        title, year = _title_year(a, img)
        if not title:
            continue

        poster = ""
        if img:
            poster = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if poster.startswith("//"):
                poster = "https:" + poster
            elif poster and not poster.startswith("http"):
                poster = BASE + "/" + poster.lstrip("/")

        seen.add(key)
        results.append({
            "title": title,
            "tmdb_id": int(tmdb_id),
            "media_type": media_type,
            "poster": poster,
            "year": year,
        })
    return results
