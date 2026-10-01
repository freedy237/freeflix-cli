from .objects import (
    SearchResult,
    FrenchStreamMovie,
    Player,
    FrenchStreamSeason,
    Episode,
)
from .utils import parse_html

from curl_cffi import requests as cffi_requests, CurlOpt
from ..net_config import DNS_OPTIONS

from .config import portals

website_origin = portals["french-stream"]
if not website_origin.startswith("http"):
    website_origin = "https://" + website_origin

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

_DOH_SESSION = None

def _doh_session():
    global _DOH_SESSION
    if _DOH_SESSION is None:
        _DOH_SESSION = cffi_requests.Session(
            impersonate="chrome",
            curl_options={
                CurlOpt.DOH_URL: "https://1.1.1.1/dns-query",
                CurlOpt.DOH_SSL_VERIFYPEER: 0,
                CurlOpt.DOH_SSL_VERIFYHOST: 0,
                CurlOpt.CONNECTTIMEOUT: 15,
            },
        )
    return _DOH_SESSION



from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)


def _get(url, **kw):
    """Cloudflare-aware GET (cf_clearance + FlareSolverr cascade).

    Also detects the french-stream.one JS challenge (status 200 with
    ``verification`` + ``anti-robot`` in the body) and retries with the
    ``fsschal=1`` cookie set, same as `_post`.

    Falls back to DNS-over-HTTPS (1.1.1.1) when the system DNS fails."""
    from time import sleep as _sl

    base_headers = kw.pop("headers", {})

    def _headers():
        cf = cloudflare.get_cf_headers(url)
        return {**cf, **base_headers} if cf else dict(base_headers)

    def _fetch(session=None):
        s = session or scraper
        h = _headers()
        return s.get(url, headers=h, **kw) if h else s.get(url, **kw)

    try:
        resp = cloudflare.cf_get(scraper, url, headers=base_headers, **kw)
    except Exception:
        resp = _fetch(_doh_session())

    need_retry = False
    try:
        body = (resp.text or "").lower()
        if not cloudflare.is_blocked(resp) and "verification" in body and "anti-robot" in body:
            try:
                import urllib.parse as _up
                host = _up.urlparse(website_origin).hostname or _up.urlparse(url).hostname or ""
            except Exception:
                host = ""
            scraper.cookies.set("fsschal", "1", domain=host, path="/")
            need_retry = True
    except Exception:
        pass

    if need_retry:
        _sl(0.5)
        resp = _fetch()

    return resp


def _post(url, data=None, **kw):
    """Cloudflare-aware POST — handles both standard Cloudflare challenges
    (cf_clearance + FlareSolverr cascade) and the custom JS challenge used
    by french-stream.one which sets a ``fsschal=1`` cookie.

    Falls back to DNS-over-HTTPS (1.1.1.1) when the system DNS fails."""
    base_headers = kw.pop("headers", {})

    def _headers():
        cf = cloudflare.get_cf_headers(url)
        return {**cf, **base_headers} if cf else dict(base_headers)

    def _fetch(session=None):
        s = session or scraper
        h = _headers()
        return s.post(url, data=data, headers=h, **kw) if h else s.post(url, data=data, **kw)

    try:
        resp = _fetch()
    except Exception:
        resp = _fetch(_doh_session())

    # Detect challenge page (status 200 JS challenge with fsschal)
    need_retry = False
    try:
        body = (resp.text or "").lower()
        if not cloudflare.is_blocked(resp) and "verification" in body and "anti-robot" in body:
            try:
                import urllib.parse as _up
                host = _up.urlparse(website_origin).hostname or _up.urlparse(url).hostname or ""
            except Exception:
                host = ""
            scraper.cookies.set("fsschal", "1", domain=host, path="/")
            need_retry = True
    except Exception:
        pass

    if need_retry:
        resp = _fetch()

    return resp

def _abs_img(src: str) -> str:
    """Resolve an <img> src : leave absolute URLs (e.g. TMDB) untouched,
    prefix the site origin only for relative paths."""
    if not src:
        return ""
    if src.startswith("http") or src.startswith("//"):
        return src
    return website_origin + "/" + src.lstrip("/")


# Hosts verified dead (Sept 2026) — filtered so menus only offer working
# players instead of entries that can never resolve :
#   * trakx.lol (old dood/voe proxy) : "No video found with that id" / timeouts
#   * multiup.us (netu) : ad-wall redirector, no static stream + movie entries
#     are short codes, not URLs
#   * bysesayeveum.com (filemoon "Byse Frontend" SPA) : client-side rendered,
#     no static stream to extract — same for the kokoflix chamber_go.php
#     endpoint, which always lands on that SPA (tokyo_go→dood and
#     rosewood_go→voe are both supported, chamber_go never is)
_DEAD_PLAYER_HOSTS = ("trakx.lol", "multiup.us", "multiup.io", "bysesayeveum.com")
_DEAD_PLAYER_PATHS = ("chamber_go.php",)


def _is_usable_player_link(link: str) -> bool:
    """True if a player link is a fetchable http(s) URL on a live host."""
    if not link or not isinstance(link, str):
        return False
    import urllib.parse as _up
    low = link.strip().lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return False  # e.g. netu short codes
    # Hosts morts jugés sur le HOSTNAME seul : ?x=trakx.lol ne doit pas
    # disqualifier un host valide.
    try:
        host = _up.urlparse(low).hostname or ""
    except Exception:
        return False
    if any(h in host for h in _DEAD_PLAYER_HOSTS):
        return False
    return not any(p in low for p in _DEAD_PLAYER_PATHS)


def search(query: str) -> list[SearchResult]:
    page_search = "/engine/ajax/search.php"

    data = {
        "query": query,
        "page": 1,
    }

    headers = {
        "Referer": f"{website_origin}/",
    }

    try:
        response = _post(
            website_origin + page_search,
            data=data,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
    except Exception:
        return []

    results: list[SearchResult] = []

    soup = parse_html(response.text)

    for result in soup.find_all("div", {"class": "search-item"}):
        try:
            title: str = result.find("div", {"class": "search-title"}).text
        except AttributeError:
            continue  # carte promo sans titre : on saute, pas tout le reste

        onclick = result.attrs.get("onclick", "")
        if "location.href='" not in onclick:
            continue
        link: str = (
            website_origin
            + onclick.split("location.href='")[1].split("'")[0]
        )
        try:
            img_tag = result.find("img")
            img: str = _abs_img((img_tag.attrs.get("src") or "") if img_tag else "")
        except AttributeError:
            img: str = ""  # no image

        genres: list[str] = []  # unknow

        results.append(SearchResult(title, link, img, genres))

    return results


def get_movie(url: str, content: str) -> FrenchStreamMovie:
    soup = parse_html(content)

    og = soup.find("meta", {"property": "og:title"})
    if og and og.attrs.get("content"):
        title = og.attrs["content"]
    else:
        title = soup.title.get_text(strip=True) if soup.title else url.rstrip("/").split("/")[-1].replace("-", " ").title()

    img: str = ""
    try:
        img: str = _abs_img(soup.find("img", {"class": "dvd-thumbnail"}).attrs["src"])
    except AttributeError:
        img: str = ""
    genres: list[str] = []
    slist = soup.find("ul", {"id": "s-list"})
    if slist:
        li_tags = slist.find_all("li")
        if len(li_tags) > 1:
            for genre in li_tags[1].find_all("a"):
                if genre.text:
                    genres.append(genre.text)

    players: list[Player] = []
    movie_id = url.rstrip("/").split("/")[-1].split("-")[0]

    try:
        movie_info_response = _get(
            f"{website_origin}/engine/ajax/film_api.php?id={movie_id}",
            timeout=15,
        )
        movie_info_response.raise_for_status()
        movie_info = movie_info_response.json()
    except Exception:
        return FrenchStreamMovie(title, url, img, genres, players)

    raw_players = movie_info.get("players") if isinstance(movie_info, dict) else None
    if not isinstance(raw_players, dict):
        return FrenchStreamMovie(title, url, img, genres, players)
    for player_name, player_links in raw_players.items():
        if not isinstance(player_links, dict):
            continue
        for lang, link in player_links.items():
            if not _is_usable_player_link(link):
                continue  # dead host (trakx/netu) or non-URL code
            players.append(Player(player_name + " " + lang, link))

    return FrenchStreamMovie(title, url, img, genres, players)


def get_series_season(url: str, content: str) -> FrenchStreamSeason:
    soup = parse_html(content)

    og = soup.find("meta", {"property": "og:title"})
    if og and og.attrs.get("content"):
        title = og.attrs["content"]
    else:
        title = soup.title.get_text(strip=True) if soup.title else url.rstrip("/").split("/")[-1].replace("-", " ").title()
    serie_id = url.rstrip("/").split("/")[-1].split("-")[0]

    try:
        serie_info_response = _get(
            f"{website_origin}/ep-data.php?id={serie_id}",
            timeout=15,
        )
        serie_info_response.raise_for_status()
        serie_info = serie_info_response.json()
    except Exception:
        return FrenchStreamSeason(title, url, {})
    if not isinstance(serie_info, dict):
        return FrenchStreamSeason(title, url, {})

    episodes: dict[str, list[Episode]] = {}

    voEpisodes = get_episodes_from_lang("vo", serie_info)
    if voEpisodes:
        episodes["vo"] = voEpisodes

    vostfrEpisodes = get_episodes_from_lang("vostfr", serie_info)
    if vostfrEpisodes:
        episodes["vostfr"] = vostfrEpisodes

    vfEpisodes = get_episodes_from_lang("vf", serie_info)
    if vfEpisodes:
        episodes["vf"] = vfEpisodes

    return FrenchStreamSeason(title, url, episodes)


def get_episodes_from_lang(lang: str, serie_info: dict):
    episodes_raw = (serie_info or {}).get(lang) or {}
    if not isinstance(episodes_raw, dict):
        return []
    episodes: list[Episode] = []

    for number, players_raw in episodes_raw.items():
        players: list[Player] = []
        for player_name, link in players_raw.items():
            if not _is_usable_player_link(link):
                continue  # dead host (trakx/netu) or non-URL code
            players.append(Player(player_name, link))

        episode = Episode(f"Episode {number}", players)
        episodes.append(episode)

    return episodes


def get_content(url: str):
    response = _get(url)
    response.raise_for_status()
    content = response.text

    if '"episodes-' in content:
        return get_series_season(url, content)
    return get_movie(url, content)


if __name__ == "__main__":
    print(
        get_series_season(
            "https://french-stream.one/s-tv/15112935-mercredi-saison-1.html"
        )
    )
