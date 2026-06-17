from bs4 import BeautifulSoup
from .objects import (
    SearchResult,
    FrenchStreamMovie,
    Player,
    FrenchStreamSeason,
    Episode,
)

from curl_cffi import requests as cffi_requests
from ..proxy import DNS_OPTIONS

from .config import portals

website_origin = portals["french-stream"]
if not website_origin.startswith("http"):
    website_origin = "https://" + website_origin

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)



from .. import cloudflare


def _get(url, **kw):
    """Cloudflare-aware GET (cf_clearance + FlareSolverr cascade)."""
    return cloudflare.cf_get(scraper, url, **kw)


def _post(url, data=None, **kw):
    """Cloudflare-aware POST — handles both standard Cloudflare challenges
    (cf_clearance + FlareSolverr cascade) and the custom JS challenge used
    by french-stream.one which sets a ``fsschal=1`` cookie."""
    base_headers = kw.pop("headers", {})

    def _headers():
        cf = cloudflare.get_cf_headers(url)
        return {**cf, **base_headers} if cf else dict(base_headers)

    def _fetch():
        h = _headers()
        return scraper.post(url, data=data, headers=h, **kw) if h else scraper.post(url, data=data, **kw)

    resp = _fetch()

    # Detect challenge page (status 200 JS challenge with fsschal)
    need_retry = False
    try:
        body = (resp.text or "").lower()
        if not cloudflare.is_blocked(resp) and "verification" in body and "anti-robot" in body:
            scraper.cookies.set("fsschal", "1", domain="french-stream.one", path="/")
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


def search(query: str) -> list[SearchResult]:
    page_search = "/engine/ajax/search.php"

    data = {
        "query": query,
        "page": 1,
    }

    headers = {
        "Referer": f"{website_origin}/",
    }

    response = _post(
        website_origin + page_search,
        data=data,
        headers=headers,
        timeout=15,
    )

    response.raise_for_status()

    results: list[SearchResult] = []

    soup = BeautifulSoup(response.text, "html5lib")

    for result in soup.find_all("div", {"class": "search-item"}):
        try:
            title: str = result.find("div", {"class": "search-title"}).text
        except AttributeError:
            break  # no results

        link: str = (
            website_origin
            + result.attrs["onclick"].split("location.href='")[1].split("'")[0]
        )
        try:
            img: str = _abs_img(result.find("img").attrs["src"])
        except AttributeError:
            img: str = ""  # no image

        genres: list[str] = []  # unknow

        results.append(SearchResult(title, link, img, genres))

    return results


def get_movie(url: str, content: str) -> FrenchStreamMovie:
    soup = BeautifulSoup(content, "html5lib")

    title: str = soup.find("meta", {"property": "og:title"}).attrs["content"]

    img: str = ""
    try:
        img: str = _abs_img(soup.find("img", {"class": "dvd-thumbnail"}).attrs["src"])
    except AttributeError:
        img: str = ""
    genres: list[str] = []
    genres_div = soup.find("ul", {"id": "s-list"}).find_all("li")[1]
    if genres_div is not None:
        for genre in genres_div.find_all("a"):
            if genre.text:
                genres.append(genre.text)

    players: list[Player] = []
    movie_id = url.split("/")[-1].split("-")[0]

    movie_info_response = _get(
        f"{website_origin}/engine/ajax/film_api.php?id={movie_id}"
    )
    movie_info_response.raise_for_status()

    movie_info = movie_info_response.json()

    for player_name, player_links in movie_info["players"].items():
        for lang, link in player_links.items():
            players.append(Player(player_name + " " + lang, link))

    return FrenchStreamMovie(title, url, img, genres, players)


def get_series_season(url: str, content: str) -> FrenchStreamSeason:
    soup = BeautifulSoup(content, "html5lib")

    title: str = soup.find("meta", {"property": "og:title"}).attrs["content"]
    serie_id = url.split("/")[-1].split("-")[0]

    serie_info_response = _get(
        f"{website_origin}/ep-data.php?id={serie_id}"
    )
    serie_info_response.raise_for_status()

    serie_info = serie_info_response.json()

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
    episodes_raw = serie_info[lang]
    episodes: list[Episode] = []

    for number, players_raw in episodes_raw.items():
        players: list[Player] = []
        for player_name, link in players_raw.items():
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
    # print(search("Mercredi"))
    # print(
    #     get_movie(
    #         "https://french-stream.one/films/13448-la-soupe-aux-choux-film-streaming-complet-vf.html"
    #     )
    # )
    print(
        get_series_season(
            "https://french-stream.one/s-tv/15112935-mercredi-saison-1.html"
        )
    )
