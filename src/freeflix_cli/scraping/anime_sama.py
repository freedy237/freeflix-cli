from curl_cffi import requests as cffi_requests
from .objects import SearchResult, SamaSeason, SamaSeries, SeasonAccess, Episode
from .utils import parse_episodes_from_js, parse_html
from ..net_config import DNS_OPTIONS
from . import resilient
from random import randint
import re

website_origin = ""

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)


def _get(url, cache_ttl=0, cache_key=None, **kw):
    """
    GET that rides a cf_clearance cookie if set, and — on a Cloudflare block
    — asks FlareSolverr to auto-solve the challenge, then retries once.

    When *cache_ttl* > 0 the (successful) body is served from / stored in the
    persistent HTTP cache — used for catalogue reads (search, series, seasons)
    that don't change minute-to-minute, so repeat browsing is instant.
    *cache_key* overrides the cache identity when the real URL carries a
    random cache-buster (e.g. episodes.js?filever=…) that must be ignored.
    """
    from .. import httpcache

    ckey = cache_key or url
    if cache_ttl:
        hit = httpcache.get(ckey, cache_ttl)
        if hit is not None:
            return httpcache.CachedResponse(hit)

    base_headers = kw.pop("headers", {})
    kw.setdefault("timeout", 20)  # never hang on a dead host

    def _fetch():
        cf = cloudflare.get_cf_headers(url)
        h = {**cf, **base_headers} if cf else dict(base_headers)
        return scraper.get(url, headers=h, **kw) if h else scraper.get(url, **kw)

    resp = _fetch()
    if cloudflare.is_blocked(resp) and cloudflare.solve_and_store(url):
        resp = _fetch()
    if cache_ttl and getattr(resp, "status_code", None) == 200:
        httpcache.store(ckey, resp.text)
    return resp

# info_class = "mt-0.5 text-gray-300 font-medium text-xs truncate"
info_class = "info-value"


from .config import portals  # noqa: E402 (deliberate late import — order matters)


def get_website_url(portal=portals["anime-sama"]):
    global website_origin

    if website_origin:
        return

    base = portal if portal.startswith("http") else "https://" + portal

    # Route through cf_get : it retries transient "Connection reset by peer"
    # errors, then falls back to a plain request and finally DoH (bypasses ISP
    # DNS blocking of these hosts) — so a flaky first hit doesn't fail outright.
    response = cloudflare.cf_get(scraper, base, timeout=20)
    if response is None:
        raise RuntimeError("Anime-Sama unreachable (network/DNS/TLS).")
    response.raise_for_status()

    soup = parse_html(response.text)

    btn = soup.find("a", {"class": "btn-primary"})
    recommanded_url = (btn.attrs.get("href") if btn else None) or base

    # Resolve the final mirror (follows redirects). cf_get already follows them,
    # so response.url is the settled origin.
    resp2 = cloudflare.cf_get(scraper, recommanded_url, timeout=20)
    if resp2 is None:
        website_origin = recommanded_url.rstrip("/")
        return
    resp2.raise_for_status()
    website_origin = str(resp2.url).rstrip("/")


def search(query: str) -> list[SearchResult]:
    import urllib.parse as _up
    page = website_origin + f"/catalogue/?search={_up.quote(query)}"

    response = _get(page, cache_ttl=1800)
    response.raise_for_status()

    results: list[SearchResult] = []

    soup = parse_html(response.text)

    # Selectors are hot-patchable via the remote selectors.jsonc (see
    # scraping.resilient) — a layout change on Anime-Sama can be fixed for
    # everyone without a release. The [0] default mirrors today's behavior.
    def _css(key: str, default: str) -> str:
        vals = resilient.get("anime-sama", key, [default])
        return vals[0] if vals else default  # remote [] corrompu → défaut

    container_css = _css("search_container", "#list_catalog")
    card_css = _css("search_card", "div.card-content")
    info_css = _css("search_info", "p.info-value")

    result_container = soup.select_one(container_css)

    # Check if the container exists to avoid errors if no results
    if result_container:
        for result in result_container.find_all("div", recursive=False):
            is_scan_only = False
            for info in result.select(info_css):
                if info.get_text(strip=True) == "Scans":
                    is_scan_only = True
                    break
            if is_scan_only:
                continue

            link_tag = result.find("a")
            if not link_tag:
                continue
            url: str = link_tag.attrs.get("href", "")
            if url and not url.startswith("http"):
                url = website_origin.rstrip("/") + "/" + url.lstrip("/")
            img_tag = link_tag.img
            img: str = img_tag.attrs.get("src", "") if img_tag else ""
            info_block = result.select_one(card_css)
            if not info_block:
                continue
            h2 = info_block.h2
            title: str = h2.text if h2 else ""
            genre_p = info_block.select_one(info_css)
            genres: list[str] = genre_p.text.split(", ") if genre_p else []
            if not title:
                continue
            results.append(SearchResult(title, url, img, genres))

    return results


lang_codes = ["vostfr", "vf", "vj", "vcn", "vqc", "vkr", "va", "vf1", "vf2"]


def get_season(url: str) -> SamaSeason:
    episodes: dict[str, list[Episode]] = {}
    valid_lang = []
    # Ne remplace que le SEGMENT de langue final (…/saison1/vostfr/) : un
    # replace("vostfr") aveugle dupliquait toutes les langues quand l'URL
    # d'entrée était déjà en vf, et corrompait les slugs contenant "vostfr".
    m = re.search(r"/(vostfr|vf|vj|vcn|vqc|vkr|va|vf1|vf2)/?$", url)
    base = url[:m.start()] if m else url.rstrip("/")
    seen_stable = set()
    for lang_code in lang_codes:
        stable = base + f"/{lang_code}/episodes.js"
        if stable in seen_stable:
            continue
        seen_stable.add(stable)
        nurl = stable + f"?filever={randint(1, 100000)}"
        try:
            response = _get(nurl, cache_ttl=3600, cache_key=stable)
        except Exception:
            continue
        if response.status_code == 404:
            continue
        try:
            response.raise_for_status()
        except Exception:
            continue  # une langue en 500/403 n'aborte plus toute la saison

        # Season announced but not yet published (episodes.js is empty,
        # e.g. `//`) — skip instead of crashing in parse_episodes_from_js.
        if "var eps" not in (response.text or ""):
            continue

        parsed = parse_episodes_from_js(response.text)
        if not parsed:
            continue
        episodes[lang_code] = parsed
        valid_lang.append(lang_code)

    # Clean up the title based on the URL
    parts = url.removesuffix("/").split("/")
    # Take the second to last element if the url ends with the language, otherwise adjust according to structure
    name = parts[-2].title() if len(parts) >= 2 else "Unknown"

    # Espace entre lettres et groupes de chiffres : "Saison 10", pas "Saison 1 0".
    name = re.sub(r"(?<=[^\W\d_])(\d+)", r" \1", name)

    return SamaSeason(name, url, valid_lang, episodes)


# season_container_class = "flex flex-wrap overflow-y-hidden justify-start bg-slate-900 bg-opacity-70 rounded mt-2 h-auto"
def get_series(url: str) -> SamaSeries:
    response = _get(url, cache_ttl=3600)
    response.raise_for_status()

    soup = parse_html(response.text)

    # Title : newer anime-sama layout dropped <h4 id="titreOeuvre"> in favour
    # of a plain <h1>. The selector list (old id, then h1) is hot-patchable;
    # fall back to the URL slug if none match.
    title = resilient.first_text(soup, "anime-sama", "series_title")
    if not title:
        title = url.rstrip("/").split("/")[-1].replace("-", " ").title()

    # Cover : the <img id="coverOeuvre"> tag is missing on many catalogue
    # pages (One Piece, Frieren…), which left the poster empty "when it
    # felt like it". The og:image meta tag is ALWAYS present though, so the
    # selector list tries it first, then coverOeuvre / a lazy-load attribute.
    img = resilient.first_attr(
        soup, "anime-sama", "series_cover",
        "content", "src", "data-src", "data-lazy-src",
    ).strip()
    if img and img.startswith("//"):
        img = "https:" + img
    elif img and not img.startswith("http"):
        img = website_origin.rstrip("/") + "/" + img.lstrip("/")

    # Genres (optional — missing on some pages)
    genres_el = resilient.first(soup, "anime-sama", "series_genres")
    genres = genres_el.get_text(strip=True).split(", ") if genres_el else []

    seasons: list[SeasonAccess] = []

    # Seasons are declared as panneauAnime("<title>", "<path>") calls in a JS
    # block. The old split+break parser stopped early and missed later seasons
    # (e.g. Dr Stone's "Saison 4 Partie 2/3"). Match ALL calls across the whole
    # page instead, skipping the template call panneauAnime("nom", "url").
    base = url.rstrip("/")
    seen_urls = set()
    for name, path in re.findall(r'panneauAnime\("([^"]*)",\s*"([^"]*)"\)', response.text):
        name = name.strip()
        path = path.strip()
        if not name or not path or name.lower() == "nom" or path.lower() == "url":
            continue  # skip the template / commented example
        season_url = base + "/" + path.lstrip("/")
        if season_url in seen_urls:
            continue
        seen_urls.add(season_url)
        seasons.append(SeasonAccess(name, season_url))

    return SamaSeries(title, url, img, genres, seasons)


if __name__ == "__main__":
    print(
        get_season(
            "https://anime-sama.fr/catalogue/le-chateau-dans-le-ciel/film/vostfr"
        )
    )
