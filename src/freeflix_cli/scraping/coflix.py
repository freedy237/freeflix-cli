from curl_cffi import requests as cffi_requests
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
from .utils import parse_html
import base64
import re
import urllib.parse
from ..net_config import DNS_OPTIONS

website_origin = ""
scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)


def _get(url, **kw):
    """
    GET that rides a cf_clearance cookie if set, and — on a Cloudflare block
    — asks FlareSolverr to auto-solve the challenge, then retries once.
    Cascade : curl_cffi → FlareSolverr → manual cf_clearance → block message.
    On HTTP 429 (rate‑limit) sleeps 3 s and retries once.
    """
    import time as _time

    base_headers = kw.pop("headers", {})
    kw.setdefault("timeout", 20)  # never hang on a dead host

    def _fetch():
        cf = cloudflare.get_cf_headers(url)
        h = {**cf, **base_headers} if cf else dict(base_headers)
        return scraper.get(url, headers=h, **kw) if h else scraper.get(url, **kw)

    for attempt in range(2):
        resp = _fetch()
        if cloudflare.is_blocked(resp) and cloudflare.solve_and_store(url):
            resp = _fetch()
        if resp.status_code == 429 and attempt == 0:
            _time.sleep(3)
            continue
        return resp
    return resp


from .config import portals  # noqa: E402 (deliberate late import — order matters)


def get_website_url(portal=portals["coflix"]):
    global website_origin

    if website_origin:
        return

    base = portal if portal.startswith("http") else "https://" + portal

    # Route through cf_get : retries transient DNS / "connection reset" errors,
    # then falls back to a plain request and DoH (bypasses ISP DNS blocking of
    # the coflix mirror) — and follows the redirect to the live domain, so
    # website_origin settles on the current mirror (coflix.cymru → coflix.esq…).
    response = cloudflare.cf_get(scraper, base, timeout=20)
    if response is None:
        raise RuntimeError("Coflix unreachable (network/DNS/TLS).")
    response.raise_for_status()

    website_origin = str(response.url).rstrip("/")





def _norm_img(src: str) -> str:
    """Normalise a cover URL (Coflix serves protocol-relative //image.tmdb.org)."""
    src = (src or "").strip()
    if src.startswith("//"):
        return "https:" + src
    return src


def _search_html(query: str) -> list[SearchResult]:
    """
    Search via the site's own results page (/?s=…). Each result is a
    ``.md-manga-card`` whose <a> gives the /film|serie/ URL and whose <img>
    carries BOTH the poster (src) and the title (alt) — so the preview pane
    gets real posters, unlike the imageless WP REST endpoint.
    """
    page = website_origin.rstrip("/") + "/?s=" + urllib.parse.quote(query)
    response = _get(page)
    response.raise_for_status()
    soup = parse_html(response.text)

    results: list[SearchResult] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"/(film|serie)/[^/]+/?$", href) or href in seen:
            continue
        if href and not href.startswith("http"):
            href = website_origin.rstrip("/") + "/" + href.lstrip("/")
        # Poster de LA carte uniquement : remonter au parent prenait le
        # poster d'une carte voisine sur les liens texte sans image.
        img = a.find("img")
        if img is None:
            continue
        title = (img.get("alt") or "").strip()
        cover = _norm_img(img.get("src") or img.get("data-src") or "")
        if not title:
            continue
        seen.add(href)
        results.append(SearchResult(title, href, cover, []))
    return results


def search(query: str) -> list[SearchResult]:
    """
    Search Coflix (now a WordPress site — the old /suggest.php 500s). Primary:
    the HTML results page, which carries posters + titles. Fallback: the WP REST
    search endpoint (titles only) if the HTML layout ever yields nothing.
    """
    try:
        results = _search_html(query)
        if results:
            return results
    except Exception:
        pass

    # Fallback : WP REST search (no poster, but reliable titles/urls).
    try:
        page = (website_origin.rstrip("/")
                + "/wp-json/wp/v2/search?per_page=20&search=" + urllib.parse.quote(query))
        response = _get(page)
        if getattr(response, "status_code", None) == 429:
            raise RuntimeError("Coflix 429 — search temporarily blocked by the site")
        response.raise_for_status()
        data = response.json()
    except RuntimeError:
        raise
    except Exception:
        return []

    if not isinstance(data, list):
        return []
    out: list[SearchResult] = []
    for r in data:
        if isinstance(r, dict) and r.get("title") and r.get("url"):
            out.append(SearchResult(r["title"], r["url"], "", []))
    return out


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

    soup = parse_html(content)

    players = []
    for li in soup.find_all("li"):
        if "onclick" in li.attrs and "showVideo" in li.attrs["onclick"]:
            try:
                span = li.find("span")
                player_name = span.text.strip() if span else "Unknown"
                player_name = player_name.split(" /")[0]
                raw = li.attrs["onclick"].split("'")[1].split("'")[0]
                link = base64.b64decode(raw)
                players.append(Player(player_name, str(link, "utf-8")))
            except (IndexError, ValueError, UnicodeDecodeError):
                continue  # un <li> malformé ne tue plus tous les players

    return players


def get_episode(url: str) -> Episode:
    """
    Get episode details including players. On the WordPress theme the episode
    page embeds the player aggregator in an <iframe> (same as movies), so the
    players come straight from get_players() ; the title falls back to the h1.
    """
    response = _get(url)
    response.raise_for_status()

    soup = parse_html(response.text)

    h1 = soup.find("h1")
    title: str = h1.get_text(strip=True) if h1 else ""

    iframe = soup.find("iframe")
    players_url = (iframe.attrs.get("src") or "") if iframe else ""
    if players_url and not players_url.startswith("http"):
        players_url = website_origin.rstrip("/") + "/" + players_url.lstrip("/")

    players = get_players(players_url) if players_url else []

    return Episode(title, players)


def get_season(url: str) -> CoflixSeason:
    """
    Episodes for one season. The WordPress theme ships EVERY season's episodes
    in the series page, split into ``<div class="cf-episodes-panel" data-panel=K>``
    blocks. We encode the panel index in the URL fragment (``…#panel=K``, set by
    get_series) and pull that panel's episode items (each an ``/episode/…`` link).
    """
    page_url, _, frag = url.partition("#")
    panel = ""
    if frag.startswith("panel="):
        # N'accepte que [A-Za-z0-9_-] : le fragment vient de l'historique et
        # est injecté tel quel dans un sélecteur CSS (SelectorSyntaxError).
        raw = frag[len("panel="):]
        panel = raw if re.fullmatch(r"[A-Za-z0-9_-]+", raw) else ""

    response = _get(page_url)
    response.raise_for_status()
    soup = parse_html(response.text)

    panels = soup.select(f".cf-episodes-panel[data-panel='{panel}']") if panel != "" \
        else soup.select(".cf-episodes-panel")

    # Real season label from the matching tab (data-panel index ≠ season number).
    season_title = f"Saison {panel}" if panel != "" else "Episodes"
    btn = soup.select_one(f"button[data-season='{panel}']") if panel != "" else None
    if btn:
        lang = btn.find("span", {"class": "cf-server-tab-lang"})
        if lang:
            lang.extract()
        season_title = btn.get_text(strip=True) or season_title

    episodes: list[EpisodeAccess] = []
    seen = set()
    for panel_el in panels:
        for item in panel_el.select(".cf-episode-item"):
            ep_url = _onclick_url(item.get("onclick", ""))
            if not ep_url or ep_url in seen:
                continue
            seen.add(ep_url)
            title_el = item.select_one(".cf-episode-title")
            name = title_el.get_text(strip=True) if title_el else f"Episode {len(episodes) + 1}"
            episodes.append(EpisodeAccess(name, url=ep_url))

    return CoflixSeason(season_title, url, episodes)


def _onclick_url(onclick: str) -> str:
    """Extract the target URL from a `window.location.href='…'` onclick."""
    m = re.search(r"href=['\"]([^'\"]+)['\"]", onclick or "")
    return m.group(1) if m else ""


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
    # WordPress theme : the main poster is an <img> whose src is a TMDB poster
    # (…/t/p/w500/…). Prefer w500 (the cover) over w342 (episode/related thumbs).
    tmdb_imgs = [
        i.get("src", "") for i in soup.find_all("img")
        if "image.tmdb.org/t/p/" in (i.get("src") or "")
    ]
    candidates += [s for s in tmdb_imgs if "/w500/" in s]
    candidates += tmdb_imgs
    if html:
        # protocol-relative //image.tmdb.org/… (no scheme) too.
        m = re.search(r'(?:https?:)?//image\.tmdb\.org/t/p/w\d+/[^"\'\s>]+', html)
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

    soup = parse_html(response.text)

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
    players_url = (iframe.attrs.get("src") or "") if iframe else ""
    if players_url and not players_url.startswith("http"):
        players_url = website_origin.rstrip("/") + "/" + players_url.lstrip("/")
    players = get_players(players_url) if players_url else []

    return CoflixMovie(title, url, img, genres, year, players)


def get_series(url: str) -> CoflixSeries:
    response = _get(url)
    response.raise_for_status()

    soup = parse_html(response.text)

    h1 = soup.find("h1")
    title: str = h1.text.strip() if h1 else url.rstrip("/").split("/")[-1].replace("-", " ").title()
    img: str = _extract_cover(soup, response.text)

    genres: list[str] = []
    genres_container = soup.find("div", {"class": "ctgrs"})

    if genres_container:
        for genre_link in genres_container.find_all("a"):
            genres.append(genre_link.text)

    # WordPress theme : seasons are tabs <button data-season="K">Saison N
    # <span class="cf-server-tab-lang">…</span></button>, and each season's
    # episodes live in <div class="cf-episodes-panel" data-panel="K">. Every
    # episode is already in the page, so get_season() just re-reads the panel;
    # we encode the panel index in the SeasonAccess URL fragment.
    base_url = url.split("#")[0].rstrip("/")
    seasons: list[SeasonAccess] = []
    for btn in soup.select("button[data-season]"):
        k = btn.get("data-season")
        if k is None:
            continue
        # Clean label : button text minus the "N ép" count span.
        lang = btn.find("span", {"class": "cf-server-tab-lang"})
        if lang:
            lang.extract()
        label = btn.get_text(strip=True) or f"Saison {k}"
        seasons.append(SeasonAccess(label, f"{base_url}#panel={k}"))

    # Fallback : no tabs but episodes present (single-season) → one pseudo-season.
    if not seasons and soup.select(".cf-episode-item"):
        seasons.append(SeasonAccess("Episodes", f"{base_url}#panel=0"))

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
    print(get_episode("https://coflix.foo/episode/game-of-thrones-4x9/"))
