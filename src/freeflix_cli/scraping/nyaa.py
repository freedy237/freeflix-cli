"""
HTML scraper for nyaa.si (anime-first).

Returns a list of dicts (title, size, size_bytes, quality, seeders,
leechers, trusted, date, magnet, page_url, torrent_id, torrent_url)
for the top results of a search query, ordered by seeders desc.

Backward compatible: the historical keys (title, size, seeders,
leechers, magnet, page_url) keep the exact same meaning as before.
"""

from typing import List, Dict, Optional
import logging
import re
from urllib.parse import quote_plus, urljoin
from curl_cffi import requests as cffi_requests
from ..net_config import shared_session
from .. import cloudflare
from .utils import parse_html

log = logging.getLogger("freeflix.nyaa")

NYAA_BASE = "https://nyaa.si"
SUKEBEI_BASE = "https://sukebei.nyaa.si"

# Nyaa search categories (c= param). Anime-first defaults.
CATEGORIES = {
    "anime": "1_0",      # Anime — all
    "english": "1_2",    # Anime — English-translated
    "non_english": "1_3",
    "raw": "1_4",        # Anime — Raw
    "manga": "3_0",      # Manga — all
    "all": "0_0",        # Everything (old behaviour)
}

# Nyaa result filters (f= param).
FILTER_NONE = 0
FILTER_NO_REMAKES = 1
FILTER_TRUSTED_ONLY = 2

# Last human-readable failure reason (network error, layout change…).
# The handler reads it to explain empty results instead of a bare "No results".
last_error: Optional[str] = None

_SIZE_RE = re.compile(r"^([\d.]+)\s*(GiB|MiB|KiB|B)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_QUALITY_RES = (
    ("2160p", re.compile(r"2160p|4k|uhd", re.I)),
    ("1080p", re.compile(r"1080p|1920x1080|FHD", re.I)),
    ("720p", re.compile(r"720p|1280x720|HD(?:TV|Rip)?\b", re.I)),
    ("480p", re.compile(r"480p|848x480|SDTV|HDTV-480p", re.I)),
    ("DVD", re.compile(r"\bDVD(?:Rip)?\b|DVDR|DVD5|DVD9", re.I)),
)
_SIZE_MULT = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}


def _session():
    """Session persistante (cf_clearance conservé) ; repli module nu."""
    try:
        return shared_session()
    except Exception:
        return cffi_requests


def size_to_bytes(size: str) -> int:
    """'133.3 GiB' -> bytes. Unknown format -> 0."""
    m = _SIZE_RE.match((size or "").strip())
    if not m:
        return 0
    try:
        return int(float(m.group(1)) * _SIZE_MULT[m.group(2)])
    except (ValueError, KeyError):
        return 0


def detect_quality(title: str) -> str:
    """Best-effort quality tag from a release title ('1080p', '720p'…)."""
    t = title or ""
    if re.search(r"\bBD\b|Blu-?Ray|BDMV|BDREMUX", t, re.I):
        for q, rx in _QUALITY_RES[:4]:
            if rx.search(t):
                return q
        return "BD"
    for q, rx in _QUALITY_RES:
        if rx.search(t):
            return q
    return "?"


def search(
    query: str,
    max_results: int = 25,
    category: str = "anime",
    trusted_only: bool = False,
    min_seeders: int = 0,
    page: int = 0,
) -> List[Dict]:
    """
    Search nyaa.si by free-text query, ordered by seeders desc.

    :param category: one of 'anime' (default), 'english', 'non_english',
        'raw', 'manga', 'all'.
    :param trusted_only: only green/trusted uploads (f=2).
    :param min_seeders: drop results below this seeder count.
    :param page: result page (0-based, appended as &p= when > 0).
    """
    global last_error
    last_error = None
    if not query.strip():
        return []

    cat = CATEGORIES.get(category, CATEGORIES["anime"])
    filt = FILTER_TRUSTED_ONLY if trusted_only else FILTER_NONE
    url = (f"{NYAA_BASE}/?f={filt}&c={cat}&q={quote_plus(query)}"
           f"&s=seeders&o=desc")
    if page > 0:
        url += f"&p={page + 1}"
    return _fetch_list(url, query, max_results, min_seeders)


def latest(category: str = "anime", max_results: int = 25) -> List[Dict]:
    """Newest uploads (browse view, sorted by upload order).

    NOTE: Nyaa has no `s=date` sort (400) — upload order is `s=id`.
    """
    global last_error
    last_error = None
    cat = CATEGORIES.get(category, CATEGORIES["anime"])
    url = f"{NYAA_BASE}/?f=0&c={cat}&s=id&o=desc"
    return _fetch_list(url, "(latest)", max_results, 0)


def _fetch_list(url: str, query: str, max_results: int,
               min_seeders: int) -> List[Dict]:
    """GET a nyaa list page URL and parse its torrent table."""
    global last_error
    last_error = None
    try:
        r = cloudflare.cf_get(_session(), url, impersonate="chrome", timeout=15)
        if r is None:
            last_error = "network error (no response)"
            return []
        r.raise_for_status()
    except Exception as e:
        last_error = f"network error ({e})"
        log.warning("nyaa fetch failed for %r: %s", query, e)
        return []

    try:
        soup = parse_html(r.text)
    except Exception as e:
        last_error = f"parse error ({e})"
        return []
    table = soup.find("table", class_="torrent-list")
    if not table:
        # Nyaa shows no table at all when there are zero hits — that is a
        # legitimate empty result, not a layout change.
        if "Nothing found" in (r.text or "") or "No results" in (r.text or ""):
            return []
        last_error = "layout change (torrent table not found)"
        log.warning("nyaa layout change? no table.torrent-list for %r", query)
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
    for tr in rows:
        if len(out) >= max_results:
            break
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
        # The header row uses colspans, so the header-text mapping can land
        # one column off (size ← date). Detect by content instead : a real
        # size looks like "9.7 GiB", a date like "2025-03-26 06:54".
        if not _SIZE_RE.match(size):
            for _td in tds[2:6]:
                _txt = _td.get_text(strip=True)
                if _SIZE_RE.match(_txt):
                    size = _txt
                    break
        seeders = tds[col_idx["seeders"]].get_text(strip=True)
        leechers = tds[col_idx["leechers"]].get_text(strip=True)
        date = ""
        for _td in tds[2:6]:
            _txt = _td.get_text(strip=True)
            if _DATE_RE.match(_txt):
                date = _txt.split(" ")[0]
                break

        try:
            seeders_n = int(seeders)
        except ValueError:
            seeders_n = 0
        try:
            leechers_n = int(leechers)
        except ValueError:
            leechers_n = 0

        if seeders_n < min_seeders:
            continue

        # Trusted badge : nyaa marque la ligne en vert (class "success").
        try:
            _cls = tr.get("class") or []
            trusted = "success" in _cls
            remake = "danger" in _cls
        except Exception:
            trusted = False
            remake = False

        m = re.search(r"/view/(\d+)", page_url)
        torrent_id = m.group(1) if m else None
        torrent_url = (f"{NYAA_BASE}/download/{torrent_id}.torrent"
                       if torrent_id else None)

        out.append(
            {
                "title": title,
                "size": size,
                "size_bytes": size_to_bytes(size),
                "quality": detect_quality(title),
                "seeders": seeders_n,
                "leechers": leechers_n,
                "trusted": trusted,
                "remake": remake,
                "date": date,
                "magnet": magnet,
                "page_url": page_url,
                "torrent_id": torrent_id,
                "torrent_url": torrent_url,
            }
        )

    return out
