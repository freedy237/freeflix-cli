from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from .objects import SearchResult, SamaSeason, SamaSeries, SeasonAccess, Episode
from .utils import parse_episodes_from_js
from ..proxy import DNS_OPTIONS
from random import randint

website_origin = ""

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

# info_class = "mt-0.5 text-gray-300 font-medium text-xs truncate"
info_class = "info-value"


from .config import portals


def _resolve_portal_url(portal_url: str, use_doh: bool = True) -> str:
    """
    Try to resolve a portal URL to the real site origin.

    Handles two layouts:
      - Portal redirect page (has <a class="btn-primary">): follows the link.
      - Direct site: just returns the resolved URL.

    `use_doh=False` retries with a fresh session that has no DNS-over-HTTPS
    options, useful when the DoH resolver (1.1.1.1) is timing out.
    """
    if use_doh:
        session = scraper
    else:
        session = cffi_requests.Session(impersonate="chrome")

    full_url = portal_url if portal_url.startswith("http") else "https://" + portal_url
    response = session.get(full_url, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")
    btn = soup.find("a", {"class": "btn-primary"})
    if btn and btn.attrs.get("href"):
        recommanded_url = btn.attrs["href"]
        response = session.head(recommanded_url, timeout=15)
        response.raise_for_status()
        return str(response.url).rstrip("/")
    return str(response.url).rstrip("/")


def get_website_url(portal=portals["anime-sama"]):
    global website_origin
    from ..tracker import tracker

    if website_origin:
        return

    # 1. Honor a fresh cache entry to avoid the network round-trip
    cached = tracker.get_portal_cache("anime-sama")
    if cached:
        website_origin = cached
        return

    # 2. Normalize portal config to a list of candidate URLs
    if isinstance(portal, str):
        candidates = [portal]
    elif isinstance(portal, (list, tuple)):
        candidates = list(portal)
    else:
        candidates = [str(portal)]

    # 3. Try each candidate. For each, attempt with DoH; fall back to system DNS.
    last_error = None
    for url in candidates:
        for use_doh in (True, False):
            try:
                resolved = _resolve_portal_url(url, use_doh=use_doh)
                if resolved:
                    website_origin = resolved
                    tracker.set_portal_cache("anime-sama", resolved)
                    return
            except Exception as e:
                last_error = e
                continue

    # 4. All attempts failed — surface a clean, actionable error.
    raise RuntimeError(
        "Could not resolve any anime-sama portal URL.\n"
        f"Tried: {candidates}\n"
        f"Last error: {last_error}\n"
        "Tip: the domain probably moved. Edit\n"
        "  ~/.local/share/uv/tools/freeflix-cli/lib/python3.14/data/source_portal.jsonc\n"
        'and set the new URL for "anime-sama", then relaunch.'
    )


def _absolutize(url: str) -> str:
    """
    Prepend website_origin when the scraper returns a relative path,
    and collapse any accidental double slashes in the path (legacy
    progress.json entries sometimes stored "/catalogue/x//saisonN").
    """
    import re as _re

    if not url:
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        if url.startswith("/"):
            url = website_origin.rstrip("/") + url
        else:
            url = website_origin.rstrip("/") + "/" + url

    # Collapse "//" in the path while preserving the scheme "://".
    return _re.sub(r"([^:])//+", r"\1/", url)


def search(query: str) -> list[SearchResult]:
    from urllib.parse import quote_plus
    # Note: no slash before "?search" — the new site (animes-sama.fr) returns 404
    # on the legacy "/catalogue/?search=" form but 200 on "/catalogue?search=".
    page = website_origin + f"/catalogue?search={quote_plus(query)}"

    response = scraper.get(page)
    response.raise_for_status()

    results: list[SearchResult] = []

    soup = BeautifulSoup(response.text, "html5lib")

    result_container = soup.find("div", {"id": "list_catalog"})

    # Check if the container exists to avoid errors if no results
    if result_container:
        for result in result_container.find_all("div", recursive=False):
            # Legacy layout has <p class="info-value">Scans</p> for scan-only
            # entries — newer animes-sama.fr layout has no such marker; we
            # therefore include everything the catalogue returns.
            for info in result.find_all("p", {"class": info_class}):
                if info.text == "Scans":
                    is_scan_only = True
                    break
            else:
                is_scan_only = False
            if is_scan_only:
                continue

            link = result.find("a")
            if not link or not link.has_attr("href"):
                continue
            url = _absolutize(link.attrs["href"])
            img_tag = link.find("img")
            img = img_tag.attrs.get("src", "") if img_tag else ""

            info_block = result.find("div", {"class": "card-content"}) or result

            # New layout : <div class="card-title">TITLE</div>
            # Legacy layout : <h2>TITLE</h2>
            title_tag = info_block.find("div", {"class": "card-title"}) or info_block.find("h2")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)

            # Genres only exist in the legacy <p class="info-value"> ; new
            # layout doesn't expose them — fall back to an empty list.
            genres_tag = info_block.find("p", {"class": info_class})
            if genres_tag:
                genres = genres_tag.get_text(strip=True).split(", ")
            else:
                genres = []

            results.append(SearchResult(title, url, img, genres))

    return results


lang_codes = ["vostfr", "vf", "vj", "vcn", "vqc", "vkr", "va", "vf1", "vf2"]


def get_season(url: str) -> SamaSeason:
    url = _absolutize(url)
    episodes: dict[str, list[Episode]] = {}
    valid_lang = []

    # Strip any existing lang suffix so we can append a fresh one per attempt.
    # URLs from get_series come in as /catalogue/<slug>/<season> (no lang),
    # but legacy URLs may already include /vostfr.
    base = url.removesuffix("/")
    for lc in lang_codes:
        if base.endswith("/" + lc):
            base = base[: -len("/" + lc)]
            break

    # Probe all candidate languages IN PARALLEL. The old sequential loop
    # did up to 9 round-trips back-to-back (~900 ms+). A thread pool cuts
    # that to roughly one round-trip — but each worker MUST use its own
    # curl_cffi session : a curl handle is not safe to share across
    # threads (concurrent use on the shared `scraper` serializes/errors).
    from concurrent.futures import ThreadPoolExecutor

    def _probe(lang_code):
        sess = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)
        try:
            page_url = f"{base}/{lang_code}"
            response = sess.get(page_url, timeout=15)
            if response.status_code == 404:
                legacy = f"{base}/{lang_code}/episodes.js?filever={randint(1, 100000)}"
                response = sess.get(legacy, timeout=15)
                if response.status_code == 404:
                    return lang_code, None
            response.raise_for_status()
            parsed = parse_episodes_from_js(response.text)
            return lang_code, (parsed or None)
        except Exception:
            return lang_code, None
        finally:
            try:
                sess.close()
            except Exception:
                pass

    with ThreadPoolExecutor(max_workers=len(lang_codes)) as ex:
        results = list(ex.map(_probe, lang_codes))

    # Preserve the lang_codes order for a stable language menu.
    for lang_code, parsed in results:
        if parsed:
            episodes[lang_code] = parsed
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
    url = _absolutize(url)
    response = scraper.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    title: str = soup.find("h4", {"id": "titreOeuvre"}).text
    img: str = soup.find("img", {"id": "coverOeuvre"}).attrs["src"]
    genres: list[str] = soup.find("a", {"class": "text-sm text-gray-300"}).text.split(
        ", "
    )

    seasons: list[SeasonAccess] = []

    # --- Legacy layout (anime-sama.pw mirrors) : panneauAnime("Title", "url") ---
    selection = soup.css.select("div.flex.flex-wrap.overflow-y-hidden")
    if selection:
        seasons_script = selection[0].script
        if seasons_script:
            for season in str(seasons_script).split('panneauAnime("')[2:]:
                parts = season.split('"')
                if len(parts) > 2:
                    season_title = parts[0]
                    url_part = season.split('", "')[1].split('"')[0]
                    season_url = url + "/" + url_part
                    seasons.append(SeasonAccess(season_title, season_url))
                if season.endswith("/*"):
                    break

    # --- New layout (animes-sama.fr) : direct <a href="/catalogue/<slug>/<season>"> ---
    if not seasons:
        import re as _re
        # Each season exposes multiple language variants ; we want one entry per season.
        season_re = _re.compile(r"^/catalogue/[^/]+/([^/]+)(?:/[^/]+)?/?$")
        seen_keys: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = season_re.match(href)
            if not m:
                continue
            season_slug = m.group(1)
            # Manga scans are out of scope for the anime flow.
            if season_slug in ("scan", "scans"):
                continue
            parts = href.rstrip("/").split("/")
            if len(parts) < 4:
                continue
            season_key = "/".join(parts[:4])
            if season_key in seen_keys:
                continue
            seen_keys.add(season_key)
            season_title = a.get_text(strip=True) or season_slug
            seasons.append(
                SeasonAccess(season_title, _absolutize(season_key))
            )

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
