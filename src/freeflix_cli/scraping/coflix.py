from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from .objects import (
    SearchResult,
    CoflixSeason,
    CoflixSeries,
    SeasonAccess,
    EpisodeAccess,
    Episode,
    Player,
    CoflixMovie,
)
import base64
import re
from ..proxy import DNS_OPTIONS

website_origin = ""
scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

from .. import cloudflare


def _get(url, **kw):
    """
    GET that rides a cf_clearance cookie if set, and — on a Cloudflare block
    — asks FlareSolverr to auto-solve the challenge, then retries once.
    Cascade : curl_cffi → FlareSolverr → manual cf_clearance → block message.
    """
    base_headers = kw.pop("headers", {})

    def _fetch():
        cf = cloudflare.get_cf_headers(url)
        h = {**cf, **base_headers} if cf else dict(base_headers)
        return scraper.get(url, headers=h, **kw) if h else scraper.get(url, **kw)

    resp = _fetch()
    if cloudflare.is_blocked(resp) and cloudflare.solve_and_store(url):
        resp = _fetch()
    return resp


from .config import portals


def get_website_url(portal=portals["coflix"]):
    global website_origin

    if website_origin:
        return

    if portal.startswith("http"):
        response = scraper.head(portal)
    else:
        response = scraper.head("https://" + portal)
    response.raise_for_status()

    website_origin = response.url


def search(query: str) -> list[SearchResult]:
    page = website_origin + f"/suggest.php?query={query}"

    response = _get(page)
    response.raise_for_status()
    response = response.json()

    results: list[SearchResult] = []

    for result in response:
        image: str = result["image"]
        # Handle cases where the image might not have the expected format
        try:
            image = "https://" + image.split("//")[1].split('"')[0]
        except IndexError:
            pass  # Keep the original url if the split fails

        results.append(SearchResult(result["title"], result["url"], image, []))

    return results


def get_players(players_url: str) -> list[Player]:
    """
    Get list of players from a player URL.

    Args:
        players_url: URL to fetch players from

    Returns:
        List of Player objects
    """

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,en-US;q=0.7,en;q=0.3",
        "Sec-GPC": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Priority": "u=0, i",
        "Referer": website_origin,
    }

    response = _get(players_url, headers=headers)

    content = response.text or ""
    # coflix's player aggregator (lecteurvideo.com) sits behind Cloudflare
    # and returns a 403 challenge page no terminal can pass. Surface a
    # clear message instead of a raw HTTPError.
    head = content[:1500].lower()
    if response.status_code != 200 and (
        "cloudflare" in head or "cf-ray" in head or "attention required" in head
    ):
        hint = (
            " Astuce : Réglages → Cloudflare token (colle ton cookie "
            "cf_clearance + ton User-Agent) pour débloquer."
            if not cloudflare.has_token(players_url)
            else " (ton cf_clearance ne passe plus — régénère-le dans le navigateur.)"
        )
        raise RuntimeError(
            "Source Coflix protégée par Cloudflare en ce moment." + hint
        )
    response.raise_for_status()

    soup = BeautifulSoup(content, "html5lib")

    players = []
    for li in soup.find_all("li"):
        if "onclick" in li.attrs and "showVideo" in li.attrs["onclick"]:
            span = li.find("span")
            player_name = span.text.strip() if span else "Unknown"
            player_name = player_name.split(" /")[0]
            link = base64.b64decode(li.attrs["onclick"].split("'")[1].split("'")[0])
            players.append(Player(player_name, str(link, "utf-8")))

    return players


def get_episode(url: str) -> Episode:
    """
    Get episode details including players.

    Args:
        url: Episode URL

    Returns:
        Episode object with title and players
    """
    response = _get(url)
    response.raise_for_status()

    content = response.text
    soup = BeautifulSoup(content, "html5lib")

    title: str = ""
    episodes_div = soup.find("div", {"class": "episodes"})
    if episodes_div:
        for episode in episodes_div.find_all("div", class_="episode"):
            link = episode.find("a")
            if link and link.attrs.get("href") == url:
                span = episode.find("span", class_="fwb link-co")
                title = span.text.strip() if span else ""
                break

    iframe = soup.find("iframe")
    players_url = iframe.attrs["src"] if iframe else ""

    players = get_players(players_url)

    return Episode(title, players)


def get_season(url: str) -> CoflixSeason:
    response = _get(url)
    response.raise_for_status()

    content = response.json()

    title = content["title"]
    episodes: list[EpisodeAccess] = []

    for episode in content["episodes"]:
        name = f"Episode {episode['number']}"
        episodes.append(EpisodeAccess(name, url=episode["links"]))

    return CoflixSeason(title, url, episodes)


def _extract_cover(soup, html: str = "") -> str:
    """
    Robust Coflix cover URL so the poster ALWAYS shows : tries og:image,
    then .title-img / .poster, then the first TMDB image in the page, and
    normalises it to an absolute https URL (Coflix serves protocol-relative
    //image.tmdb.org/… URLs that curl can't fetch as-is).
    """
    candidates = []
    og = soup.find("meta", {"property": "og:image"})
    if og and og.attrs.get("content"):
        candidates.append(og.attrs["content"])
    for cls in ("title-img", "poster"):
        d = soup.find("div", {"class": cls})
        if d and d.find("img"):
            candidates.append(d.find("img").attrs.get("src", ""))
    if html:
        m = re.search(r'https?:?//image\.tmdb\.org/t/p/w\d+/[^"\'\s>]+', html)
        if m:
            candidates.append(m.group(0))

    for c in candidates:
        c = (c or "").strip()
        if not c:
            continue
        if c.startswith("//"):
            return "https:" + c
        if c.startswith("http"):
            return c
        return website_origin.rstrip("/") + "/" + c.lstrip("/")
    return ""


def get_movie(url: str) -> CoflixMovie:
    response = _get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    h1 = soup.find("h1")
    title: str = h1.text.strip() if h1 else url.rstrip("/").split("/")[-1].replace("-", " ").title()
    img: str = _extract_cover(soup, response.text)

    genres: list[str] = []
    genres_container = soup.find("div", {"class": "ctgrs"})

    if genres_container:
        for genre_link in genres_container.find_all("a"):
            genres.append(genre_link.text)

    year_elem = soup.find("span", {"class": "fwb fz20 e-fz25 dib"})
    year = year_elem.text.strip() if year_elem else "Unknown"

    iframe = soup.find("iframe")
    players_url = iframe.attrs["src"] if iframe else ""
    players = get_players(players_url) if players_url else []

    return CoflixMovie(title, url, img, genres, year, players)


def get_series(url: str) -> CoflixSeries:
    response = _get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    h1 = soup.find("h1")
    title: str = h1.text.strip() if h1 else url.rstrip("/").split("/")[-1].replace("-", " ").title()
    img: str = _extract_cover(soup, response.text)

    genres: list[str] = []
    genres_container = soup.find("div", {"class": "ctgrs"})

    if genres_container:
        for genre_link in genres_container.find_all("a"):
            genres.append(genre_link.text)

    # Seasons are radio inputs : <input name="seasons" data-season="1"
    # post-id="12468" ...>. (The old code read <ul class="sub-menu">,
    # which is the site nav — the theme moved seasons into a
    # section.sc-seasons block.) The episode API endpoint is unchanged :
    #   /wp-json/apiflix/v1/series/{post-id}/{data-season}
    seasons: list[SeasonAccess] = []
    for inp in soup.find_all("input", attrs={"name": "seasons"}):
        post_id = inp.attrs.get("post-id")
        data_season = inp.attrs.get("data-season")
        if not post_id or not data_season:
            continue
        link = f"{website_origin}/wp-json/apiflix/v1/series/{post_id}/{data_season}"
        # Label : the <span> next to the radio (e.g. "From - Season 1"),
        # falling back to "Season N".
        parent = inp.find_parent()
        label = parent.get_text(strip=True) if parent else ""
        if not label:
            label = f"Season {data_season}"
        seasons.append(SeasonAccess(label, link))

    return CoflixSeries(title, url, img, genres, seasons)


def get_content(url: str):
    """
    Auto-detect and get content (movie or series) based on URL.

    Args:
        url: Content URL

    Returns:
        CoflixMovie if URL contains '/film/', CoflixSeries otherwise
    """
    if "/film/" in url:
        return get_movie(url)
    return get_series(url)


if __name__ == "__main__":
    # print(search("mercredi"))
    # print(get_series("https://coflix.foo/serie/game-of-thrones/"))
    # print(get_season("https://coflix.foo/wp-json/apiflix/v1/series/14261/4"))
    print(get_episode("https://coflix.foo/episode/game-of-thrones-4x9/"))
