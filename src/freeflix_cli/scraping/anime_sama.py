from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from .objects import SearchResult, SamaSeason, SamaSeries, SeasonAccess, Episode
from .utils import parse_episodes_from_js
from ..proxy import DNS_OPTIONS
from random import randint

website_origin = ""

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

from .. import cloudflare


def _get(url, **kw):
    """
    GET that rides a cf_clearance cookie if set, and — on a Cloudflare block
    — asks FlareSolverr to auto-solve the challenge, then retries once.
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

# info_class = "mt-0.5 text-gray-300 font-medium text-xs truncate"
info_class = "info-value"


from .config import portals


def get_website_url(portal=portals["anime-sama"]):
    global website_origin

    if website_origin:
        return

    if portal.startswith("http"):
        response = scraper.get(portal)
    else:
        response = scraper.get("https://" + portal)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    recommanded_url = soup.find("a", {"class": "btn-primary"}).attrs["href"]

    response = scraper.head(recommanded_url)
    response.raise_for_status()

    website_origin = response.url


def search(query: str) -> list[SearchResult]:
    page = website_origin + f"/catalogue/?search={query}"

    response = _get(page)
    response.raise_for_status()

    results: list[SearchResult] = []

    soup = BeautifulSoup(response.text, "html5lib")

    result_container = soup.find("div", {"id": "list_catalog"})

    # Check if the container exists to avoid errors if no results
    if result_container:
        for result in result_container.find_all("div", recursive=False):
            is_scan_only = False
            for info in result.find_all("p", {"class": info_class}):
                if info.text == "Scans":
                    is_scan_only = True
                    break
            if is_scan_only:
                continue

            url: str = result.find("a").attrs["href"]
            img: str = result.find("a").img.attrs["src"]
            info_block = result.find("div", {"class": "card-content"})
            title: str = info_block.h2.text
            genres: list[str] = info_block.find("p", {"class": info_class}).text.split(
                ", "
            )
            results.append(SearchResult(title, url, img, genres))

    return results


lang_codes = ["vostfr", "vf", "vj", "vcn", "vqc", "vkr", "va", "vf1", "vf2"]


def get_season(url: str) -> SamaSeason:
    episodes: dict[str, list[Episode]] = {}
    valid_lang = []
    for lang_code in lang_codes:
        nurl = (
            url.replace("vostfr", lang_code).removesuffix("/")
            + f"/episodes.js?filever={randint(1, 100000)}"
        )
        response = _get(nurl)

        if response.status_code == 404:
            continue
        response.raise_for_status()

        episodes[lang_code] = parse_episodes_from_js(response.text)
        valid_lang.append(lang_code)

    # Clean up the title based on the URL
    parts = url.removesuffix("/").split("/")
    # Take the second to last element if the url ends with the language, otherwise adjust according to structure
    name = parts[-2].title() if len(parts) >= 2 else "Unknown"

    num = "0123456789"
    for char in num:
        name = name.replace(char, " " + char)

    return SamaSeason(name, url, valid_lang, episodes)


# season_container_class = "flex flex-wrap overflow-y-hidden justify-start bg-slate-900 bg-opacity-70 rounded mt-2 h-auto"
def get_series(url: str) -> SamaSeries:
    response = _get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    # Title : newer anime-sama layout dropped <h4 id="titreOeuvre"> in
    # favour of a plain <h1>. Try the old id, then h1, then the URL slug.
    title_el = soup.find("h4", {"id": "titreOeuvre"}) or soup.find("h1")
    if title_el:
        title = title_el.get_text(strip=True)
    else:
        title = url.rstrip("/").split("/")[-1].replace("-", " ").title()

    # Cover : the <img id="coverOeuvre"> tag is missing on many catalogue
    # pages (One Piece, Frieren…), which left the poster empty "when it
    # felt like it". The og:image meta tag is ALWAYS present though, so try
    # it first and fall back to coverOeuvre / a lazy-load attribute.
    img = ""
    og = soup.find("meta", {"property": "og:image"})
    if og and og.attrs.get("content"):
        img = og.attrs["content"].strip()
    if not img:
        img_el = soup.find("img", {"id": "coverOeuvre"})
        if img_el:
            img = (
                img_el.attrs.get("src")
                or img_el.attrs.get("data-src")
                or img_el.attrs.get("data-lazy-src")
                or ""
            ).strip()
    if img and img.startswith("//"):
        img = "https:" + img
    elif img and not img.startswith("http"):
        img = website_origin.rstrip("/") + "/" + img.lstrip("/")

    # Genres (optional — missing on some pages)
    genres_el = soup.find("a", {"class": "text-sm text-gray-300"})
    genres = genres_el.get_text(strip=True).split(", ") if genres_el else []

    seasons: list[SeasonAccess] = []

    # Using css select as in the original code
    selection = soup.css.select("div.flex.flex-wrap.overflow-y-hidden")

    if selection:
        seasons_script = selection[0].script
        if seasons_script:
            # Manual parsing of the JS script to extract seasons
            for season in str(seasons_script).split('panneauAnime("')[2:]:
                parts = season.split('"')
                if len(parts) > 2:
                    season_title = parts[0]
                    # The original logic assumes a specific JS structure
                    url_part = season.split('", "')[1].split('"')[0]
                    season_url = url + "/" + url_part
                    seasons.append(SeasonAccess(season_title, season_url))

                if season.endswith("/*"):
                    break

    return SamaSeries(title, url, img, genres, seasons)


if __name__ == "__main__":
    # print(search("one piece"))
    # print(get_series("https://anime-sama.fr/catalogue/bofuri/"))
    # print(get_season("https://anime-sama.fr/catalogue/hunter-x-hunter/saison1/vostfr/"))
    print(
        get_season(
            "https://anime-sama.fr/catalogue/le-chateau-dans-le-ciel/film/vostfr"
        )
    )
