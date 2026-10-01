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
from ..net_config import DNS_OPTIONS
from .config import portals

website_origin = portals.get("french-manga", "https://w16.french-manga.net").rstrip("/")

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)



from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)


def _get(url, **kw):
    """Cloudflare-aware GET (cf_clearance + FlareSolverr cascade)."""
    return cloudflare.cf_get(scraper, url, **kw)

def _ajax_headers():
    return {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": website_origin + "/",
    }


def _post(url, data=None, **kw):
    """POST avec les headers cf_clearance éventuels (sinon Cloudflare 403
    → recherche vide sans diagnostic)."""
    base_headers = kw.pop("headers", {})
    try:
        cf = cloudflare.get_cf_headers(url)
        headers = {**cf, **base_headers} if cf else dict(base_headers)
    except Exception:
        headers = dict(base_headers)
    kw.setdefault("timeout", 15)
    return scraper.post(url, data=data, headers=headers, **kw)


def search(query: str) -> list:
    """Search via the DLE ajax endpoint. Returns a list of SearchResult."""
    try:
        r = _post(
            f"{website_origin}/engine/ajax/search.php",
            data={"query": query},
            headers=_ajax_headers(),
        )
        r.raise_for_status()
    except Exception:
        return []

    from .utils import parse_html
    results = []
    # Par carte (BeautifulSoup) plutôt qu'une regex DOTALL inter-cartes qui
    # mélangeait les posters quand une carte n'avait pas de titre.
    soup = parse_html(r.text)
    for card in soup.find_all("div", {"class": "search-item"}):
        onclick = card.attrs.get("onclick", "")
        m = re.search(r"location\.href='([^']+)'", onclick)
        if not m:
            continue
        url = m.group(1)
        if not url.startswith("http"):
            url = website_origin + url
        title_tag = card.find("div", {"class": "search-title"})
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            continue
        # Pull the card's poster (TMDB thumbnail) so the preview pane has a cover.
        img = ""
        img_tag = card.find("img")
        if img_tag:
            img = img_tag.attrs.get("src", "") or ""
            if img.startswith("//"):
                img = "https:" + img
            elif img.startswith("/"):
                img = website_origin + img
        results.append(SearchResult(title, url, img, []))
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


def _extract_cover(html: str) -> str:
    """Grab the poster URL from the series page (og:image, TMDB, or fposter)."""
    # 1. og:image meta (some DLE skins have it)
    m = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        html,
    )
    if m:
        return _abs_url(m.group(1))
    # 2. TMDB poster (this skin uses image.tmdb.org/t/p/wNNN/…)
    m = re.search(
        r'https?://image\.tmdb\.org/t/p/w\d+/[^"\'\s>]+\.(?:jpg|jpeg|png)',
        html,
    )
    if m:
        return m.group(0)
    # 3. First <img> inside the .fposter block
    m = re.search(
        r'class=["\']fposter["\'][^>]*>\s*<img[^>]+src=["\']([^"\']+)',
        html,
        re.DOTALL,
    )
    if m:
        return _abs_url(m.group(1))
    return ""


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
    out = {"title": "", "cover": "", "vf": {}, "vostfr": {}}
    url = _abs_url(url)
    try:
        page = _get(url, timeout=20)
        out["cover"] = _extract_cover(page.text)
        news_id = _extract_news_id(page.text)
        if not news_id:
            return out

        api = _get(
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
                if isinstance(embed, str) and embed.strip()
            ]
            if players:
                out[lang][ep_num] = players
    return out
