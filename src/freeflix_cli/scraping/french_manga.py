"""
French-Manga (french-manga.net) scraper — an anime-focused DLE site.

Flow :
  search()        POST /engine/ajax/search.php  → result cards
  get_episodes()  page → newsId → GET /engine/ajax/manga_episodes_api.php?id=…
                  which returns {"vf": {ep: {host: embed}}, "vostfr": {…}, …}

Players are plain host→embed maps (vidzy, luluvid, …) resolved by the
shared player.get_hls_link extractors.
"""

import re
from curl_cffi import requests as cffi_requests
from .objects import SearchResult, Player
from ..proxy import DNS_OPTIONS
from .config import portals

website_origin = portals.get("french-manga", "https://w16.french-manga.net").rstrip("/")

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)


def _ajax_headers():
    return {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": website_origin + "/",
    }


def search(query: str) -> list:
    """Search via the DLE ajax endpoint. Returns a list of SearchResult."""
    try:
        r = scraper.post(
            f"{website_origin}/engine/ajax/search.php",
            data={"query": query},
            headers=_ajax_headers(),
            timeout=15,
        )
    except Exception:
        return []

    results = []
    # Each card : <div class='search-item' onclick="location.href='/NNN-…html'">
    #               … <div class='search-title'>Title (Year)</div>
    for m in re.finditer(
        r"location\.href='([^']+)'.*?search-title[^>]*>([^<]+)",
        r.text,
        re.DOTALL,
    ):
        url, title = m.group(1), m.group(2).strip()
        if not url.startswith("http"):
            url = website_origin + url
        results.append(SearchResult(title, url, "", []))
    return results


def _abs_url(url: str) -> str:
    """Make a possibly-relative URL absolute against website_origin.

    Older history entries stored relative URLs (e.g. '/1498-foo.html'),
    which curl can't fetch directly. Normalise them here so resume works.
    """
    if not url:
        return url
    if url.startswith("http"):
        return url
    return website_origin + "/" + url.lstrip("/")


def _extract_news_id(html: str):
    for pat in (r'data-newsid="(\d+)"', r'data-news-id="(\d+)"', r'newsid=(\d+)'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def get_episodes(url: str) -> dict:
    """
    Return {"title": str, "vf": {ep_num: [Player,…]}, "vostfr": {…}}.
    Episode numbers are strings ("1", "2", …) as returned by the API.
    """
    out = {"title": "", "vf": {}, "vostfr": {}}
    url = _abs_url(url)
    try:
        page = scraper.get(url, timeout=20)
        news_id = _extract_news_id(page.text)
        if not news_id:
            return out

        api = scraper.get(
            f"{website_origin}/engine/ajax/manga_episodes_api.php?id={news_id}",
            headers=_ajax_headers(),
            timeout=15,
        )
        data = api.json()
    except Exception:
        return out

    info = data.get("info") or {}
    out["title"] = info.get("title", "") if isinstance(info, dict) else ""

    for lang in ("vf", "vostfr"):
        ep_map = data.get(lang) or {}
        if not isinstance(ep_map, dict):
            continue
        for ep_num, players_dict in ep_map.items():
            if not isinstance(players_dict, dict):
                continue
            players = [
                Player(host, embed)
                for host, embed in players_dict.items()
                if embed
            ]
            if players:
                out[lang][ep_num] = players
    return out
