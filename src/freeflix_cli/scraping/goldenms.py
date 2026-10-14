from curl_cffi import requests as cffi_requests
import urllib.parse
import re
from .config import portals
from ..net_config import DNS_OPTIONS

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)



from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)


def _get(url, **kw):
    """Cloudflare-aware GET (cf_clearance + FlareSolverr cascade)."""
    return cloudflare.cf_get(scraper, url, **kw)


# Xpass /data/* crypto (reversed 2026-10 from their player bundle) : the
# endpoint answers an AES-256-GCM blob (base64url, iv = first 12 bytes)
# keyed by SHA256("spv3-data-response|<build>|<path>|<token>").
_XPASS_KEY_PREFIX = "spv3-data-response|spv3-build-1787821613-50e5fc97c9dce367|"


def _xpass_decrypt_data(body: str, path: str, token: str):
    """Decrypt an Xpass /data/* response body → parsed JSON (or None)."""
    import base64 as _b64
    import hashlib as _hl
    import json as _json

    try:
        parts = (token or "").split(".")
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[1]):
            return None
        key = bytes.fromhex(_hl.sha256(
            (_XPASS_KEY_PREFIX + path + "|" + token).encode()
        ).hexdigest())
        b64 = (body or "").strip().replace("-", "+").replace("_", "/")
        b64 += "=" * ((4 - len(b64) % 4) % 4)
        raw = _b64.b64decode(b64)
        if len(raw) <= 12 + 16:
            return None
        from Crypto.Cipher import AES as _AES
        plain = _AES.new(key, _AES.MODE_GCM, nonce=raw[:12]
                         ).decrypt_and_verify(raw[12:-16], raw[-16:])
        return _json.loads(plain.decode("utf-8"))
    except Exception:
        return None

class MediaExtractor:
    """
    Movie and Series extractor based on CineStream.
    Targets M3U8 streams and video players.
    """

    def __init__(self):
        # --- Source URLs loaded from source_portal.jsonc ---
        self.multi_decrypt_api = portals.get(
            "multi-decrypt", "https://enc-dec.app/api"
        )
        self.videasy_api = portals.get("videasy", "https://api.videasy.net")
        self.vidlink_api = portals.get("vidlink", "https://vidlink.pro")
        self.hexa_api = portals.get("hexa", "https://themoviedb.hexa.su")
        self.mapple_api = portals.get("mapple", "https://mapple.uk")
        self.xpass_api = portals.get("xpass", "https://play.xpass.top")

        # --- Referers ---
        self.videasy_referer = portals.get("videasy-referer", "https://cineby.gd")
        self.hexa_referer = portals.get("hexa-referer", "https://hexa.su/")

        self.headers = {"Connection": "keep-alive"}

    def _quote(self, text):
        return urllib.parse.quote(text).replace("+", "%20")

    def search_videasy(
        self, title, tmdb_id=None, imdb_id=None, year=None, season=None, episode=None
    ):
        """Extraction via Videasy (Multi-server)."""
        headers = {
            "Accept": "*/*",
            "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
            "Origin": self.videasy_referer,
            "Referer": self.videasy_referer + "/",
        }

        servers = [
            "myflixerzupcloud",
            "1movies",
            "moviebox",
            "primewire",
            "m4uhd",
            "hdmovie",
            "cdn",
            "primesrcme",
        ]
        results = []

        if not title:
            return []

        # Double encoding as per CineStream logic
        enc_title = self._quote(self._quote(title))
        media_type = "movie" if season is None else "tv"

        for server in servers:
            try:
                url = f"{self.videasy_api}/{server}/sources-with-title?title={enc_title}&mediaType={media_type}"
                if year:
                    url += f"&year={year}"
                if tmdb_id:
                    url += f"&tmdbId={tmdb_id}"
                if imdb_id:
                    url += f"&imdbId={imdb_id}"
                if season:
                    url += f"&seasonId={season}"
                if episode:
                    url += f"&episodeId={episode}"

                r = _get(url, headers=headers, timeout=10)
                if r.status_code != 200:
                    continue
                enc_data = r.text

                # Decryption via multi-decrypt (passing tmdbId as 'id')
                payload = {"text": enc_data, "id": tmdb_id}
                r_dec = scraper.post(
                    f"{self.multi_decrypt_api}/dec-videasy", json=payload, timeout=10
                )

                if r_dec.status_code == 200:
                    data = r_dec.json().get("result", {})
                    sources = data.get("sources", [])
                    subs = [
                        {"lang": s.get("language"), "url": s.get("url")}
                        for s in data.get("subtitles", [])
                    ]

                    for src in sources:
                        results.append(
                            {
                                "source": f"Videasy ({server.upper()})",
                                "quality": src.get("quality", "Multi"),
                                "url": src.get("url"),
                                "type": (
                                    "M3U8"
                                    if ".m3u8" in src.get("url", "").lower()
                                    else "VIDEO"
                                ),
                                "subtitles": subs if subs else None,
                                "headers": headers,
                            }
                        )
            except Exception:
                continue
        return results

    def search_vidlink(self, tmdb_id, season=None, episode=None):
        """Extraction via Vidlink."""
        if not tmdb_id:
            return []
        try:
            # 1. Encrypt TMDB ID via API
            r_enc = _get(
                f"{self.multi_decrypt_api}/enc-vidlink?text={tmdb_id}", timeout=10
            )
            enc_data = r_enc.json().get("result")
            if not enc_data:
                return []

            headers = {
                "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
                "Connection": "keep-alive",
                "Referer": f"{self.vidlink_api}/",
                "Origin": self.vidlink_api,
            }

            if season is None:
                url = f"{self.vidlink_api}/api/b/movie/{enc_data}"
            else:
                url = f"{self.vidlink_api}/api/b/tv/{enc_data}/{season}/{episode}"

            r = _get(url, headers=headers, timeout=10)
            data = r.json()
            stream = data.get("stream") or {}
            # Legacy shape : a single HLS playlist.
            m3u8_url = stream.get("playlist")

            if m3u8_url:
                return [
                    {
                        "source": "Vidlink",
                        "quality": "Multi",
                        "url": m3u8_url,
                        "type": "M3U8",
                        "headers": headers,
                    }
                ]
            # Current shape : direct per-quality MP4 files (+ captions).
            qualities = stream.get("qualities") or {}
            if isinstance(qualities, dict) and qualities:
                subs = [
                    {"lang": c.get("language"), "url": c.get("url")}
                    for c in (stream.get("captions") or [])
                    if isinstance(c, dict) and c.get("url")
                ]
                out = []
                for q in sorted(qualities, key=lambda h: int(h) if str(h).isdigit() else 0):
                    qd = qualities[q] or {}
                    qurl = qd.get("url") if isinstance(qd, dict) else None
                    if not qurl:
                        continue
                    out.append(
                        {
                            "source": "Vidlink",
                            "quality": f"{q}p",
                            "url": qurl,
                            "type": "VIDEO",
                            "headers": headers,
                            "subtitles": subs or None,
                        }
                    )
                if out:
                    return out
        except Exception:
            pass
        return []

    def search_hexa(self, tmdb_id, season=None, episode=None):
        """Extraction via Hexa with dynamic security handshake."""
        if not tmdb_id:
            return []
        try:
            # 1. Endpoint
            if season is None:
                url = f"{self.hexa_api}/api/tmdb/movie/{tmdb_id}/images"
            else:
                url = f"{self.hexa_api}/api/tmdb/tv/{tmdb_id}/season/{season}/episode/{episode}/images"

            # 2. Security Handshake
            import secrets

            key = secrets.token_hex(32)  # Generate 32-byte key

            # Fetch X-Cap-Token from multi-decrypt
            r_token = _get(f"{self.multi_decrypt_api}/enc-hexa", timeout=10)
            _res = r_token.json().get("result")
            cap_token = _res.get("token") if isinstance(_res, dict) else None
            if not cap_token:
                return []

            headers = {
                "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
                "Accept": "text/plain",
                "X-Api-Key": key,
                "X-Fingerprint-Lite": "e9136c41504646444",
                "Referer": self.hexa_referer,
                "X-Cap-Token": cap_token,
            }

            # 3. Request
            r_enc = _get(url, headers=headers, timeout=10)
            if r_enc.status_code != 200:
                return []
            enc_data = r_enc.text

            # 4. Decrypt
            payload = {"text": enc_data, "key": key}
            r_dec = scraper.post(
                f"{self.multi_decrypt_api}/dec-hexa", json=payload, timeout=10
            )

            if r_dec.status_code == 200:
                data = r_dec.json().get("result", {})
                sources = data.get("sources", [])
                results = []
                for src in sources:
                    results.append(
                        {
                            "source": f"Hexa ({src.get('server', '').upper()})",
                            "quality": "Multi",
                            "url": src.get("url"),
                            "type": "M3U8",
                            "headers": {"Referer": self.hexa_referer},
                        }
                    )
                return results
        except Exception:
            pass
        return []

    def _mapple_token(self, referer: str) -> str | None:
        """Fetch a request token (2026-10 flow).

        The watch page no longer embeds ``window.__REQUEST_TOKEN__`` — the
        frontend bootstraps it via ``POST /api/request-token`` (no body,
        ``Accept: application/json``) which answers
        ``{"token": …, "expiresIn"|"expiresAt": …}``. Returns the token or
        None (Cloudflare may captcha API routes for some IPs — the caller
        then yields no sources instead of crashing).
        """
        import time as _time

        try:
            r = scraper.post(
                f"{self.mapple_api}/api/request-token",
                headers={
                    "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
                    "Referer": referer,
                    "Origin": self.mapple_api,
                    "Accept": "application/json",
                },
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            if not isinstance(data, dict):
                return None
            token = data.get("token")
            if not isinstance(token, str) or len(token) < 3:
                return None
            exp = data.get("expiresAt")
            if isinstance(exp, (int, float)) and exp <= _time.time() * 1000:
                return None
            return token
        except Exception:
            return None

    def search_mapple(self, tmdb_id, season=None, episode=None):
        """Extraction via Mapple."""
        if not tmdb_id:
            return []

        base_url = self.mapple_api
        headers = {
            "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
            "Referer": f"{base_url}/",
        }

        try:
            # 1. Get Token (request-token bootstrap; the watch page no longer
            # embeds one).
            media_type = "movie" if season is None else "tv"
            tv_slug = f"{season}-{episode}" if season else ""
            watch_url = f"{base_url}/watch/{media_type}/{tmdb_id}"
            if season:
                watch_url += f"/{tv_slug}"

            token = self._mapple_token(watch_url)
            if not token:
                # Legacy fallback: an embedded token, if the layout ever
                # carries one again.
                try:
                    r = _get(watch_url, headers=headers, timeout=10)
                    token_match = re.search(
                        r"window\.__REQUEST_TOKEN__\s*=\s*[\"']([^\"']+)[\"']",
                        r.text or "",
                    )
                    token = token_match.group(1) if token_match else None
                except Exception:
                    token = None
            if not token:
                return []

            # 2. Extract Streams (Iterate through sources)
            sources = [
                "mapple",
                "sakura",
                "oak",
                "willow",
                "cherry",
                "pines",
                "magnolia",
                "sequoia",
            ]
            results = []

            for source in sources:
                try:
                    payload = {
                        "data": {
                            "mediaId": int(tmdb_id),
                            "mediaType": media_type,
                            "tv_slug": tv_slug,
                            "source": source,
                        },
                        "endpoint": "stream-encrypted",
                    }

                    r_enc = scraper.post(
                        f"{base_url}/api/encrypt",
                        json=payload,
                        headers=headers,
                        timeout=10,
                    )
                    stream_path = r_enc.json().get("url")
                    if not stream_path:
                        continue

                    if stream_path.startswith("http"):
                        final_url = stream_path
                        sep = "&" if "?" in stream_path else "?"
                    else:
                        sep = "&" if "?" in stream_path else "?"
                        final_url = f"{base_url}{stream_path}"
                    final_url = f"{final_url}{sep}requestToken={token}"
                    r_streams = _get(
                        final_url, headers=headers, timeout=10
                    ).json()

                    if r_streams.get("success"):
                        stream_url = r_streams.get("data", {}).get("stream_url")
                        if stream_url:
                            results.append(
                                {
                                    "source": f"Mapple ({source.upper()})",
                                    "quality": "1080p",
                                    "url": stream_url,
                                    "type": "M3U8",
                                    "headers": {"Referer": f"{base_url}/"},
                                }
                            )
                except Exception:
                    continue
            return results
        except Exception:
            return []

    def search_xpass(self, tmdb_id, season=None, episode=None):
        """Extraction via Xpass (2026-10 layout).

        The old ``href="…/playlist/…"`` links are gone. The embed page now
        carries ``var dataUrl="/data/movie|tv/…?token=…"`` ; that endpoint
        returns an AES-256-GCM blob (see :func:`_xpass_decrypt_data`).
        Decrypted JSON is a list of ``{name, url: /mdata/…/playlist.json}``
        and each playlist.json holds the direct ``file`` (m3u8) entries.
        """
        from concurrent.futures import ThreadPoolExecutor as _Pool

        if not tmdb_id:
            return []

        base_url = self.xpass_api
        try:
            embed_url = (
                f"{base_url}/e/movie/{tmdb_id}"
                if season is None
                else f"{base_url}/e/tv/{tmdb_id}/{season}/{episode}"
            )
            r = _get(embed_url, headers={"Referer": f"{base_url}/"}, timeout=10)
            m = re.search(r'var dataUrl="([^"]+)"', r.text or "")
            if not m:
                return []
            data_url = m.group(1)
            if not data_url.startswith("http"):
                data_url = base_url + data_url

            body = (
                _get(data_url, headers={"Referer": embed_url},
                     timeout=10).text or ""
            ).strip()
            if not body:
                return []
            q = urllib.parse.urlparse(data_url)
            token = (urllib.parse.parse_qs(q.query).get("token") or [""])[0]
            entries = _xpass_decrypt_data(body, q.path, token)
            if not isinstance(entries, list):
                return []

            headers = {"Referer": f"{base_url}/"}

            def _one(entry):
                if not isinstance(entry, dict):
                    return []
                name = entry.get("name") or "Xpass"
                pl = entry.get("url") or ""
                if not pl:
                    return []
                if not pl.startswith("http"):
                    pl = base_url + pl
                try:
                    data = _get(pl, headers=headers, timeout=10).json()
                except Exception:
                    return []
                out = []
                for item in (data.get("playlist") or []) if isinstance(data, dict) else []:
                    for src in (item.get("sources") or []) if isinstance(item, dict) else []:
                        if not isinstance(src, dict):
                            continue
                        file_url = src.get("file")
                        if not file_url:
                            continue
                        out.append({
                            "source": f"Xpass ({name})",
                            "quality": src.get("label") or "Multi",
                            "url": file_url,
                            "type": ("M3U8" if "m3u8" in file_url.lower()
                                     else "VIDEO"),
                            "headers": dict(headers),
                        })
                return out

            results = []
            with _Pool(max_workers=6) as _pool:
                for chunk in _pool.map(_one, entries):
                    results.extend(chunk)
            return results
        except Exception:
            return []

    def extract(
        self,
        title=None,
        tmdb_id=None,
        imdb_id=None,
        year=None,
        season=None,
        episode=None,
    ):
        """Main search method."""
        results = []

        # Priority: Vidlink, Hexa, Xpass, Mapple, Videasy
        if tmdb_id:
            results.extend(self.search_vidlink(tmdb_id, season, episode))
            results.extend(self.search_hexa(tmdb_id, season, episode))
            results.extend(self.search_xpass(tmdb_id, season, episode))
            results.extend(self.search_mapple(tmdb_id, season, episode))

        if title:
            results.extend(
                self.search_videasy(title, tmdb_id, imdb_id, year, season, episode)
            )

        # Deduplication by URL
        unique = {}
        for r in results:
            if r["url"] and r["url"] not in unique:
                unique[r["url"]] = r
        return list(unique.values())


# Instantiate a global instance for easy use
goldenms_extractor = MediaExtractor()
