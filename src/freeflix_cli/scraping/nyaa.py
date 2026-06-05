"""
Minimal HTML scraper for nyaa.si.

Returns a list of dicts (title, size, seeders, leechers, magnet, page_url)
for the top results of a search query.
"""

from typing import List, Dict
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from .. import cloudflare

NYAA_BASE = "https://nyaa.si"


def search(query: str, max_results: int = 25) -> List[Dict]:
    """
    Search nyaa.si by free-text query, ordered by seeders desc.
    """
    if not query.strip():
        return []

    url = f"{NYAA_BASE}/?f=0&c=0_0&q={quote_plus(query)}&s=seeders&o=desc"
    try:
        r = cloudflare.cf_get(cffi_requests, url, impersonate="chrome", timeout=15)
        r.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "html5lib")
    table = soup.find("table", class_="torrent-list")
    if not table:
        return []

    out: List[Dict] = []
    rows = table.find("tbody")
    if not rows:
        return []

    for tr in rows.find_all("tr", recursive=False)[:max_results]:
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 8:
            continue

        # Name cell holds one or two links; the title is the last <a> that
        # does not point to /view/ comments fragment.
        name_links = tds[1].find_all("a")
        name_link = None
        for a in name_links:
            href = a.get("href", "")
            if href.startswith("/view/") and "#comments" not in href:
                name_link = a
        if not name_link:
            continue

        title = name_link.get_text(strip=True)
        page_url = NYAA_BASE + name_link["href"]

        # Magnet is in tds[2] — second link
        magnet = None
        for a in tds[2].find_all("a"):
            href = a.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
                break
        if not magnet:
            continue

        size = tds[3].get_text(strip=True)
        seeders = tds[5].get_text(strip=True)
        leechers = tds[6].get_text(strip=True)

        try:
            seeders_n = int(seeders)
        except ValueError:
            seeders_n = 0

        out.append(
            {
                "title": title,
                "size": size,
                "seeders": seeders_n,
                "leechers": leechers,
                "magnet": magnet,
                "page_url": page_url,
            }
        )

    return out
