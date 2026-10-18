from curl_cffi import requests as cffi_requests
import json
import re
from ..net_config import DNS_OPTIONS

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)



from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)
from .. import httpcache  # noqa: E402 (persistent catalogue cache)
from .utils import cacheable_body, clean_text  # noqa: E402


def _get(url, **kw):
    """Cloudflare-aware GET (cf_clearance + FlareSolverr cascade)."""
    return cloudflare.cf_get(scraper, url, **kw)

class AnimeExtractor:
    """
    Original Version (VO) anime extractor based on CineStream.
    Targets M3U8 streams and video players.
    """

    def __init__(self):
        # --- Source URLs loaded from source_portal.jsonc ---
        self.sudatchi_base = portals.get("sudatchi", "https://sudatchi.com")
        self.animetsu_base = portals.get("animetsu", "https://animetsu.live")
        self.animetsu_api = portals.get("animetsu-api", "https://b.animetsu.live")
        self.animetsu_proxy = portals.get(
            "animetsu-proxy", "https://ani.metsu.site/proxy"
        )
        self.allanime_api = portals.get("allanime-api", "https://api.allanime.day/api")
        self.allanime_referer = portals.get("allanime-referer", "https://allmanga.to")
        self.allanime_base = portals.get("allanime-base", "https://allanime.day")
        self.anizone_base = portals.get("anizone", "https://anizone.to")
        self.hianime_base = portals.get("hianime", "https://hianime.at")

        self.headers = {
            "Referer": self.sudatchi_base + "/",
            "Origin": self.sudatchi_base,
        }
        self.animetsu_headers = {
            "Referer": self.animetsu_base + "/",
            "Origin": self.animetsu_base,
        }

    def _decrypt_allanime(self, hex_str):
        """Allanime hex decryption (XOR 56)."""
        try:
            # Extract hex part after '-'
            hex_part = hex_str.split("-")[-1]
            bytes_data = bytes.fromhex(hex_part)
            return "".join(chr(b ^ 56) for b in bytes_data)
        except Exception:
            return hex_str

    def search_sudatchi(self, anilist_id, episode=1):
        """Extraction from Sudatchi (direct M3U8)."""
        base_url = self.sudatchi_base
        api_url = f"{base_url}/api/episode/{anilist_id}/{episode}"

        try:
            response = _get(api_url, headers=self.headers, timeout=10)
            if response.status_code != 200:
                return []

            data = response.json()
            ep_id = data.get("episode", {}).get("id")
            if not ep_id:
                return []

            # The stream link is an API call that returns the M3U8 (Sudatchi logic)
            stream_url = f"{base_url}/api/streams?episodeId={ep_id}"

            return [
                {
                    "source": "Sudatchi",
                    "quality": "1080p",
                    "url": stream_url,
                    "type": "M3U8",
                }
            ]
        except Exception:
            return []

    def search_allanime(self, title, episode=1):
        """Extraction from Allanime using latest GQL hashes and XOR-56 decryption."""
        api_url = self.allanime_api
        referer = self.allanime_referer

        # Latest GQL Hashes from CineStream
        search_hash = "a24c500a1b765c68ae1d8dd85174931f661c71369c89b92b88b75a725afc471c"
        ep_hash = "d405d0edd690624b66baba3068e0edc3ac90f1597d898a1ec8db4e5c43c00fec"

        try:
            # 1. Search (Query Hash)
            vars_search = {
                "search": {"query": title, "types": ["TV", "Movie"]},
                "limit": 26,
                "page": 1,
                "translationType": "sub",
                "countryOrigin": "ALL",
            }
            ext_search = {"persistedQuery": {"version": 1, "sha256Hash": search_hash}}

            r = _get(
                api_url,
                params={
                    "variables": json.dumps(vars_search),
                    "extensions": json.dumps(ext_search),
                },
                headers={"Referer": referer},
                timeout=10,
            )
            shows = r.json().get("data", {}).get("shows", {}).get("edges", [])
            if not shows:
                return []

            # Match title logic
            show_id = None
            t_lower = title.lower().strip()
            for edge in shows:
                name = (edge.get("name") or "").lower().strip()
                eng = (edge.get("englishName") or "").lower().strip()
                if name == t_lower or eng == t_lower:
                    show_id = edge.get("_id")
                    break

            if not show_id and shows:
                # Fuzzy fallback
                for edge in shows:
                    name = (edge.get("name") or "").lower().strip()
                    eng = (edge.get("englishName") or "").lower().strip()
                    if t_lower in name or t_lower in eng:
                        show_id = edge.get("_id")
                        break

            if not show_id and shows:
                show_id = shows[0].get("_id")

            if not show_id:
                return []

            # 2. Links (EP Hash)
            vars_ep = {
                "showId": show_id,
                "translationType": "sub",
                "episodeString": str(episode),
            }
            ext_ep = {"persistedQuery": {"version": 1, "sha256Hash": ep_hash}}

            r = _get(
                api_url,
                params={
                    "variables": json.dumps(vars_ep),
                    "extensions": json.dumps(ext_ep),
                },
                headers={"Referer": referer},
                timeout=10,
            )
            sources = r.json().get("data", {}).get("episode", {}).get("sourceUrls", [])

            results = []
            for src in sources:
                if not isinstance(src, dict):
                    continue  # un miroir malformé ne jette plus les autres
                try:
                    url = src.get("sourceUrl")
                except AttributeError:
                    continue
                if not url:
                    continue
                if url.startswith("--"):
                    url = self._decrypt_allanime(url)

                # Fix relative paths if necessary
                if url.startswith("/"):
                    url = self.allanime_base + url

                if not url.startswith("http"):
                    continue

                results.append(
                    {
                        "source": f"Allanime ({src.get('sourceName', 'Default')})",
                        "quality": "Multi",
                        "url": url,
                        "type": "Player/M3U8",
                    }
                )
            return results
        except Exception:
            return []

    def search_anizone(self, title, episode=1):
        """Extraction from Anizone (Updated Search and DOM selection)."""
        base_url = self.anizone_base
        try:
            # 1. Search. anizone migrated to a Livewire app : the search
            #    is /anime?search=… and result links are now ABSOLUTE with
            #    short opaque slugs (…/anime/bmwdgxhk), not title slugs.
            from urllib.parse import quote as _quote
            r = _get(
                f"{base_url}/anime?search={_quote(title)}",
                headers=self.headers,
                timeout=10,
            )

            slugs = re.findall(
                r'href="(?:' + re.escape(base_url) + r')?/anime/([A-Za-z0-9_-]+)"',
                r.text,
            )
            # de-dupe, keep order
            slugs = list(dict.fromkeys(slugs))
            # Slugs are opaque now, so we can't title-match — the first
            # result is anizone's best relevance match.
            best_slug = slugs[0] if slugs else None

            if not best_slug:
                return []

            # 2. Episode page
            ep_url = f"{base_url}/anime/{best_slug}/{episode}"
            r = _get(ep_url, headers=self.headers, timeout=10)

            # Find media-player src (M3U8)
            player_match = re.search(r'<media-player[^>]+src="([^"]+)"', r.text)

            if player_match:
                return [
                    {
                        "source": "Anizone",
                        "quality": "1080p",
                        "url": player_match.group(1),
                        "type": "M3U8",
                    }
                ]
        except Exception:
            pass
        return []

    def search_animetsu(self, title, anilist_id, episode=1):
        """Extraction from Animetsu (Updated Gojo V2 API)."""
        base_api = f"{self.animetsu_api}/v2/api"
        headers = self.animetsu_headers

        try:
            # 1. Search (V2 API)
            r = _get(
                f"{base_api}/anime/search/?query={title}",
                headers=headers,
                timeout=10,
            )
            results = r.json().get("results", [])

            # Find match by title or anilist_id
            gojo_id = None
            for item in results:
                if not isinstance(item, dict):
                    continue
                if str(item.get("anilist_id")) == str(anilist_id):
                    gojo_id = item.get("id")
                    break

            if not gojo_id and results:
                # Fallback to title match
                t_lower = title.lower().strip()
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    titles = item.get("title", {})
                    if not isinstance(titles, dict):
                        continue
                    if (
                        t_lower in (titles.get("english") or "").lower()
                        or t_lower in (titles.get("romaji") or "").lower()
                    ):
                        gojo_id = item.get("id")
                        break

            if not gojo_id:
                return []

            # 2. Servers
            r = _get(
                f"{base_api}/anime/servers/{gojo_id}/{episode}",
                headers=headers,
                timeout=10,
            )
            servers_data = r.json()

            results = []
            if not isinstance(servers_data, list):
                return results
            for server_obj in servers_data:
                if not isinstance(server_obj, dict):
                    continue
                server_id = server_obj.get("id")
                if not server_id:
                    continue

                for lang in ["sub", "dub"]:
                    try:
                        # 3. Stream Links (Oppai endpoint)
                        r = _get(
                            f"{base_api}/anime/oppai/{gojo_id}/{episode}?server={server_id}&source_type={lang}",
                            headers=headers,
                            timeout=10,
                        )
                        stream_data = r.json()
                        sources = stream_data.get("sources", [])

                        # Subtitles
                        subs = []
                        for sub in stream_data.get("subtitles", []):
                            subs.append(
                                {"lang": sub.get("lang"), "url": sub.get("url")}
                            )

                        for src in sources:
                            url = src.get("url")
                            if not url:
                                continue

                            # Apply proxy if relative
                            if not url.startswith("http"):
                                url = f"{self.animetsu_proxy}/{url.lstrip('/')}"

                            results.append(
                                {
                                    "source": f"Animetsu ({lang.upper()} - {server_id})",
                                    "quality": src.get("quality", "1080p"),
                                    "url": url,
                                    "type": (
                                        "M3U8"
                                        if src.get("type") != "video/mp4"
                                        else "MP4"
                                    ),
                                    "subtitles": subs if subs else None,
                                }
                            )
                    except Exception:
                        continue
            return results
        except Exception:
            return []

    def search_hianime_shows(self, title):
        """HiAnime catalogue search → [{slug, title, poster, sub, dub}]."""
        import html as _html
        import urllib.parse as _up

        base = (self.hianime_base or "https://hianime.at").rstrip("/")
        out = []
        try:
            ckey = f"hianime:search:{(title or '').lower()}"
            body = httpcache.get(ckey, 900)
            if body is None:
                r = _get(f"{base}/search?keyword={_up.quote(title or '')}",
                         timeout=12)
                if r.status_code != 200:
                    return out
                body = r.text or ""
                if cacheable_body(body):
                    httpcache.store(ckey, body)
            txt = body
            # The top-10 sidebar repeats result markup — cut it off first
            # (same trick as ani-cli).
            txt = txt.split('id="main-sidebar"')[0]
            # One flw-item block per result : poster + ticks + film-detail.
            blocks = re.split(r'<div class="flw-item', txt)[1:]
            for b in blocks:
                m = re.search(
                    r'<a href="[^"]*/([^"/]*)"[^>]*title="([^"]*)"', b)
                if not m:
                    continue
                slug = m.group(1)
                name = clean_text(_html.unescape(m.group(2)))
                if not slug or not name:
                    continue
                im = re.search(r'<img[^>]+src="([^"]+)"', b)
                sub = re.search(r'tick-sub">\s*<i[^>]*></i>\s*(\d+)', b)
                dub = re.search(r'tick-dub">\s*<i[^>]*></i>\s*(\d+)', b)
                out.append({
                    "slug": slug,
                    "title": name,
                    "poster": im.group(1) if im else "",
                    "sub": sub.group(1) if sub else "",
                    "dub": dub.group(1) if dub else "",
                })
        except Exception:
            pass
        return out

    def latest_hianime(self, limit: int = 15):
        """Latest-Episode homepage section → [{slug, title, poster, ep}]."""
        import html as _html

        base = (self.hianime_base or "https://hianime.at").rstrip("/")
        out = []
        try:
            body = httpcache.get("hianime:home", 300)
            if body is None:
                r = _get(f"{base}/home", timeout=12)
                if r.status_code != 200:
                    return out
                body = r.text or ""
                if body:
                    if cacheable_body(body):
                        httpcache.store("hianime:home", body)
            txt = body
            i = txt.find("Latest Episode")
            seg = txt[i:i + 40000] if i >= 0 else ""
            # Cut at the next section header so only this shelf is read.
            nxt = re.search(r"<h2[^>]*>", seg[100:])
            if nxt:
                seg = seg[:100 + nxt.start()]
            for m in re.finditer(
                    r'<a href="(?:https?://[^/]+)?/([^"/]*-[0-9]+)"[^>]*'
                    r'title="([^"]*)"', seg):
                slug = m.group(1)
                if any(s["slug"] == slug for s in out):
                    continue
                name = clean_text(_html.unescape(m.group(2)))
                em = re.search(
                    r'<a href="(?:https?://[^/]+)?/' + re.escape(slug) +
                    r'"[^>]{0,400}?<img[^>]+src="([^"]+)"', seg)
                if not em:
                    # Poster usually precedes the link in the same item.
                    pos = m.start()
                    im = re.findall(r'<img[^>]+src="([^"]+)"',
                                    seg[max(0, pos - 1500):pos])
                    poster = im[-1] if im else ""
                else:
                    poster = em.group(1)
                ep = ""
                # Episode badge near the link (E12 / EP 12 …), best effort.
                bem = re.search(r"[Ee][Pp]?\s*(\d{1,4})",
                                seg[m.start():m.start() + 600])
                if bem:
                    ep = bem.group(1)
                out.append({"slug": slug, "title": name or slug,
                            "poster": poster, "sub": "", "dub": "",
                            "ep": ep})
                if len(out) >= limit:
                    break
        except Exception:
            pass
        return out

    def get_hianime_episodes(self, slug):
        """[(episode_number, episode_id)] for a HiAnime show slug."""
        base = (self.hianime_base or "https://hianime.at").rstrip("/")
        try:
            m = re.search(r"-(\d+)$", slug or "")
            if not m:
                return []
            ckey = f"hianime:eps:{m.group(1)}"
            cached = httpcache.get(ckey, 900)
            if cached is not None:
                html = json.loads(cached).get("html", "")
            else:
                r = _get(f"{base}/api/theme/episode/list/{m.group(1)}",
                         timeout=12)
                html = r.json().get("html", "")
                if cacheable_body(html):
                    httpcache.store(ckey, json.dumps({"html": html}))
            eps = re.findall(r'data-number="(\d+)"[^>]*data-id="(\d+)"', html)
            return [(int(n), e) for n, e in eps]
        except Exception:
            return []

    def extract_hianime_episode(self, slug, episode=1):
        """Streams for one HiAnime show slug + episode number."""
        import base64 as _b64

        base = (self.hianime_base or "https://hianime.at").rstrip("/")
        results = []
        try:
            eps = self.get_hianime_episodes(slug)
            ep_id = None
            for num, eid in eps:
                if str(num) == str(episode):
                    ep_id = eid
                    break
            if not ep_id:
                return []
            r = _get(
                f"{base}/api/theme/episode/servers?episodeId={ep_id}",
                timeout=12,
            )
            try:
                servers_html = r.json().get("html", "")
            except Exception:
                return []

            for lang in ("sub", "dub"):
                # ZokoAnime first (known payload layout), HD-1 as fallback.
                for server_name in ("ZokoAnime", "HD-1"):
                    try:
                        hm = re.search(
                            r'data-type="' + lang + r'"[^>]*data-server-name="'
                            + re.escape(server_name) + r'"[^>]*data-hash="([^"]*)"',
                            servers_html,
                        )
                        if not hm:
                            continue
                        embed = _b64.b64decode(hm.group(1)).decode("utf-8")
                        origin = embed.split("/")[2]
                        headers = {
                            "Referer": f"https://{origin}/",
                            "Origin": f"https://{origin}",
                        }
                        er = _get(embed, headers=headers, timeout=12)
                        bm = re.search(r'window\.__P="([^"]*)"', er.text or "")
                        if not bm:
                            continue
                        raw = _b64.b64decode(bm.group(1))
                        key = b"otaku-embed-v1"
                        dec = bytes(
                            c ^ key[i % len(key)] for i, c in enumerate(raw)
                        ).decode("utf-8")
                        data = json.loads(dec)
                        stream_url = data.get("src")
                        if not stream_url:
                            continue
                        subs = [
                            {"lang": s.get("label") or s.get("lang"),
                             "url": s.get("src") or s.get("url")}
                            for s in (data.get("subtitles") or [])
                            if isinstance(s, dict)
                            and (s.get("src") or s.get("url"))
                        ]
                        results.append(
                            {
                                "source": f"HiAnime ({lang.upper()} - {server_name})",
                                "quality": "Multi",
                                "url": stream_url,
                                "type": "M3U8",
                                "headers": headers,
                                "subtitles": subs or None,
                            }
                        )
                        break  # one working server per language is enough
                    except Exception:
                        continue
        except Exception:
            pass
        return results

    def search_hianime(self, title, episode=1):
        """Extraction from HiAnime (ani-cli's provider, sub + dub).

        Chain : search page → episodes API → servers API → embed page →
        ``window.__P`` payload (base64 of JSON XOR ``otaku-embed-v1``) →
        master m3u8 + subtitles. Pure stdlib decode, no browser.
        """
        results = []
        try:
            shows = self.search_hianime_shows(title)
            if not shows:
                return []
            t_lower = (title or "").lower().strip()
            slug = None
            for sh in shows:
                if (sh.get("title") or "").lower().strip() == t_lower:
                    slug = sh["slug"]
                    break
            if not slug:
                for sh in shows:
                    if t_lower and t_lower in (sh.get("title") or "").lower():
                        slug = sh["slug"]
                        break
            if not slug:
                slug = shows[0]["slug"]
            results = self.extract_hianime_episode(slug, episode)
        except Exception:
            pass
        return results

    def extract_vo(self, title=None, anilist_id=None, episode=1):
        """Search, deduplication, and sorting."""
        results = []

        if anilist_id:
            results.extend(self.search_sudatchi(anilist_id, episode))
        if title:
            results.extend(self.search_hianime(title, episode))
        if title:
            results.extend(self.search_anizone(title, episode))
        if title and anilist_id:
            results.extend(self.search_animetsu(title, anilist_id, episode))
        if title:
            results.extend(self.search_allanime(title, episode))

        # Simple deduplication by URL
        unique = {}
        for r in results:
            u = r.get("url") if isinstance(r, dict) else None
            if not u or u in unique:
                continue
            unique[u] = r
        return list(unique.values())


# Instantiate a global instance for easy use
goldenanime = AnimeExtractor()
