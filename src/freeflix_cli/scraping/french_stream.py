import json
import re

from .objects import (
    SearchResult,
    FrenchStreamMovie,
    Player,
    FrenchStreamSeason,
    Episode,
)
from .utils import cacheable_body, clean_text, parse_html

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
                CurlOpt.CONNECTTIMEOUT: 15,
            },
        )
    return _DOH_SESSION



from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)
from .. import httpcache  # noqa: E402 (persistent search cache)


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
# waaw.to (Netu clone) : the stream is resolved client-side via
# DNS-over-HTTPS + websocket handshake (needs JS) — never extractable
# server-side, so listing it only offers a dead player.
_DEAD_PLAYER_HOSTS = ("trakx.lol", "multiup.us", "multiup.io", "bysesayeveum.com", "waaw.to")
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


def _page_has_more(body: str) -> bool:
    """True when the AJAX page carries the site's "Afficher la suite" card."""
    try:
        soup = parse_html(body)
        return soup.select_one(".search-item.search-more") is not None
    except Exception:
        return "search-more" in (body or "") or 'data-page="' in (body or "")


def search_page(query: str, page: int = 1):
    """One result page + whether the site has a next page.

    The endpoint is paginated (page 1 = 19 cards, then 25/page). The UI now
    shows ONE page at a time with an "Afficher la suite" row, exactly like the
    site — instead of dumping 191 rows (or, before 1.16.5, stopping at page 1).
    """
    page_search = "/engine/ajax/search.php"
    headers = {"Referer": f"{website_origin}/"}

    def _diag(msg: str):
        try:
            from .. import logsetup as _ls
            _ls.warning(f"french-stream search: {msg}")
        except Exception:
            pass

    page = max(1, int(page or 1))
    ckey = f"french-stream:search-page-v4:{query.strip().lower()}:{page}"
    cached = httpcache.get(ckey, 300)
    if cached is not None:
        try:
            data = json.loads(cached)
            cards = [
                SearchResult(c[0], c[1], c[2], list(c[3] or []),
                             (c[4] if len(c) > 4 else None))
                for c in (data.get("cards") or [])
            ]
            if cards:
                return cards, bool(data.get("has_more"))
        except Exception:
            pass

    try:
        response = _post(
            website_origin + page_search,
            data={"query": query, "page": page},
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
    except Exception as e:
        _diag(f"request failed page={page} err={type(e).__name__}: {e}")
        return [], False

    body = response.text or ""
    low = body.lower()
    if "verification" in low and "anti-robot" in low:
        _diag(f"anti-robot challenge page (page {page}, {len(body)} bytes)")
    elif "cloudflare" in low or "cf-ray" in low or "just a moment" in low:
        _diag(f"cloudflare challenge page (page {page}, {len(body)} bytes)")

    cards = _parse_search_cards(body)
    has_more = bool(cards) and _page_has_more(body)
    if cards:
        try:
            httpcache.store(ckey, json.dumps({
                "cards": [[r.title, r.url, r.img, r.genres, r.seasons]
                          for r in cards],
                "has_more": has_more,
            }, ensure_ascii=False))
        except Exception:
            pass
    else:
        _diag(f"0 results parsed from {len(body)}-byte response "
              f"(page {page}, status={getattr(response, 'status_code', '?')})")
    return cards, has_more


def search(query: str) -> list[SearchResult]:
    """Backward-compatible helper: the FIRST page (the UI paginates)."""
    cards, _has_more = search_page(query, 1)
    return cards


def _parse_search_cards(body: str) -> list[SearchResult]:
    results: list[SearchResult] = []

    soup = parse_html(body)

    for result in soup.find_all("div", {"class": "search-item"}):
        title_tag = result.find("div", {"class": "search-title"})
        title: str = clean_text(title_tag.text) if title_tag is not None else ""
        if not title:
            # Une carte sans .search-title mais avec un <img alt>/<a> reste
            # un résultat : on la garde au lieu de la jeter.
            img_alt = result.find("img")
            title = clean_text(
                (img_alt.get("alt") or "") if img_alt is not None else ""
            )

        # ── Series card ──────────────────────────────────────────────
        # `search-item search-series` has NO onclick/<a>: the seasons live in
        # a data-seasons JSON attribute. Skipping it hid whole shows (e.g.
        # "FROM - série", first result on the site) from the app.
        classes = result.get("class") or []
        raw_seasons = result.attrs.get("data-seasons")
        if raw_seasons or "search-series" in classes:
            seasons = []
            try:
                parsed = json.loads(raw_seasons or "[]")
                for season in parsed if isinstance(parsed, list) else []:
                    if not isinstance(season, dict):
                        continue
                    rel = season.get("l") or ""
                    if not rel:
                        continue
                    url = rel if str(rel).startswith("http") else website_origin + rel
                    seasons.append({
                        "n": season.get("n") or len(seasons) + 1,
                        "url": url,
                        "poster": _abs_img(season.get("p") or ""),
                    })
            except Exception:
                seasons = []
            if seasons:
                first = seasons[0]
                if not title:
                    title = clean_text(first["url"].rstrip("/").rsplit("/", 1)[-1])
                link = first["url"]
                if any(r.url == link for r in results):
                    continue
                results.append(SearchResult(
                    title, link, first.get("poster") or "", [], seasons,
                ))
            continue

        # Single or double quotes, and an <a href> template as a fallback:
        # the skin has shipped both layouts.
        onclick = result.attrs.get("onclick", "") or ""
        if "location.href" not in onclick:
            onclick = str(
                [v for k, v in result.attrs.items() if k == "onclick"] or ""
            )
        m = re.search(r"""location\.href\s*=\s*['"]([^'"]+)['"]""", onclick)
        rel = m.group(1) if m else ""
        if not rel:
            anchor = result.find("a", href=True)
            rel = anchor["href"] if anchor is not None else ""
        if not rel:
            continue  # bandeau pub sans lien : on saute, pas tout le reste
        if not title:
            title = clean_text(rel.rstrip("/").rsplit("/", 1)[-1].split("-", 1)[-1])
        link: str = rel if rel.startswith("http") else website_origin + rel
        try:
            img_tag = result.find("img")
            img: str = _abs_img((img_tag.attrs.get("src") or "") if img_tag else "")
        except AttributeError:
            img: str = ""  # no image

        genres: list[str] = []  # unknow

        if any(r.url == link for r in results):
            continue  # site sends the same card twice (promo + real)
        results.append(SearchResult(title, link, img, genres))

    return results


def _cached_json(url: str, ttl: int = 300):
    """Small JSON GET cache for the studio API (ep-data/film_api).

    Backing out of a season and selecting it again used to re-download the
    same JSON every time. 5 min is short enough for new episodes to appear.
    """
    key = f"french-stream:json:{url}"
    cached = httpcache.get(key, ttl)
    if cached is not None:
        try:
            data = json.loads(cached)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    try:
        r = _get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            httpcache.store(key, json.dumps(data))
            return data
    except Exception:
        pass
    return None


_player_alive_cache: dict = {}
_player_alive_lock = __import__("threading").Lock()
_PLAYER_ALIVE_TTL = 300.0
_PLAYER_DEAD_TTL = 120.0


def _probe_embed(link: str):
    """One cheap HEAD on an embed page (per-thread session, hard timeout)."""
    from . import player as _player
    host = link.split("/")[2]
    return _player._scraper().head(
        link,
        headers={"Referer": f"https://{host}/"},
        impersonate="chrome",
        timeout=(3, 4),
    )


def _player_alive(link: str) -> bool:
    """Fast cached liveness probe for one embed row.

    The studio API keeps deleted embeds for a long time (voe → 404); probing
    every row on every content load used to cost 8-30 s. This is now a HEAD
    with a hard 4 s budget, never a full stream extraction: the expensive
    resolution (and the 30 s-ad check) already runs in parallel in the player
    menu, where the user expects a short wait. A slow/blocked host is kept
    (fail-open) so a hiccup never hides a working source.
    """
    import time as _time
    now = _time.time()
    with _player_alive_lock:
        ent = _player_alive_cache.get(link)
        if ent and now - ent[1] < ent[2]:
            return ent[0]
    from . import player as _player
    ok = True
    try:
        r = _probe_embed(link)
        ok = _player.embed_status(getattr(r, "status_code", 0)) != "dead"
    except Exception as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code is None:
            import re as _re
            m = _re.search(r"\b(40[0-9]|41[0-9])\b", str(exc))
            code = int(m.group(1)) if m else None
        if code and _player.embed_status(code) == "dead":
            ok = False
        # Any other failure: keep the row (do not hide a working source).
    ttl = _PLAYER_ALIVE_TTL if ok else _PLAYER_DEAD_TTL
    with _player_alive_lock:
        _player_alive_cache[link] = (ok, now, ttl)
        if len(_player_alive_cache) > 400:
            for old in sorted(_player_alive_cache.items(),
                              key=lambda kv: kv[1][1])[:80]:
                _player_alive_cache.pop(old[0], None)
    return ok


def get_movie(url: str, content: str) -> FrenchStreamMovie:
    soup = parse_html(content)

    og = soup.find("meta", {"property": "og:title"})
    if og and og.attrs.get("content"):
        title = og.attrs["content"]
    else:
        title = clean_text(soup.title.get_text(strip=True)) if soup.title else url.rstrip("/").split("/")[-1].replace("-", " ").title()

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

    movie_info = _cached_json(
        f"{website_origin}/engine/ajax/film_api.php?id={movie_id}"
    )
    if not movie_info:
        return FrenchStreamMovie(title, url, img, genres, players)

    raw_players = movie_info.get("players") if isinstance(movie_info, dict) else None
    if not isinstance(raw_players, dict):
        return FrenchStreamMovie(title, url, img, genres, players)
    # Build the candidate rows first, then probe them CONCURRENTLY. The
    # probes are independent network calls (2-8 s each on slow hosts); doing
    # them one after another made the first movie selection take 7-30 s.
    # Order is preserved so the player menu stays stable between visits.
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for player_name, player_links in raw_players.items():
        if not isinstance(player_links, dict):
            continue
        for lang, link in player_links.items():
            if not _is_usable_player_link(link) or link in seen:
                continue  # dead host (trakx/netu) or non-URL code
            # dedup: most films expose the SAME embed under default/vostfr/vff,
            # which used to show 3 indistinguishable rows.
            seen.add(link)
            rows.append((player_name + " " + lang, link))

    if rows:
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
                alive = list(pool.map(lambda row: _player_alive(row[1]), rows))
        except Exception:
            alive = [_player_alive(row[1]) for row in rows]
        for (label, link), ok in zip(rows, alive):
            if ok:
                players.append(Player(label, link))

    return FrenchStreamMovie(title, url, img, genres, players)


def get_series_season(url: str, content: str) -> FrenchStreamSeason:
    soup = parse_html(content)

    og = soup.find("meta", {"property": "og:title"})
    if og and og.attrs.get("content"):
        title = og.attrs["content"]
    else:
        title = soup.title.get_text(strip=True) if soup.title else url.rstrip("/").split("/")[-1].replace("-", " ").title()
    serie_id = url.rstrip("/").split("/")[-1].split("-")[0]

    serie_info = _cached_json(f"{website_origin}/ep-data.php?id={serie_id}")
    if not isinstance(serie_info, dict):
        return FrenchStreamSeason(title, url, {})

    episodes: dict[str, list[Episode]] = {}

    # The API exposes one dict per language (vo/vostfr/vf, sometimes vff/vfq)
    # plus a metadata "info" dict. Read the language keys dynamically so a
    # renamed/added track is never silently dropped.
    for lang, payload in serie_info.items():
        if lang == "info" or not isinstance(payload, dict):
            continue
        lang_eps = get_episodes_from_lang(lang, serie_info)
        if lang_eps:
            episodes[lang] = lang_eps

    return FrenchStreamSeason(title, url, episodes)


def get_episodes_from_lang(lang: str, serie_info: dict):
    episodes_raw = (serie_info or {}).get(lang) or {}
    if not isinstance(episodes_raw, dict):
        return []
    episodes: list[Episode] = []

    def _num(key):
        try:
            return (0, int(key))
        except (TypeError, ValueError):
            return (1, str(key))

    # API dicts arrive in JSON order; numeric sort keeps 2 before 10 and
    # avoids a jumbled / seemingly longer episode list.
    for number, players_raw in sorted(episodes_raw.items(),
                                      key=lambda kv: _num(kv[0])):
        if not isinstance(players_raw, dict):
            continue
        players: list[Player] = []
        for player_name, link in players_raw.items():
            if not _is_usable_player_link(link):
                continue  # dead host (trakx/netu) or non-URL code
            players.append(Player(player_name, link))
        # Do not list announced-but-empty episodes (no playable host).
        if players:
            episodes.append(Episode(f"Episode {number}", players))

    return episodes


def get_content(url: str):
    ckey = f"french-stream:content:{url}"
    content = httpcache.get(ckey, 300)
    if content is None:
        response = _get(url)
        response.raise_for_status()
        content = response.text or ""
        if cacheable_body(content):
            httpcache.store(ckey, content)

    if '"episodes-' in content:
        return get_series_season(url, content)
    return get_movie(url, content)


if __name__ == "__main__":
    print(
        get_series_season(
            "https://french-stream.one/s-tv/15112935-mercredi-saison-1.html"
        )
    )
