from __future__ import annotations

from curl_cffi import requests
from .deobfuscate import deobfuscate
from bs4 import BeautifulSoup
from ..net_config import DNS_OPTIONS
from ..defaults import DEFAULT_PLAYERS, DEFAULT_NEW_URL, DEFAULT_KAKAFLIX_PLAYERS
import re
import base64
import urllib.parse

import json
import binascii

import threading as _threading

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


from .. import cloudflare  # noqa: E402 (deliberate late import — order matters)


def _get(url, **kw):
    """Cloudflare-aware GET (cf_clearance + FlareSolverr cascade), per thread."""
    kw.setdefault("timeout", 20)  # un host mort ne doit jamais geler l'UI
    return cloudflare.cf_get(_scraper(), url, **kw)


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
    # uqload now ships the player JS packed (dean-edwards). Unpack first.
    try:
        code = deobfuscate(text)
    except Exception:
        code = text
    haystack = (code or "") + "\n" + text

    # Modern layout : a signed fsvid-family HLS `…/.urlset/master.m3u8?t=…`
    # (served with the embed's Origin). Legacy : sources:[{file:"…mp4"}].
    for pat in (
        r'file:\s*"([^"]+\.(?:m3u8|mp4)[^"]*)"',
        r'sources:\s*\[\s*"([^"]+)"',
        r'(https?://[^\s"\']+\.m3u8[^\s"\']*)',
        r'(https?://[^\s"\']+\.mp4[^\s"\']*)',
    ):
        m = re.search(pat, haystack)
        if m:
            return m.group(1)

    return None  # graceful : caller shows 'try another player'


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
        return source.attrs["src"]

    og = soup.find("meta", {"property": "og:video"})
    if og and og.attrs.get("content"):
        return og.attrs["content"]
    return None


def get_hls_link_sibnet(url: str) -> str:
    """
    Extract video link from sibnet.

    Args:
        url: Player URL

    Returns:
        Video URL
    """
    response = _get(url, impersonate="chrome")
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

        print("Error: No valid decryption found.")
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
        print(f"Connection error: {e}")
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
    try:
        data_id = url.split("?data=")[1].split("&")[0].split("#")[0]
    except IndexError:
        return None
    if not data_id:
        return None
    url_root = _url_host(url)
    if not url_root:
        return None

    return f"https://{url_root}/player/xs1.php?data={data_id}"


def get_hls_link_dood(url: str, headers: dict) -> str | None:
    """
    DoodStream mirrors (playmogo.com, doodstream mirrors reached via
    french-stream's kokoflix proxy).

    The /e/ page embeds a same-origin token path which the player fetches
    via AJAX (``$.get('/pass_md5/<token>')``) ; that endpoint answers the
    DIRECT mp4 URL as plain text. Reproduce both calls with the browser's
    headers (Referer + X-Requested-With).
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
    m = re.search(r"/pass_md5/[^\"'\s]*", resp.text or "")
    if not m:
        return None
    h2 = dict(h)
    h2["X-Requested-With"] = "XMLHttpRequest"
    try:
        r2 = _get(f"https://{host}" + m.group(0), headers=h2,
                  impersonate="chrome")
        r2.raise_for_status()
    except Exception:
        return None
    link = (r2.text or "").strip()
    return link if link.startswith("http") else None


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


def get_hls_link_voe(url: str, headers: dict) -> str | None:
    """
    Voe mirrors (luluvdo.com, reached via french-stream's kokoflix proxy).

    The /e/ page ships the JWPlayer setup with the stream URL hidden behind
    a word-substitution packer (``eval(function(p,a,c,k,e,d){while(c--)…})``).
    Decode it and pull the m3u8/mp4 out of the ``sources`` block.
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


def get_hls_link_fsvid(url: str, headers: dict) -> str | None:
    """
    fsvid.lol / vidzy.org (french-stream's "premium" host).

    The embed page ships a DECOY ``…/troll/master.m3u8`` in plain sight, but the
    REAL stream is built at runtime by the video.js `sources` IIFE :
        src = (function(s){ var k=[…]; b=atob(s); r="";
                            for(i…) r+=chr(b[i]^k[i%8]); return r })("<base64>")
    i.e. base64-decode the payload, then XOR each byte with an 8-byte key. We
    reproduce that here to get the actual multi-quality/-language master.m3u8.
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

    try:
        code = deobfuscate(resp.text)
    except Exception:
        code = resp.text or ""

    # The current algorithm derives its key from the EMBED HOST (location.
    # hostname in the browser), so pass it through for an exact reproduction.
    try:
        host = url.split("/")[2]
    except Exception:
        host = "fsvid.lol"
    return _fsvid_decode(code, host)


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
                link = get_hls_link_sibnet(url)
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
            elif parse_type == "dood":
                link = get_hls_link_dood(url, headers)
            elif parse_type == "voe":
                link = get_hls_link_voe(url, headers)
            elif parse_type == "kokoflix":
                link = get_hls_link_kokoflix(url, headers)

            # Some hosts (e.g. french-stream's fsvid.lol) serve an anti-scraper
            # DECOY stream — a "troll" placeholder video — to non-browser
            # clients. Reject it so the player is marked unavailable and the
            # user falls back to a host that actually returns the real content.
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
    host = _url_host(url)
    if not host:
        return False
    if _host_matches(host, "kakaflix"):
        for sub in kakaflix_players.keys():
            if _host_matches(host, sub):
                return True
        return False

    for player in players.keys():
        if _host_matches(host, player):
            return True

    return False
