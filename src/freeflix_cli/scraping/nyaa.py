from .utils import parse_html
"""
Minimal HTML scraper for nyaa.si.

Returns a list of dicts (title, size, seeders, leechers, magnet, page_url)
for the top results of a search query.
"""

from typing import List, Dict
from urllib.parse import quote_plus, urljoin
from curl_cffi import requests as cffi_requests
from ..net_config import shared_session
from .. import cloudflare

NYAA_BASE = "https://nyaa.si"


def _session():
    """Session persistante (cf_clearance conservé) ; repli module nu."""
    try:
        return shared_session()
    except Exception:
        return cffi_requests


def search(query: str, max_results: int = 25) -> List[Dict]:
    """
    Search nyaa.si by free-text query, ordered by seeders desc.
    """
    if not query.strip():
        return []

    url = f"{NYAA_BASE}/?f=0&c=0_0&q={quote_plus(query)}&s=seeders&o=desc"
    try:
        r = cloudflare.cf_get(_session(), url, impersonate="chrome", timeout=15)
        if r is None:
            return []
        r.raise_for_status()
    except Exception:
        return []

    soup = parse_html(r.text)
    table = soup.find("table", class_="torrent-list")
    if not table:
        return []

    out: List[Dict] = []
    rows = table.find("tbody") or table  # thead/tbody parfois absents
    if not rows:
        return []
    rows = rows.find_all("tr", recursive=False) or []

    # Mappe les colonnes via l'en-tête quand présent (taille/seeders/
    # leechers), sinon positions historiques 3/5/6.
    col_idx = {"size": 3, "seeders": 5, "leechers": 6}
    try:
        head = table.find("thead")
        ths = head.find_all("th") if head else []
        names = [th.get_text(strip=True).lower() for th in ths]
        for key, words in (("size", ("size", "taille")),
                           ("seeders", ("seeder",)),
                           ("leechers", ("leecher",))):
            for i, n in enumerate(names):
                if any(w in n for w in words):
                    col_idx[key] = i
                    break
    except Exception:
        pass

    need = max(col_idx.values(), default=6) + 1
    for tr in rows[:max_results]:
        tds = tr.find_all("td", recursive=False)
        if len(tds) < need:
            continue

        # Name cell holds one or two links; the title is the last <a> that
        # does not point to /view/ comments fragment (relatif ou absolu).
        name_links = tds[1].find_all("a")
        name_link = None
        for a in name_links:
            href = a.get("href", "")
            if "/view/" in href and "#comments" not in href:
                name_link = a
        if not name_link:
            continue

        title = name_link.get_text(strip=True)
        page_url = urljoin(NYAA_BASE + "/", name_link.get("href", ""))

        # Magnet is in tds[2] — second link
        magnet = None
        for a in tds[2].find_all("a"):
            href = a.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
                break
        if not magnet:
            continue

        size = tds[col_idx["size"]].get_text(strip=True)
        seeders = tds[col_idx["seeders"]].get_text(strip=True)
        leechers = tds[col_idx["leechers"]].get_text(strip=True)

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
