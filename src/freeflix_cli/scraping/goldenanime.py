from curl_cffi import requests as cffi_requests
import json
import re
from ..proxy import DNS_OPTIONS

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)



from .. import cloudflare


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
                url = src.get("sourceUrl")
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
            r = _get(
                f"{base_url}/anime?search={title}",
                headers=self.headers,
                timeout=10,
            )

            slugs = re.findall(
                r'href="' + re.escape(base_url) + r'/anime/([a-z0-9]+)"',
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
                if item.get("anilist_id") == anilist_id:
                    gojo_id = item["id"]
                    break

            if not gojo_id and results:
                # Fallback to title match
                t_lower = title.lower().strip()
                for item in results:
                    titles = item.get("title", {})
                    if (
                        t_lower in (titles.get("english") or "").lower()
                        or t_lower in (titles.get("romaji") or "").lower()
                    ):
                        gojo_id = item["id"]
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
            for server_obj in servers_data:
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

    def extract_vo(self, title=None, anilist_id=None, episode=1):
        """Search, deduplication, and sorting."""
        results = []

        if anilist_id:
            results.extend(self.search_sudatchi(anilist_id, episode))
        if title:
            results.extend(self.search_anizone(title, episode))
        if title and anilist_id:
            results.extend(self.search_animetsu(title, anilist_id, episode))
        if title:
            results.extend(self.search_allanime(title, episode))

        # Simple deduplication by URL
        unique = {}
        for r in results:
            if r["url"] not in unique:
                unique[r["url"]] = r
        return list(unique.values())


# Instantiate a global instance for easy use
goldenanime = AnimeExtractor()
