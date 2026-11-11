from __future__ import annotations

from curl_cffi import requests
from .deobfuscate import deobfuscate
from bs4 import BeautifulSoup
from ..net_config import DNS_OPTIONS
from ..defaults import DEFAULT_PLAYERS, DEFAULT_NEW_URL, DEFAULT_KAKAFLIX_PLAYERS
import re
import base64
import time
import urllib.parse

import json
import binascii

import threading as _threading

from .utils import ANIME_SAMA_SIGNED_SENTINEL

# Optional callback installed by the Anime-Sama handler: given the player
# headers (which carry the episode slot), return a freshly signed /player/…
# URL. animes-sama.fr no longer publishes player URLs, so the slot sentinel
# can only be turned into something playable through the site's own API.
_signed_resolver = None


def set_signed_player_resolver(fn):
    """Register the animes-sama.fr signed-URL resolver (or None)."""
    global _signed_resolver
    _signed_resolver = fn

# Per-thread session : curl_cffi Session is NOT thread-safe, so when the
# player-analysis runs several extractions in parallel through ONE shared
# session the responses get mixed up (every player loses its quality). Give
# each thread its own session.
_session_tls = _threading.local()


def _scraper():
    s = getattr(_session_tls, "s", None)
    if s is None:
        s = requests.Session(curl_options=DNS_OPTIONS)
        _session_tls.s = s
    return s


# Main-thread session kept under the old name for any external reference.
scraper = _scraper()

# Extra headers learned while resolving a stream (e.g. Vidzy's gate cookie).
# get_hls_link() only returns a URL, so playback/download merges these in.
_resolved_headers = {}
_resolved_headers_lock = _threading.Lock()


def set_stream_headers(url: str, headers: dict) -> None:
    with _resolved_headers_lock:
        _resolved_headers[url] = (dict(headers or {}), time.time())
        # Bound the cache on long sessions.
        if len(_resolved_headers) > 200:
            oldest = sorted(_resolved_headers.items(),
                            key=lambda kv: kv[1][1])[:50]
            for key, _ in oldest:
                _resolved_headers.pop(key, None)


def get_stream_headers(url: str) -> dict:
    with _resolved_headers_lock:
        ent = _resolved_headers.get(url)
    if not ent or time.time() - ent[1] > 3600:
        return {}
    return dict(ent[0])


from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)


def _get(url, **kw):
    """Cloudflare-aware GET (cf_clearance + FlareSolverr cascade), per thread."""
    kw.setdefault("timeout", 20)  # un host mort ne doit jamais geler l'UI
    return cloudflare.cf_get(_scraper(), url, **kw)


try:
    from ..i18n import t
except ImportError:  # pragma: no cover
    def t(s: str) -> str:
        return s


def _url_host(url: str) -> str:
    """Hostname minuscule d'une URL, "" si inparsable (jamais d'exception)."""
    try:
        return (urllib.parse.urlparse(url or "").hostname or "").lower()
    except Exception:
        return ""


def _host_matches(host: str, key: str) -> bool:
    """La clé matche-t-elle ce hostname, alignée aux labels DNS ?
    Évite les faux positifs de substring (book.ru ne matche PAS ok.ru),
    tout en gardant les préfixes (fsvid ↔ fsvid.lol) et suffixes
    multi-labels (x.coflix.upn ↔ coflix.upn)."""
    if not host or not key:
        return False
    key = key.lower()
    if host == key:
        return True
    labels = host.split(".")
    if key in labels:
        return True
    if host.startswith(key + ".") or host.endswith("." + key):
        return True
    return False

# vidmoly's live domain is .net ; .to is a PARKED ad domain, .biz/.me are 404.
_VIDMOLY_FIX = {
    "vidmoly.to": "vidmoly.net",
    "vidmoly.biz": "vidmoly.net",
    "vidmoly.me": "vidmoly.net",
}

players = dict(DEFAULT_PLAYERS)
new_url = dict(DEFAULT_NEW_URL)
new_url.pop("vidmoly.net", None)
new_url.update(_VIDMOLY_FIX)
kakaflix_players = dict(DEFAULT_KAKAFLIX_PLAYERS)

# Per-thread current player config, so several extractions can run in
# parallel (e.g. analysing every player's resolutions at once) without
# clobbering each other.
_apc = _threading.local()


def _set_apc(cfg):
    _apc.config = cfg


def _get_apc():
    return getattr(_apc, "config", None)


def extract_hls_url(unpacked_code):
    pattern = r'(https?://[^"\'\\\s]*master\.txt[^"\'\\\s]*)'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    pattern = r'(https?://[^"\'\\\s]*master\.m3u8[^"\'\\\s]*)'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    pattern = r'(https?://[^"\'\\\s]*\.m3u8[^"\'\\\s]*)'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    return None


def get_hls_link_default(url: str, headers: dict) -> str:
    """
    Extract HLS link from default player.
    """
    cfg = _get_apc() or {}

    use_headers = headers = headers or {}
    if cfg.get("m3u8-extractor"):
        if cfg.get("m3u8-extractor").get("no-header"):
            use_headers = {}

    response = _get(url, headers=use_headers, impersonate="chrome")

    # Some hosts (e.g. fsvid) now REQUIRE the page referer despite the
    # 'no-header' config flag and return 403 without it. Retry once with
    # the original headers before giving up.
    if response.status_code == 403 and use_headers is not headers and headers:
        response = _get(url, headers=headers, impersonate="chrome")

    response.raise_for_status()

    try:
        code = deobfuscate(response.text)
    except Exception:
        code = None
    link = extract_hls_url(code) if code else None
    if not link:
        # Plain (non-packed) embeds keep the stream URL in the raw HTML —
        # e.g. ansembed's JWPlayer `sources: [{file: '…master.m3u8…'}]` block,
        # which packer.unpack() drops when the page also ships a packed
        # payload. Fall back to the raw page before giving up.
        link = extract_hls_url(response.text)
    return link


def get_hls_link_embed4me(embed_url: str) -> str:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    """
    Extract HLS link from embed4me player.
    Code adapted from: https://github.com/SertraFurr/Anime-Sama-Downloader/blob/main/src/utils/extract/extract_embed4me_video_source.py

    Args:
        embed_url: The embed URL of the player.

    Returns:
        The HLS stream URL or None if not found.
    """

    KEY = b"kiemtienmua911ca"
    IV = b"1234567890oiuytr"

    def _decrypt_data(hex_str):
        try:
            data = binascii.unhexlify(hex_str)
            cipher = AES.new(KEY, AES.MODE_CBC, IV)
            decrypted = unpad(cipher.decrypt(data), AES.block_size)
            return decrypted.decode("utf-8")
        except Exception:
            return None

    match = re.search(r"#([a-zA-Z0-9]+)", embed_url)
    if not match:
        match = re.search(r"[?&]id=([a-zA-Z0-9]+)", embed_url)
    if not match:
        return None

    video_id = match.group(1)
    url_host = _url_host(embed_url)
    if not url_host:
        return None
    url_root = "https://" + url_host
    api_url = f"{url_root}/api/v1/video?id={video_id}&w=1920&h=1080&r={url_root}"

    headers = {"Referer": url_root}

    r = _get(api_url, headers=headers, impersonate="chrome", timeout=10)
    r.raise_for_status()

    hex_data = r.text.strip()
    if hex_data.startswith('"') and hex_data.endswith('"'):
        hex_data = hex_data[1:-1]

    decrypted = _decrypt_data(hex_data)
    if not decrypted:
        return None
    try:
        data = json.loads(decrypted)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    # Legacy layout : a direct {"source": "…m3u8"}.
    source = data.get("source")
    if source:
        return source if source.startswith("http") else url_root + source

    # 2026 layout : no single "source" — the stream lives on one of several
    # CDNs, chosen by streamingConfig.order. Each CDN maps to its own path key,
    # and the final URL is {cdn.domain}{path}?{cdn.params}. In-House has no
    # external domain → served from the embed host itself.
    #   Tiktok→hlsVideoTiktok · Google→hlsVideoGoogle · Cloudflare→cfNative ·
    #   In-House→source  (from the player bundle's own mapping).
    paths = {
        "Tiktok": data.get("hlsVideoTiktok"),
        "Google": data.get("hlsVideoGoogle"),
        "Cloudflare": data.get("cfNative"),
        "In-House": data.get("source"),
    }
    sc = data.get("streamingConfig")
    if isinstance(sc, str):
        try:
            sc = json.loads(sc)
        except (ValueError, TypeError):
            sc = None
    if isinstance(sc, dict) and isinstance(sc.get("order"), list):
        adjust = sc.get("adjust") or {}
        for cdn in sc["order"]:
            path = paths.get(cdn)
            if not path:
                continue
            adj = adjust.get(cdn) or {}
            if adj.get("disabled") and cdn != "In-House":
                continue
            domain = adj.get("domain")
            if domain:
                params = adj.get("params")
                query = urllib.parse.urlencode(params) if isinstance(params, dict) and params else ""
                built = f"https://{domain}{path}" + (f"?{query}" if query else "")
            else:
                built = path if path.startswith("http") else url_root + path
            return built

    # Last resort : any *hlsVideo* path we can turn absolute.
    for k, v in data.items():
        if isinstance(v, str) and k.lower().startswith("hlsvideo") and v:
            return v if v.startswith("http") else url_root + v
    return None


def get_hls_link_uqload(url: str, headers: dict) -> str:
    """
    Extract HLS link from uqload players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    # uqload rotates its domain (uqload.is / .vc / .cx…). Use the EMBED's own
    # host for the Referer instead of a hardcoded one, so a domain change
    # doesn't break extraction — and the token the CDN signs matches.
    host = _url_host(url) or "uqload.vc"
    headers = headers or {}
    response = _get(
        url.replace("embed-", ""),
        headers={**headers, "Referer": f"https://{host}/"},
        impersonate="chrome",
    )
    response.raise_for_status()

    text = response.text
    if embed_is_placeholder(text):
        return None  # locked / deleted file: the row must not look playable
    # uqload now ships the player JS packed (dean-edwards). Unpack first.
    try:
        code = deobfuscate(text)
    except Exception:
        code = text
    haystack = (code or "") + "\n" + text

    # Modern layout : a signed fsvid-family HLS `…/.urlset/master.m3u8?t=…`
    # (served with the embed's Origin). Legacy : sources:[{file:"…mp4"}].
    candidate = None
    for pat in (
        r'file:\s*"([^"]+\.(?:m3u8|mp4)[^"]*)"',
        r'sources:\s*\[\s*"([^"]+)"',
        r'(https?://[^\s"\']+\.m3u8[^\s"\']*)',
        r'(https?://[^\s"\']+\.mp4[^\s"\']*)',
    ):
        m = re.search(pat, haystack)
        if m:
            candidate = m.group(1)
            break

    if not candidate:
        return None  # graceful : caller shows 'try another player'

    # uqload always serves a signed fsvid-family HLS, so it gets the same
    # Referer/Cookie treatment as fsvid (some edges 403 otherwise). It also
    # sometimes answers with a ~30 s ad/preview instead of the episode: the
    # duration probe below rejects it so the caller falls back to another
    # player, and the text says why (it also runs in the ad check).
    set_stream_headers(candidate, {
        "Referer": f"https://{host}/",
        "Origin": f"https://{host}",
    })

    # Some uqload embeds answer with a ~30 s ad/preview placeholder instead of
    # the episode. It still looks like a valid HLS master and would otherwise
    # play. Probe the media playlist's total EXTINF and reject clearly-too-short
    # streams so the caller falls back to another player.
    if ".m3u8" in candidate:
        dur = _hls_duration_seconds(candidate, headers)
        if dur is not None and dur < 90:
            return None
    return candidate


def _hls_duration_seconds(url: str, headers: dict = None,
                          timeout: int = 8):
    """Total EXTINF duration of an HLS media playlist (None if unknown).

    Follows a master playlist's first variant. Best-effort: any network or
    parsing issue returns None so extraction never fails because of this
    validation. Used to reject uqload's short ad/preview placeholder.
    """
    try:
        import m3u8 as _m3u8

        r = _get(url, headers=headers or {}, impersonate="chrome",
                 timeout=timeout)
        r.raise_for_status()
        text = r.text or ""
        obj = _m3u8.loads(text, uri=url)
        if obj.playlists:
            variant = obj.playlists[0]
            try:
                vurl = variant.absolute_uri
            except Exception:
                vurl = variant.uri
            rv = _get(vurl, headers=headers or {}, impersonate="chrome",
                      timeout=timeout)
            rv.raise_for_status()
            obj = _m3u8.loads(rv.text or "", uri=vurl)
        total = sum(float(seg.duration or 0) for seg in obj.segments)
        return total if total > 0 else None
    except Exception:
        return None


def get_hls_link_sendvid(url: str) -> str:
    """
    Extract video link from sendvid using the <source> tag's direct file URL.

    NOTE: the ``og:video`` meta tag only holds a generic ``/xxx.mp4`` page URL
    that answers ``text/html`` (mpv: "Failed to recognize file format") — the
    REAL file is the signed ``videosN.sendvid.com/…mp4?…`` URL in
    ``<source src=…>``. Prefer it, keep og:video as a last resort.

    Args:
        url: Player URL

    Returns:
        Video URL
    """
    response = _get(url, impersonate="chrome")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    source = soup.find("source")
    if source and source.attrs.get("src"):
        link = source.attrs["src"]
        return None if _is_sendvid_placeholder(link) else link

    og = soup.find("meta", {"property": "og:video"})
    if og and og.attrs.get("content"):
        return og.attrs["content"]
    return None


# Sendvid serves a ~36 KB / 5 s placeholder MP4 for deleted/missing files
# (same tiny file for every dead embed — e.g. Frieren's sendvid players)
# instead of 404ing. A real episode is tens/hundreds of MB, so reject a
# resolved file that advertises < 1 MB and let the caller fall back to a
# host with the real content. Fail-open : no Content-Length → keep it.
_SENDVID_MIN_BYTES = 1_000_000


def _is_sendvid_placeholder(link: str) -> bool:
    try:
        r = _scraper().head(
            link, headers={"Referer": "https://sendvid.com/"},
            impersonate="chrome", timeout=10,
        )
        cl = r.headers.get("Content-Length") or r.headers.get("content-length")
        return cl is not None and int(cl) < _SENDVID_MIN_BYTES
    except Exception:
        return False


def get_hls_link_sibnet(url: str, headers: dict = None) -> str:
    """
    Extract video link from sibnet.

    Args:
        url: Player URL
        headers: HTTP headers for the request (sibnet 403s without Referer)

    Returns:
        Video URL
    """
    h = dict(headers or {})
    h.setdefault("Referer", url)
    response = _get(url, headers=h, impersonate="chrome")
    response.raise_for_status()

    try:
        relative_path = response.text.split('player.src([{src: "')[1].split('"')[0]
        return "https://video.sibnet.ru" + relative_path
    except (IndexError, AttributeError):
        return None


def get_hls_link_filemoon(url: str, headers: dict) -> str:
    from Crypto.Cipher import AES
    """
    Extract HLS link from filemoon players.
    Follows iframe redirect and deobfuscates JavaScript.

    Args:
        url: Player URL

    Returns:
        HLS stream URL
    """

    def decode_base64(text):
        """Decodes URL-safe Base64 with proper padding."""
        if not text:
            return b""
        # Add padding if necessary and decode
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    def try_decrypt(key, iv, full_payload):
        """Tries to decrypt the payload using two common GCM tag positions."""

        # Combination 1: Authentication Tag at the end (Standard AES-GCM)
        try:
            ciphertext = full_payload[:-16]
            tag = full_payload[-16:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        except Exception:
            pass

        # Combination 2: Authentication Tag at the beginning
        try:
            tag = full_payload[:16]
            ciphertext = full_payload[16:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        except Exception:
            pass

        return None

    def solve_decryption(json_str):
        """Parses the JSON and attempts multiple key combinations for decryption."""
        data = json.loads(json_str)
        playback = data.get("playback", {})

        # 1. Prepare potential keys
        key_parts = playback.get("key_parts", [])
        decrypt_keys = playback.get("decrypt_keys", {})

        potential_keys = []

        # Hypothesis A: Concatenate key_parts[0] + key_parts[1]
        if len(key_parts) >= 2:
            part0 = decode_base64(key_parts[0])
            part1 = decode_base64(key_parts[1])
            potential_keys.append(part0 + part1)
            potential_keys.append(part1 + part0)

        # Hypothesis B: Concatenate edge_1 + edge_2 (16 + 16 = 32 bytes for AES-256)
        if "edge_1" in decrypt_keys and "edge_2" in decrypt_keys:
            edge1 = decode_base64(decrypt_keys["edge_1"])
            edge2 = decode_base64(decrypt_keys["edge_2"])
            potential_keys.append(edge1 + edge2)

        # 2. Prepare data
        iv = decode_base64(playback.get("iv"))
        payload = decode_base64(playback.get("payload"))

        # 3. Test all key combinations
        for _i, key in enumerate(potential_keys):
            result = try_decrypt(key, iv, payload)
            if result:
                return result

        print(t("Error: No valid decryption found."))
        return None

    code = url.split("/")[-1]
    headers = headers or {}
    try:
        response = _get(
            "https://9n8o.com/api/videos/" + code + "/embed/playback",
            impersonate="chrome",
            headers={
                "Referer": "https://9n8o.com/g1x/" + code + "/",
                "X-Embed-Origin": headers.get("Referer", "")
                .removeprefix("https://")
                .removesuffix("/"),
                "X-Embed-Parent": "https://filemoon.sx/e/" + code,
                "X-Embed-Referer": headers.get("Referer", ""),
            },
        )
    except Exception:
        return None

    # filemoon migrated to a client-side SPA ('Byse Frontend') ; the old
    # 9n8o.com playback API now returns 405. Until/unless a new server-side
    # path is found, fail gracefully so the caller offers another player
    # instead of dumping an HTTP 405 traceback.
    if response.status_code != 200:
        return None

    decrypted_json_str = solve_decryption(response.text)
    if decrypted_json_str:
        try:
            video_data = json.loads(decrypted_json_str)
            return video_data["sources"][0]["url"]
        except Exception:
            return None
    return None


def get_hls_link_vidoza(url: str, headers: dict) -> str:
    """
    Extract HLS link from vidoza players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """

    response = _get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    source = soup.find("source")
    if source and source.attrs.get("src"):
        return source.attrs["src"]
    return None


def get_hls_link_kakaflix(url: str, headers: dict) -> str:
    """
    Extract HLS link from kakaflix players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = _get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    try:
        link: str = soup.find("iframe").attrs["src"]
    except Exception:
        # Pas d'iframe : ne re-dispatch que si l'URL a changé (redirect vers
        # un autre host), sinon récursion infinie garantie sur le même host.
        final = str(getattr(response, "url", "") or "")
        if not final or _url_host(final) == _url_host(url):
            return None
        return get_hls_link(final, headers)
    else:
        return get_hls_link(link, headers)


def get_hls_link_myvidplay(url: str, headers: dict) -> str:
    """
    Extract HLS link from myvidplay players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = _get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    try:
        link = response.text.split("vtt: '")[1].split("'")[0]
    except IndexError:
        return None

    return link or None


def get_hls_link_vidmoly(url: str, headers: dict) -> str:
    """
    Dedicated parser for Vidmoly to bypass transitional page.
    Mimics an iframe request behavior.
    """
    # Specific headers observed in browser iframe test
    vidmoly_headers = {
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Upgrade-Insecure-Requests": "1",
        # Explicitly removing Referer as data: URL worked without it
        "Referer": "",
    }

    # Merge but prioritize our specific headers
    final_headers = {**(headers or {}), **vidmoly_headers}
    # Ensure Referer is actually removed if we mapped it to empty string/None
    if "Referer" in final_headers and not final_headers["Referer"]:
        del final_headers["Referer"]

    response = _get(
        url,
        headers=final_headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    return extract_hls_url(response.text)


def get_hls_link_veev(url):
    """
    Extract HLS link from Veev players.
    Converted from https://github.com/phisher98/cloudstream-extensions-phisher/blob/master/Coflix/src/main/kotlin/com/Coflix/Extractor.kt

    Args:
        url: Player URL

    Returns:
        HLS stream URL or None if extraction fails
    """

    # 1. Extract Media ID
    media_id_match = re.search(
        r"(?://|\.)(?:veev|kinoger|poophq|doods)\.(?:to|pw|com)/[ed]/([0-9A-Za-z]+)",
        url,
    )
    if not media_id_match:
        return None
    media_id = media_id_match.group(1)

    # 2. Fetch HTML
    try:
        html = _get(f"https://veev.to/e/{media_id}", impersonate="chrome").text
    except Exception as e:
        print(f"{t('Connection error:')} {e}")
        return None

    # 3. Extract encrypted tokens
    enc_regex = r"""[.\s'](?:fc|_vvto\[[^]]*)(?:['\]]*)?\s*[:=]\s*['"]([^'"]+)"""
    found_values = re.findall(enc_regex, html)
    if not found_values:
        return None

    # --- Internal helper functions ---
    def veev_decode(etext):
        # LZW-style decompression algorithm
        lut = {i: chr(i) for i in range(256)}
        n = 256
        c = etext[0]
        result = [c]
        for char in etext[1:]:
            code = ord(char)
            entry = lut[code] if code in lut else c + c[0]
            result.append(entry)
            lut[n] = c + entry[0]
            n += 1
            c = entry
        return "".join(result)

    def parse_rules(encoded):
        # We only take the first "row" of rules, matching Kotlin's buildArray(ch)[0]
        it = iter(encoded)

        def next_int():
            try:
                char = next(it)
                return int(char) if char.isdigit() else 0
            except StopIteration:
                return 0

        count = next_int()
        if count == 0:
            return []
        row = [next_int() for _ in range(count)]
        return row[::-1]  # Reversed as in the Kotlin code

    def decode_final(encoded, rules):
        text = encoded
        for r in rules:
            if r == 1:
                text = text[::-1]  # Reverse string
            try:
                # Hex to Bytes to UTF-8
                text = bytes.fromhex(text).decode("utf-8")
            except ValueError:
                pass  # Avoid crash if hex is invalid
            text = text.replace("dXRmOA==", "")  # Remove salt
        return text

    # 4. Main loop
    for f in reversed(found_values):
        ch = veev_decode(f)
        if ch == f:
            continue  # If decoding didn't change anything, skip

        # API call to get JSON
        dl_url = f"https://veev.to/dl?op=player_api&cmd=gi&file_code={media_id}&r=https://veev.to&ch={ch}&ie=1"
        try:
            resp = _get(dl_url, impersonate="chrome").json()
        except Exception:
            continue

        file_obj = resp.get("file")
        if not isinstance(file_obj, dict) or file_obj.get("file_status") != "OK":
            continue

        # Kotlin equivalent: file.getJSONArray("dv")
        dv_list = file_obj.get("dv")

        # Verify it is indeed a list and not empty
        if not dv_list or not isinstance(dv_list, list):
            continue

        # Kotlin equivalent: .getJSONObject(0).getString("s")
        first = dv_list[0]
        dv_string = first.get("s") if isinstance(first, dict) else None

        if not dv_string:
            continue

        # Final decoding steps
        step1 = veev_decode(dv_string)
        rules = parse_rules(ch)  # Rules come from 'ch'
        final_link = decode_final(step1, rules)

        return final_link

    return None


def get_hls_link_xtremestream(url, headers):
    """xtremestream (Coflix "Vidéo HD et 1080p") → xs1.php manifest.

    The xs1.php endpoint answers **403** unless the *player page itself* is
    the Referer; without it the probe said "resolved", showed a quality and
    then played a 404 page. Keep that Referer for the manifest AND every
    segment (stored with the URL, mpv/yt-dlp pick it up).
    """
    try:
        data_id = url.split("?data=")[1].split("&")[0].split("#")[0]
    except IndexError:
        return None
    if not data_id:
        return None
    url_root = _url_host(url)
    if not url_root:
        return None

    link = f"https://{url_root}/player/xs1.php?data={data_id}"
    h = dict(headers or {})
    h["Referer"] = url
    h.setdefault("Origin", f"https://{url_root}")
    set_stream_headers(link, h)
    return link


def get_hls_link_dood(url: str, headers: dict, player_host: str = None) -> str | None:
    """
    DoodStream mirrors (playmogo.com, doodstream mirrors reached via
    french-stream's kokoflix proxy).

    The /e/ page embeds a same-origin token path which the player fetches
    via AJAX (``$.get('/pass_md5/<token>')``) ; that endpoint answers the
    DIRECT mp4 URL as plain text. Reproduce both calls with the browser's
    headers (Referer + X-Requested-With).

    *player_host* is the CONFIGURED mirror (e.g. ``playmogo.com``) when
    *url* is a signed proxy link (kokoflix ``*_go.php?id=…``): the
    ``pass_md5`` token lives on that host, not on the proxy.
    """
    h = dict(headers or {})
    url_host = _url_host(url)
    host = player_host or url_host
    if not host:
        return None
    h.setdefault("Referer", f"https://{host}/")
    resp = _get(url, headers=h, impersonate="chrome")
    try:
        resp.raise_for_status()
    except Exception:
        return None
    body = resp.text or ""
    if embed_is_placeholder(body):
        return None  # "We can't find the video" → dead row, not a player
    m = re.search(r"/pass_md5/[^\"'\s]*", body)
    if not m:
        return None
    h2 = dict(h)
    h2["X-Requested-With"] = "XMLHttpRequest"
    # The AJAX token lives on the page that SERVES the player: the mirror
    # itself, or the proxy host that redirected there (kokoflix → playmogo).
    token_host = url_host if player_host else host
    try:
        r2 = _get(f"https://{token_host}" + m.group(0), headers=h2,
                  impersonate="chrome")
        r2.raise_for_status()
    except Exception:
        return None
    link = (r2.text or "").strip()
    if not link.startswith("http"):
        return None
    # DoodStream serves the media only when the URL looks like the browser
    # one: a random 10-char suffix + the page's token as a query parameter.
    if not re.search(r"\.mp4($|\?)", link):
        import random
        import string
        token = re.search(r'\?token=([^&"\'\s]+)', body) or re.search(
            r"token[\"']?\s*[:=]\s*[\"']([^\"']+)", body)
        suffix = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        link += suffix + "?token=" + (token.group(1) if token else "")
    set_stream_headers(link, {
        "Referer": f"https://{url_host or host}/",
        "Origin": f"https://{url_host or host}",
    })
    return link


_OFFLINE_HOST_MARKERS = (
    "filemoon", "byse", "minochinos", "netu", "upn", "vidmoly",
    "coflix.upn", "mixdrop", "streamtape", "dood.li", "d0000d", "d000d",
    # 2026-11 audit : veev.to no longer answers (TLS hang on every region we
    # tested) and vidhsareup.io lost its DNS. Both were still offered because
    # the extractor *type* exists; hide the dead hosts, not the family
    # (poophq / kinoger still share the veev extractor).
    "veev.to", "vidhsareup",
    # 2026-11-11 audit : oneupload.to answers "Connection refused" from six
    # countries (HK/ID/IR/TR/…) AND from here, on every path — the host is
    # gone, so Anime-Sama's "Lecteur 1" on many series can never play.
    "oneupload",
)


def is_known_offline(url: str) -> bool:
    """True when a host is known DEAD upstream (2026-11 audit).

    Those embeds answer with placeholders (or hang on dead CDNs). Listing
    them with a fake quality badge was the #1 false positive on
    French-Stream, so the player menu hides them instead of offering a
    stream that can never start. The user explicitly asked for them not to
    be shown again.
    """
    host = _url_host(url)
    if not host:
        return False
    return any(marker in host for marker in _OFFLINE_HOST_MARKERS)


_BYSE_API_RE = re.compile(r"/api/videos/([A-Za-z0-9_-]+)/embed/details")


def get_hls_link_byse(url: str, headers: dict) -> str | None:
    """Byse Frontend embeds (filemoon.sx, bysewihe.com, bysebuho.com…).

    The 2026 filemoon family dropped the AES/JSON payload: the shell page
    only loads a React bundle, and the "video record missing" placeholder is
    served with HTTP **200** for removed files. So :
      1. ask the JSON API ``/api/videos/<code>/embed/details`` (Referer must
         be the embed) — a 404 means the file is gone → None ;
      2. otherwise the playback config comes from a POST to
         ``/api/videos/<code>/embed/playback`` (AES-GCM keyed by key_parts).
         That endpoint answers 405 from the datacenter/CLI path, so we fall
         back to any plain ``sources:"…"`` left in the shell and, failing
         that, return None (the player is reported unavailable) instead of
         showing a row that will never play.
    """
    h = dict(headers or {})
    host = _url_host(url) or "filemoon.sx"
    h.setdefault("Referer", url)
    h.setdefault("Origin", f"https://{host}")
    try:
        resp = _get(url, headers=h, impersonate="chrome", timeout=20)
        body = resp.text or ""
    except Exception:
        return None
    if embed_is_placeholder(body):
        return None

    m = _BYSE_API_RE.search(body)
    code = None
    if m:
        code = m.group(1)
    else:
        cm = re.search(r"/e/([A-Za-z0-9_-]+)", url or "")
        code = cm.group(1) if cm else None

    if code:
        api = f"https://{host}/api/videos/{code}/embed/details"
        try:
            ar = _get(api, headers={"Referer": url, "Origin": f"https://{host}",
                                    "Accept": "application/json"},
                      impersonate="chrome", timeout=15)
            if getattr(ar, "status_code", 0) == 404:
                return None  # video record missing → dead embed (HTTP 200 shell)
        except Exception:
            pass  # transient API hiccup: try the page payload below

    # Plain (non-obfuscated) sources line, when the shell ships one.
    packed = unpack_dean_edwards(body)
    for text in (packed, body):
        for hit in re.finditer(
            r'sources\s*:\s*\[?\{?\s*(?:src|file)\s*:\s*"([^"]+\.(?:m3u8|mp4)[^"]*)"',
            text or "",
        ):
            link = hit.group(1)
            if _is_decoy_stream(link) or not _looks_like_stream(link):
                continue
            intro = re.search(r"intro|teaser|trailer|preview", link, re.I)
            if intro:
                continue
            set_stream_headers(link, {
                "Referer": f"https://{host}/",
                "Origin": f"https://{host}",
            })
            return link
    return None


def _voe_substitution_decode(payload: str, radix: int, table: list) -> str:
    """Emulate the voe/luluvdo packer loop :
    ``while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c])``.
    Pure (no network) : testable.
    """
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"

    def _to_base(n: int) -> str:
        if n == 0:
            return "0"
        out = ""
        while n:
            out = digits[n % radix] + out
            n //= radix
        return out

    p = payload or ""
    c = len(table)
    while c:
        c -= 1
        if c < len(table) and table[c]:
            p = re.sub(r"\b" + _to_base(c) + r"\b", table[c], p)
    return p


_VOE_ROT13 = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
)


def _voe_decode_config(text: str) -> str | None:
    """Decode voe's 2026 JSON config blob (see get_hls_link_voe)."""
    s = (text or "").strip().translate(_VOE_ROT13)
    for marker in ("@$", "^^", "~@", "%?", "*~", "!!", "#&"):
        s = s.replace(marker, "_")
    s = s.replace("_", "")
    try:
        step1 = base64.b64decode(s + "=" * (-len(s) % 4))
    except Exception:
        return None
    try:
        step2 = "".join(chr(b - 3) for b in step1)
    except Exception:
        return None
    step3 = step2[::-1]
    try:
        step4 = base64.b64decode(step3 + "=" * (-len(step3) % 4))
    except Exception:
        return None
    return step4.decode("utf-8", "ignore")


def embed_status(status: int) -> str:
    """Coarse state of an embed page: ``ok`` / ``dead`` (404/410) / ``blocked``.

    Hosts (voe, lulustream, vidmoly…) keep the embed row in the source API
    long after the file is gone: the page answers 404. Showing it in the
    player list then fails on play, so extractors use this to tell "gone"
    apart from "temporary error" (keep the row on a hiccup).
    """
    try:
        status = int(status)
    except (TypeError, ValueError):
        return "blocked"
    if status in (404, 410):
        return "dead"
    if status in (401, 403, 429):
        return "blocked"
    if status == 200:
        return "ok"
    return "blocked"


def get_hls_link_voe(url: str, headers: dict) -> str | None:
    """
    Voe mirrors (voe.sx, luluvdo.com, reached via french-stream's kokoflix).

    Two generations are supported:
      * 2024/25 — the JWPlayer setup hides the URL behind a word-substitution
        packer (``eval(function(p,a,c,k,e,d){while(c--)…})``);
      * 2026 — ``/e/<code>`` is a stub redirecting to a rotating mirror whose
        <script type="application/json"> config is doubly obfuscated and
        carries the HLS URL in ``source`` (mp4 in ``fallback``).
    """
    h = dict(headers or {})
    try:
        host = url.split("/")[2]
    except Exception:
        return None
    h.setdefault("Referer", f"https://{host}/")
    resp = _get(url, headers=h, impersonate="chrome")
    try:
        resp.raise_for_status()
    except Exception:
        return None
    body = resp.text or ""
    if embed_is_placeholder(body):
        return None  # removed / locked file → dead row, not a player

    # 2026 voe: /e/<code> is now a stub that redirects to a rotating mirror
    # (derricknationtop.com, …) which ships a plain jwplayer config
    # (`sources: [{file: "…"}]`) instead of the old packed JS.
    m_red = re.search(r"window\.location\.href\s*=\s*['\"](https?://[^'\"]+)['\"]",
                      body[:4000])
    if m_red:
        nxt = m_red.group(1)
        try:
            r2 = _get(nxt, headers={**h, "Referer": url}, impersonate="chrome")
            r2.raise_for_status()
            body = r2.text or ""
        except Exception:
            return None

    # Current voe embeds ship a doubly-obfuscated <script
    # type="application/json"> config: ROT13 → strip "@$^^~@%?*~!!#&" → remove
    # "_" → base64 → shift chars by -3 → reverse → base64 → JSON.
    m_cfg = re.search(
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        body, re.S,
    )
    if m_cfg:
        try:
            raw = _voe_decode_config(m_cfg.group(1))
            if raw:
                data = json.loads(raw)
                item = data[0] if isinstance(data, list) else data
                for src in (item.get("sources") or []):
                    f = src.get("file") if isinstance(src, dict) else None
                    if f and f.startswith("http"):
                        return f
                for fld in ("source", "file", "url", "src"):
                    f = item.get(fld) if isinstance(item, dict) else None
                    if isinstance(f, str) and f.startswith("http"):
                        return f
                for fb in (item.get("fallback") or []):
                    f = fb.get("file") if isinstance(fb, dict) else None
                    if f and f.startswith("http"):
                        return f
        except Exception:
            pass

    m_file = re.search(
        r"""['"]file['"]\s*:\s*['"]([^'"]+\.(?:m3u8|mp4)[^'"]*)['"]""", body
    )
    if m_file:
        return m_file.group(1)
    i = body.find("eval(function(p,a,c,k,e,d)")
    if i < 0:
        return extract_hls_url(body)
    m = re.search(r"\}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)",
                  body[i:i + 20000], re.DOTALL)
    if not m:
        return extract_hls_url(body)
    try:
        radix = int(m.group(2))
    except ValueError:
        return extract_hls_url(body)
    decoded = _voe_substitution_decode(m.group(1), radix, m.group(4).split("|"))
    for pat in (
        r'file\s*:\s*"([^"]+\.m3u8[^"]*)"',
        r'file\s*:\s*"([^"]+\.mp4[^"]*)"',
    ):
        f = re.search(pat, decoded)
        if f:
            return f.group(1)
    return extract_hls_url(decoded) or extract_hls_url(body)


def get_hls_link_kokoflix(url: str, headers: dict) -> str | None:
    """
    french-stream's kokoflix.lol proxy (``*_go.php?id=…``).

    The endpoint 302-redirects to the real mirror embed (playmogo/dood,
    luluvdo/voe, bysesayeveum/filemoon…). Follow the redirect and dispatch
    on the FINAL host so each mirror uses its own extractor. Loops back to
    kokoflix (or unknown hosts) → None.
    """
    h = dict(headers or {})
    h.setdefault("Referer", "https://french-stream.net/")
    try:
        resp = _get(url, headers=h, impersonate="chrome")
        resp.raise_for_status()
    except Exception:
        return None
    final = str(getattr(resp, "url", "") or "")
    if not final or "kokoflix" in final.lower():
        return None
    if final == url:
        return None
    return get_hls_link(final, h)


_UNPACK_TOKEN = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_UNPACK_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,d\).*?\}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)",
    re.S,
)


def unpack_dean_edwards(page: str) -> str:
    """Resolve Dean Edwards packer `eval(function(p,a,c,k,e,d){…})` blocks.

    fsvid/vidzy now ship their player inside the classic packer: every
    token (``sources``, ``src``, ``var``, ``t``, ``e``, the numbers of the
    signed query…) is replaced by a base-N index into the word list. Without
    unpacking, the plain ``sources:[{src:"…"}]`` line is INVISIBLE and the
    only m3u8 left in the page is the ``/troll/`` decoy — that is exactly the
    "vidzy sometimes fails" bug. This is a pure-JS transform, mirrored in
    Python: repeated until no more packed blocks remain.
    """
    out = page or ""
    for _ in range(5):
        m = _UNPACK_RE.search(out)
        if not m:
            break
        payload, base = m.group(1).replace("\\'", "'"), int(m.group(2))
        words = m.group(4).split("|")
        # Replace the HIGHEST indices first so "1" never eats a "10".
        # The packer's regex is \b<N>\b — a WORD BOUNDARY only — so ".1" or
        # "?s=1" inside a URL ARE substituted by the browser too. Use the same
        # rule: an alphanumeric look-behind would leave stale digits behind.
        for idx in range(len(words) - 1, -1, -1):
            if not words[idx]:
                continue
            num, tok = idx, ""
            if idx == 0:
                tok = "0"
            while num:
                tok = _UNPACK_TOKEN[num % base] + tok
                num //= base
            value = words[idx].replace("\\", "\\\\")
            # NEVER substitute inside a long digit run ("00032" ≠ "0…032"):
            # the packer's \b<N>\b does match a "1" glued to digits, but the
            # real payload never relies on it and it corrupts signed URLs.
            payload = re.sub(
                r"(?<![0-9A-Za-z_])" + re.escape(tok) + r"(?![0-9A-Za-z_])",
                lambda _m, v=value: v,
                payload,
            )
        out = out[: m.start()] + payload + out[m.end():]
    return out


_NON_STREAM_VIDEO_EXTS = (
    ".mp4", ".m4v", ".webm", ".mkv", ".avi", ".mov", ".flv", ".ts", ".m4s",
)


def _looks_like_stream(link: str) -> bool:
    """True for a playable media URL (HLS manifest or a video file).

    Byse API responses carry an ``intro.mp4`` hook as well as the real
    stream; picking the first ``.mp4`` in a page would play the ad.
    """
    low = (link or "").split("?")[0].lower()
    return low.endswith(".m3u8") or low.endswith(_NON_STREAM_VIDEO_EXTS)


def _js_context(page: str) -> str:
    """Only the JavaScript part of an embed page.

    Unpacked code is JavaScript, so the CSS/HTML around it must NOT take part
    in the source regexes: a stylesheet rule like ``src:url(…)`` or an
    ``img src="…m3u8"`` would otherwise win over the real player payload.
    """
    chunks = re.findall(r"<script[^>]*>(.*?)</script>", page or "", re.S)
    if not chunks:
        return page or ""
    return "\n".join(chunks)


def _fsvid_candidates(body: str, host: str = "fsvid.lol") -> list[str]:
    """Every REAL stream URL a fsvid/vidzy embed exposes (decoy excluded).

    Tried in order : unpacked page (current layout), obfuscated IIFE (older
    layout), raw page. Returns [] when the embed only serves the decoy.
    """
    js = _js_context(body)
    code = unpack_dean_edwards(js)
    urls: list[str] = []

    for text in (code, js):
        for m in re.finditer(
            r'(?:sources\s*:\s*\[?\{?\s*src|src)\s*[:=]\s*"([^"]+\.m3u8[^"]*)"',
            text or "",
        ):
            urls.append(m.group(1))
        hit = extract_hls_url(text or "")
        if hit:
            urls.append(hit)
    try:
        decoded = _fsvid_decode(code, host)
    except Exception:
        decoded = None
    if decoded:
        urls.append(decoded)

    clean: list[str] = []
    for u in urls:
        if not u or "/troll/" in u.lower() or u in clean:
            continue
        if u.startswith("//"):
            u = "https:" + u
        if not _looks_like_stream(u):
            continue  # intro/teaser .mp4, analytics URL, not the episode
        clean.append(u)
    return clean


def get_hls_link_fsvid(url: str, headers: dict) -> str | None:
    """
    fsvid.lol / vidzy.cc / vidzy.live (french-stream's "premium" hosts).

    Two embedding layouts coexist and BOTH are handled :

    CURRENT (2026-11) — the whole player is inside Dean Edwards' packer
    ``eval(function(p,a,c,k,e,d){…})``; resolving it (``unpack_dean_edwards``)
    exposes a plain ``sources:[{src:"…master.m3u8?…"}]`` with a REAL stream.
    The page also contains ``var _fsvHls="…/troll/master.m3u8"`` — a DECOY.

    OLDER — the real URL is built at runtime from a base64+XOR IIFE, which we
    reproduce (``_fsvid_decode``).

    Both return None when the host only serves the decoy (banned mirror), so
    the player is reported unavailable instead of returning a troll video.
    """
    h = dict(headers or {})
    # The embed 403s without a Referer ; the embed's own origin is accepted
    # (source-agnostic — works whether it's reached via french-stream or not).
    try:
        origin = "https://" + url.split("/")[2] + "/"
    except Exception:
        origin = "https://fsvid.lol/"
    h.setdefault("Referer", origin)
    resp = _get(url, headers=h, impersonate="chrome")
    resp.raise_for_status()

    body = resp.text or ""
    if embed_is_placeholder(body):
        return None  # removed / locked file, never a real stream
    try:
        host = url.split("/")[2]
    except Exception:
        host = "fsvid.lol"
    candidates = _fsvid_candidates(body, host)
    if not candidates:
        return None

    stream_url = candidates[0]
    return _remember_premium_headers(host, stream_url, h) or stream_url


def _remember_premium_headers(host: str, stream_url: str, h: dict):
    """Carry the cookies/headers the browser player sets before playing.

    fsvid sets ``fsv_pe=1`` and vidzy's gate returns a short-lived ``gk``
    appended to the CDN URL (with a ``vz_ok`` cookie). The CDN usually
    tolerates their absence, but mpv/yt-dlp are more likely to be rejected
    on some edges — so keep them attached to the resolved URL.
    """
    try:
        if "fsvid" in host.lower():
            set_stream_headers(stream_url, {
                "Cookie": "fsv_pe=1",
                "Referer": f"https://{host}/",
                "Origin": f"https://{host}",
            })
        if "vidzy" in host.lower():
            # The embed's current gate answers {"ok":0} and the CDN now
            # serves the master (and every segment) with just the embed
            # Referer/Origin. Only append gk when the gate really returns one.
            headers = {"Referer": f"https://{host}/", "Origin": f"https://{host}"}
            try:
                base_domain = ".".join(host.split(".")[-2:])
                gate = f"https://v6.{base_domain}/gate.php?" + urllib.parse.urlencode({
                    "v": "p1",
                    "cw": "100", "cw2": "100", "wg": "1", "dpr": "1",
                    "sw": "1920", "hw": "8", "ft": "TOP", "rf": host,
                })
                gh = dict(h)
                gh.setdefault("Origin", f"https://{host}")
                gr = _get(gate, headers=gh, impersonate="chrome", timeout=8)
                gk = (gr.json() or {}).get("gk") if gr.status_code == 200 else None
            except Exception:
                gk = None
            if gk and stream_url.startswith("http") and "hls2" in stream_url:
                sep = "&" if "?" in stream_url else "?"
                stream_url = stream_url + f"{sep}gk={urllib.parse.quote(gk)}"
                headers["Cookie"] = f"vz_ok={gk}"
            set_stream_headers(stream_url, headers)
    except Exception:
        return None
    return stream_url


# Placeholder an embed shows INSTEAD of the player when it will never play
# for anyone (file locked/removed, preview not ready…). Listing such a player
# with a quality badge would be a false positive.
_EMBED_DEAD_TEXT_MARKERS = (
    "file was locked by administrator",
    "file was deleted",
    "file expired",
    "file not found",
    "the file you are looking for",
    "video was removed",
    "video not found",
    "this video has been removed",
    "can't find the video",
    "we can't find the video",
)


def embed_is_placeholder(body: str) -> bool:
    """True when an embed page is a "file removed/locked" placeholder.

    uqload keeps listing locked files (``over_player_msg`` = "File was locked
    by administrator"), mixdrop answers "We can't find the video". Resolving
    them is wasted time and, worse, they used to appear as playable rows.
    """
    low = (body or "").lower()
    return any(marker in low for marker in _EMBED_DEAD_TEXT_MARKERS)


def _has_real_player_payload(body: str) -> bool:
    """True when the embed actually carries the obfuscated player payload.

    A healthy embed ships either the packed player (Dean Edwards' packer
    holding ``sources.src``) or the older base64 IIFE; the "banned" variant
    only has the decoy /troll/ URL.
    """
    body = body or ""
    if re.search(r"\}\)\(\\?\"[A-Za-z0-9+/=]{40,}\\?\"\)", body):
        return True
    packed = unpack_dean_edwards(body)
    return bool(re.search(r"sources\s*:\s*\[?\{?\s*src\s*:", packed))


def _fsvid_decode(code: str, hostname: str = "fsvid.lol"):
    """Pure decoder (no network) : reconstruct the real master.m3u8 URL from the
    fsvid/vidzy player JS. Testable.

    Two algorithms are supported (the host has rotated its obfuscation) :

    NEW (2026) — the video.js `sources.src` IIFE :
        H = (sum of location.hostname char codes) & 255
        BC = offsetWidth of a hidden 1in div (96 CSS px at 100% zoom)
        b = atob(payload) ; a = reverse(b)
        for each i: kk = (OFFSET + i*MULT + H [+ BC]) & 255 ; r += chr(a[i] ^ kk)
      OFFSET/MULT are read straight out of the JS so a constant tweak can't
      break us, and `hostname` MUST be the embed host (fsvid.lol / vidzy.cc…).
      BC defaults to 96 (standard zoom) with a brute-force fallback over the
      plausible zoom range — the decode is client-side, so a wrong BC just
      yields garbage that fails validation.

    OLD — a fixed 8-byte XOR key `var k=[…]` (kept as a fallback).
    """
    code = code or ""

    # ── NEW algorithm : (OFFSET + i*MULT + H [+ BC]) + reversed base64 ──
    km = re.search(
        r"\(\s*(0x[0-9a-fA-F]+|\d+)\s*\+\s*i\s*\*\s*(\d+)\s*\+\s*H\s*(?:\+\s*BC\s*)?\)",
        code,
    )
    if km:
        try:
            offset = int(km.group(1), 16) if km.group(1).lower().startswith("0x") else int(km.group(1))
            mult = int(km.group(2))
        except ValueError:
            offset = mult = None
        uses_bc = "BC" in km.group(0)
        # Payload = the base64 argument of the IIFE that contains this key.
        payload = None
        m2 = re.search(r'\}\)\(\s*"([A-Za-z0-9+/=]{40,})"\s*\)', code[km.start():])
        if not m2:  # some builds put the arg before the key text — search whole file
            m2 = re.search(r'\}\)\(\s*"([A-Za-z0-9+/=]{40,})"\s*\)', code)
        if payload is None and m2:
            payload = m2.group(1)
        reverse = ".reverse()" in code
        if offset is not None and payload:
            H = 0
            for ch in (hostname or ""):
                H = (H + ord(ch)) & 255

            def _try(bc: int):
                try:
                    raw = base64.b64decode(payload)
                except Exception:
                    return None
                if reverse:
                    raw = raw[::-1]
                out = "".join(
                    chr(raw[i] ^ ((offset + i * mult + H + bc) & 255))
                    for i in range(len(raw))
                )
                return out if out.startswith("http") and ".m3u8" in out else None

            if uses_bc:
                # 96 = 1 CSS inch at 100% zoom ; fall back to a scan over the
                # plausible zoom range (a wrong BC fails validation safely).
                for bc in [96] + [b for b in range(24, 201) if b != 96]:
                    hit = _try(bc)
                    if hit:
                        return hit
            else:
                hit = _try(0)
                if hit:
                    return hit
            # fall through to the legacy path

    # ── OLD algorithm : fixed 8-byte XOR key ──
    km = re.search(r"var\s+k\s*=\s*\[([0-9,\s]+)\]", code)
    if not km:
        return None
    key = [int(x) for x in km.group(1).split(",") if x.strip() != ""]
    if not key:
        return None
    payload = None
    for m in re.finditer(r'\}\)\(\s*"([A-Za-z0-9+/=]+)"\s*\)', code[km.start():]):
        payload = m.group(1)
        break
    if not payload:
        return None
    try:
        raw = base64.b64decode(payload)
        out = "".join(chr(raw[i] ^ key[i % len(key)]) for i in range(len(raw)))
    except Exception:
        return None
    return out if out.startswith("http") and ".m3u8" in out else None


# Anti-scraper DECOY streams : some hosts return a placeholder ("troll") video
# to non-browser clients instead of the real content. These substrings in a
# RESOLVED stream URL mark it as fake so we skip that player.
_DECOY_STREAM_MARKERS = ("/troll/", "/fake/", "/decoy/", "/notfound/", "/error/")


def _is_decoy_stream(link) -> bool:
    if not link:
        return False
    low = str(link).lower()
    return any(marker in low for marker in _DECOY_STREAM_MARKERS)


def get_hls_link(url: str, headers: dict = None) -> str | None:
    """
    Extract HLS/video link from a player URL.
    Automatically detects the player type and uses the appropriate parser.

    Args:
        url: Player URL
        headers: HTTP headers for the request (default: {})

    Returns:
        HLS/video stream URL if successful, None otherwise
    """
    headers = headers or {}
    # animes-sama.fr slots: the site mints the real URL on demand. When a
    # resolver is registered, use it now; otherwise there is nothing to fetch.
    if url == ANIME_SAMA_SIGNED_SENTINEL:
        if _signed_resolver is None:
            _set_apc(None)
            return None
        try:
            real = _signed_resolver(headers)
        except Exception:  # noqa: BLE001 - a dead sign API is not a crash
            real = None
        if not real:
            _set_apc(None)
            return None
        url = real
        headers = dict(headers or {})
        headers.pop("_anime_sama_slot", None)
        # The resolver already returned the final media URL (a /player/media
        # HLS). There is no embed to scrape: hand it straight to the player.
        if "/player/media" in url:
            _set_apc(None)
            return url
    # Matching sur le HOSTNAME aligné aux labels : matcher en substring sur
    # l'URL complète prenait des faux positifs (book.ru → ok.ru,
    # ?ref=sibnet, /veev/ tiers).
    host = _url_host(url)
    if not host:
        _set_apc(None)
        return None
    # Find matching player and parse accordingly
    for player_name, config in players.items():
        if _host_matches(host, player_name):
            _set_apc(config)
            parse_type = config["type"]

            link = None
            if parse_type == "default":
                link = get_hls_link_default(url, headers)
            elif parse_type == "sendvid":
                link = get_hls_link_sendvid(url)
            elif parse_type == "sibnet":
                link = get_hls_link_sibnet(url, headers)
            elif parse_type == "uqload":
                link = get_hls_link_uqload(url, headers)
            elif parse_type == "vidoza":
                link = get_hls_link_vidoza(url, headers)
            elif parse_type == "filemoon":
                link = get_hls_link_filemoon(url, headers)
            elif parse_type == "kakaflix":
                link = get_hls_link_kakaflix(url, headers)
            elif parse_type == "myvidplay":
                link = get_hls_link_myvidplay(url, headers)
            elif parse_type == "vidmoly":
                link = get_hls_link_vidmoly(url, headers)
            elif parse_type == "embed4me":
                link = get_hls_link_embed4me(url)
            elif parse_type == "veev":
                link = get_hls_link_veev(url)
            elif parse_type == "xtremestream":
                link = get_hls_link_xtremestream(url, headers)
            elif parse_type == "fsvid":
                link = get_hls_link_fsvid(url, headers)
            elif parse_type == "byse":
                link = get_hls_link_byse(url, headers)
            elif parse_type == "dood":
                link = get_hls_link_dood(
                    url, headers,
                    player_host=(config.get("referrer") or "").split("//")[-1].strip("/"),
                )
            elif parse_type == "voe":
                link = get_hls_link_voe(url, headers)
            elif parse_type == "kokoflix":
                link = get_hls_link_kokoflix(url, headers)

            # Some hosts (e.g. french-stream's fsvid.lol) serve an anti-scraper
            # DECOY stream — a "troll" placeholder video — to non-browser
            # clients. Reject it so the player is marked unavailable and the
            # user falls back to a host that actually returns the real content.
            return None if _is_decoy_stream(link) else link

    # Rotating Voe mirrors (Anime-Sama): not in `players` on purpose, since
    # their hostnames change daily. Recognised by shape + a live probe.
    if is_voe_url(url):
        link = get_hls_link_voe(url, headers)
        return None if _is_decoy_stream(link) else link

    _set_apc(None)
    return None


def is_supported(url: str) -> bool:
    """
    Check if a player URL is supported.

    Args:
        url: Player URL to check

    Returns:
        True if the player is supported, False otherwise
    """
    if url == ANIME_SAMA_SIGNED_SENTINEL:
        # animes-sama.fr slots carry no host: supported as long as the
        # handler registered a resolver that can mint the real URL.
        return _signed_resolver is not None
    host = _url_host(url)
    if not host:
        return False
    # Unknown host but the page speaks Voe → it is a rotating Anime-Sama
    # mirror, so the row must be offered instead of hidden as unsupported.
    if is_voe_url(url):
        return True
    if _host_matches(host, "kakaflix"):
        for sub in kakaflix_players.keys():
            if _host_matches(host, sub):
                return True
        return False

    for player in players.keys():
        if _host_matches(host, player):
            return True

    return False


# ── Rotating Voe mirrors (Anime-Sama) ────────────────────────────────
# Anime-Sama serves its Voe player under a stream of randomly named
# throwaway domains (…/e/<id>), each 302ing through one or two more before
# landing on the page that carries the stream. Hardcoding the list breaks
# within days: 8 new hosts appeared in a single day during the audit. So the
# URL *shape* is what we recognise, then the page is confirmed live once
# (cached) to be sure it really speaks Voe.
_VOE_UNKNOWN: dict[str, bool] = {}
_VOE_LOCK = _threading.Lock()

# Hosts already confirmed (keeps the common case network-free).
_VOE_KNOWN = (
    "luluvdo", "lulust", "voe", "lulustream",
    "claireguessthousand", "derricknationtop", "jeremyparticipantanything",
    "megankiddifference", "teresapoliticallearn", "shannoncoldalready",
    "susanexpectcare", "ashleyhardat", "shanelocaldog",
)


def _is_voe_known(host: str) -> bool:
    return any(_host_matches(host, k) for k in _VOE_KNOWN)


def voe_family_host(host: str) -> bool:
    """True when *host* is a Voe-family mirror (known, or probed once)."""
    if not host:
        return False
    if _is_voe_known(host):
        return True
    with _VOE_LOCK:
        if host in _VOE_UNKNOWN:
            return _VOE_UNKNOWN[host]
    ok = False
    try:
        r = _get(f"https://{host}/", impersonate="chrome", timeout=8)
        body = (getattr(r, "text", "") or "")[:6000].lower()
        ok = "voe" in body and r.status_code == 200
    except Exception:  # noqa: BLE001 - a probe failure must not crash the menu
        ok = False
    with _VOE_LOCK:
        _VOE_UNKNOWN[host] = ok
    return ok


def is_voe_url(url: str) -> bool:
    """True when *url* looks like a Voe player page (…/e/<id>)."""
    host = _url_host(url)
    if not host:
        return False
    if _is_voe_known(host):
        return True
    # Only spend a network probe on the /e/<id> shape Voe actually uses,
    # never on an arbitrary host the catalogue might list.
    return "/e/" in (url or "") and voe_family_host(host)
