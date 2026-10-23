"""
Local HLS/MP4 proxy — now on the Python stdlib ``http.server`` (no Flask).

It resolves relative m3u8 segment URLs, injects the per-host headers the CDN
needs, streams segments with automatic resume on a flaky link + re-resolution
on an expired token (see ``resilient_body``), and serves a small web player.
Binds to 127.0.0.1 on a random port, started lazily on first playback.
"""

import threading
import socket
import json
import time
import ipaddress
import urllib.parse
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from curl_cffi import requests, CurlOpt
from .net_config import DNS_OPTIONS
from .i18n import t
import m3u8

# Global Configuration
PROXY_PORT = 0
PROXY_HOST = "127.0.0.1"
PROXY_URL = None
_server_instance = None  # the ThreadingHTTPServer, for shutdown

# Web Player State
player_finished_event = threading.Event()
player_heartbeat_time = 0


class StreamIncomplete(Exception):
    """Upstream ended before the announced body length.

    The response has already started, so the only safe signal is to ABORT the
    connection (close it without the final chunk / with fewer bytes than
    ``Content-Length``). Players and yt-dlp then retry the range/segment
    instead of accepting a truncated file as complete — a truncated segment is
    exactly what makes a video "jump" over missing parts.
    """

# ── Data-usage meter ──────────────────────────────────────────────────
_bytes_lock = threading.Lock()
_bytes_served = 0


def reset_bytes_counter():
    """Zero the data-usage meter (call right before a playback)."""
    global _bytes_served
    with _bytes_lock:
        _bytes_served = 0


def add_bytes(n: int):
    global _bytes_served
    with _bytes_lock:
        _bytes_served += n


def get_bytes_served() -> int:
    """Total bytes streamed to the player since the last reset."""
    with _bytes_lock:
        return _bytes_served


# ── SSRF guard ────────────────────────────────────────────────────────
# The proxy binds to 127.0.0.1 on a random port, but any local process could
# otherwise abuse it as an open proxy to reach internal/cloud-metadata services
# (e.g. /video?url=http://169.254.169.254/…). Legit streams are always public
# CDNs, so we refuse any target URL whose host is a loopback / private /
# link-local / reserved IP (or a localhost literal).
_BLOCK_HOST_LITERALS = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}


def _ip_is_blocked(ip) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _normalize_ip_literal(host: str):
    """Parse non-standard IPv4 forms (0x7f.0.0.1, 0177.0.0.1, 2130706433,
    127.1) that ipaddress rejects but stacks resolve to loopback/private."""
    import struct
    try:
        packed = socket.inet_aton(host)
    except (OSError, ValueError):
        return None
    try:
        return ipaddress.ip_address(struct.unpack("!I", packed)[0])
    except ValueError:
        return None


# Hostname → (expires_ts, blocked) : juge la RÉPONSE DNS, pas le nom
# (anti DNS-rebinding). TTL court pour garder la latence basse.
_DNS_VERDICT_CACHE_TTL = 60.0
_DNS_VERDICT_CACHE: dict = {}
_DNS_VERDICT_LOCK = threading.Lock()


def _hostname_resolves_blocked(host: str) -> bool:
    """True si le host résout vers une IP interdite. Échec de résolution →
    False (fail-open, comme avant : ne pas casser la lecture sur DNS flaky)."""
    now = time.time()
    with _DNS_VERDICT_LOCK:
        hit = _DNS_VERDICT_CACHE.get(host)
        if hit and hit[0] > now:
            return hit[1]
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC,
                                   type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return False
    blocked = False
    for _fam, _typ, _proto, _canon, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            blocked = True
            break
    with _DNS_VERDICT_LOCK:
        _DNS_VERDICT_CACHE[host] = (now + _DNS_VERDICT_CACHE_TTL, blocked)
        if len(_DNS_VERDICT_CACHE) > 1024:
            _DNS_VERDICT_CACHE.clear()
    return blocked


def _is_ssrf_blocked(target_url: str) -> bool:
    try:
        parts = urllib.parse.urlparse(target_url)
    except Exception:
        return False
    # Seuls http/https sortent vers un CDN ; file://, gopher://, dict://…
    # n'ont rien à faire dans ce proxy (hostname vide = refusé aussi).
    if (parts.scheme or "").lower() not in ("http", "https"):
        return True
    host = parts.hostname or ""
    if not host:
        return True
    h = host.lower().rstrip(".")
    if h in _BLOCK_HOST_LITERALS:
        return True
    # Fast path : littéral IP (formes standard + hex/octal/décimales).
    ip = None
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        ip = _normalize_ip_literal(h)
    if ip is not None:
        return _ip_is_blocked(ip)
    # Hostname : on juge la réponse DNS, pas le nom.
    return _hostname_resolves_blocked(h)


# ── Subtitle endpoint jail ────────────────────────────────────────────
# /player/subtitle?path= ne sert que les sous-titres que FreeFlix a lui-même
# téléchargés (tempdir) ou placés dans le dossier de téléchargement. Tout le
# reste (dont /etc/passwd, clés SSH, /dev/zero) est refusé en 403.
_SUBTITLE_MAX_BYTES = 2 * 1024 * 1024


def _subtitle_allowed_dirs() -> list:
    import os
    import tempfile
    dirs = [tempfile.gettempdir()]
    try:
        from .player_manager import DOWNLOAD_DIR  # import tardif : pas de cycle
        dirs.append(DOWNLOAD_DIR)
    except Exception:
        dirs.append(os.path.expanduser("~/Downloads/FreeFlix"))
    return dirs


def find_free_port():
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def get_base_url(url):
    """Extracts the base URL to resolve relative paths."""
    return url.rsplit("/", 1)[0] + "/"


# ─── Thread-local session reuse (BIG throughput win) ──────────────
# Each worker thread keeps ONE persistent curl_cffi session : curl reuses the
# connection (HTTP keep-alive) and caches the DoH result, so DNS + TLS is paid
# once per thread then amortized over every segment.
_thread_local = threading.local()


def _build_session():
    session = requests.Session(impersonate="chrome")
    session.curl_options.update(DNS_OPTIONS)
    # Use DoH for the video proxy (bypasses ISP DNS blocks on CDNs).
    session.curl_options[CurlOpt.DOH_URL] = "https://1.1.1.1/dns-query"
    # Abort a transfer that's essentially dead (< 100 B/s) after 3 s, so the
    # resilient body can RECONNECT + RESUME quickly rather than hanging. The
    # reconnect logic (not a longer cutoff) is what makes it robust: after a
    # Wi-Fi/operator switch the next attempt uses a fresh DNS/TLS route.
    session.curl_options.update({
        CurlOpt.LOW_SPEED_LIMIT: 100,
        CurlOpt.LOW_SPEED_TIME: 3,
    })
    return session


def get_session():
    """Return this thread's persistent session, creating it on first use."""
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = _build_session()
        _thread_local.session = sess
    return sess


def _reset_session():
    """Drop the thread's session so the next call builds a fresh one."""
    sess = getattr(_thread_local, "session", None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
    _thread_local.session = None


def _upstream_total(resp, start_offset: int):
    """Total bytes we still expect to receive from *resp* (from Content-Range
    or Content-Length), or None if unknown."""
    try:
        cr = resp.headers.get("Content-Range") or resp.headers.get("content-range")
        if cr and "/" in cr:
            grand = cr.rsplit("/", 1)[-1].strip()
            if grand.isdigit():
                return max(0, int(grand) - start_offset)
        cl = resp.headers.get("Content-Length") or resp.headers.get("content-length")
        if cl and str(cl).isdigit():
            return int(cl)   # 206 → remaining; 200 → full body
    except Exception:
        pass
    return None


def _range_is_closed(value: str) -> bool:
    """``bytes=0-1023`` (closed) vs ``bytes=0-`` (open-ended)."""
    return bool(re.match(r"bytes=\d+-\d+\s*$", value or ""))


def _declared_length(resp):
    try:
        cl = resp.headers.get("Content-Length") or resp.headers.get("content-length")
        if cl and str(cl).isdigit() and int(cl) >= 0:
            return int(cl)
    except Exception:
        pass
    return None


# ── Stream re-resolution (handles EXPIRED / tokenised URLs) ───────────
# Playback registers a refresher : a callable that RE-RESOLVES the stream and
# returns a fresh (unexpired) master URL. On 401/403/410 the proxy fetches a
# fresh master and re-signs the failing URL with the new token.
_stream_refresher = None
_refresh_lock = threading.Lock()
_refresh_cache = {
    "master": None, "ts": 0.0,
    "segments": None, "segments_ts": 0.0,
}
_SIGN_PARAMS = ("t", "s", "e", "sp", "i", "f", "fr", "token", "expires",
                "expire", "hash", "hmac", "sig", "signature", "key", "st")


def set_stream_refresher(fn):
    """Register a callable() -> fresh master URL (or None). Called by play_video
    at the start of a proxied playback."""
    global _stream_refresher
    with _refresh_lock:
        _stream_refresher = fn
        _refresh_cache.update({
            "master": None, "ts": 0.0, "segments": None, "segments_ts": 0.0,
        })


def clear_stream_refresher():
    global _stream_refresher
    with _refresh_lock:
        _stream_refresher = None
        _refresh_cache.update({
            "master": None, "ts": 0.0, "segments": None, "segments_ts": 0.0,
        })


def _fresh_master(max_age: float = 8.0):
    """Re-resolve the stream (cached briefly so a burst of expired segments
    triggers ONE re-resolution, not dozens)."""
    with _refresh_lock:
        fn = _stream_refresher
        if fn is None:
            return None
        if _refresh_cache["master"] and (time.time() - _refresh_cache["ts"]) < max_age:
            return _refresh_cache["master"]
    try:
        master = fn()
    except Exception:
        master = None
    with _refresh_lock:
        if master and master != _refresh_cache["master"]:
            # New manifest → its segment URLs (and possibly host) changed.
            _refresh_cache["segments"] = None
            _refresh_cache["segments_ts"] = 0.0
        if master:
            _refresh_cache["master"] = master
            _refresh_cache["ts"] = time.time()
    return master


def _basename_path(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).path.rsplit("/", 1)[-1] or ""
    except Exception:
        return ""


def _fresh_segment_map(master: str, headers: dict, max_age: float = 12.0):
    """Map ``basename → fresh absolute URL`` from the freshly resolved stream.

    Query-token swapping fixes most expirations, but when the CDN rotates to a
    different HOST (or signs URLs in the path) after a reconnect / network
    switch, the only reliable URL is the one in the new manifest. Cached for a
    few seconds so a burst of expired segments costs one playlist fetch.
    """
    with _refresh_lock:
        cached = _refresh_cache.get("segments")
        if cached is not None and (time.time() - _refresh_cache["segments_ts"]) < max_age:
            return cached
    out = {}
    try:
        import m3u8 as _m3u8

        def _add(obj, base):
            for key in getattr(obj, "keys", []) or []:
                if key and key.uri:
                    try:
                        out[_basename_path(key.uri)] = key.absolute_uri
                    except Exception:
                        pass
            for sm in getattr(obj, "segment_map", []) or []:
                if sm and sm.uri:
                    try:
                        out[_basename_path(sm.uri)] = sm.absolute_uri
                    except Exception:
                        pass
            for seg in getattr(obj, "segments", []) or []:
                if seg and seg.uri:
                    try:
                        out[_basename_path(seg.uri)] = seg.absolute_uri
                    except Exception:
                        pass

        resp = fetch_with_retry(master, headers or {}, max_retries=2)
        if not resp or getattr(resp, "status_code", 0) not in (200, 206):
            return out
        try:
            text = resp.text or ""
        finally:
            try:
                resp.close()
            except Exception:
                pass
        if "#EXTM3U" not in text[:4096]:
            return out
        obj = _m3u8.loads(text, uri=master)
        if obj.playlists:
            # Segment names are normally shared by all variants; inspect the
            # first few until we find the playlist level.
            for p in obj.playlists[:4]:
                try:
                    media = p.absolute_uri
                except Exception:
                    media = p.uri
                r2 = fetch_with_retry(media, headers or {}, max_retries=2)
                if not r2 or getattr(r2, "status_code", 0) not in (200, 206):
                    continue
                try:
                    t2 = r2.text or ""
                finally:
                    try:
                        r2.close()
                    except Exception:
                        pass
                if "#EXTINF" in t2 or "#EXT-X-MAP" in t2:
                    _add(_m3u8.loads(t2, uri=media), media)
                    if out:
                        break
        else:
            _add(obj, master)
    except Exception:
        out = {}
    with _refresh_lock:
        _refresh_cache["segments"] = out
        _refresh_cache["segments_ts"] = time.time()
    return out


def _refreshed_url(expired_url: str, headers: dict = None):
    """A fresh, unexpired version of *expired_url* (the master itself, a
    segment from the new manifest, or a segment re-signed with the fresh
    token), or None.

    The new-manifest lookup comes first: after an operator/Wi-Fi switch the CDN
    may hand out a different host, which a query-only signature swap cannot
    repair.
    """
    master = _fresh_master()
    if not master:
        return None
    low = expired_url.lower()
    if ".m3u8" in low or "master" in low:
        return master
    # Query-signature swap first (cheap, no extra request). The fresh-manifest
    # lookup is only needed when the HOST or the path changed — e.g. after an
    # operator switch the CDN hands out a new hostname that cannot be repaired
    # by copying query params.
    swapped = None
    changed = False
    try:
        mq = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(master).query))
        parts = urllib.parse.urlparse(expired_url)
        sq = dict(urllib.parse.parse_qsl(parts.query))
        for p in _SIGN_PARAMS:
            if p in mq:
                sq[p] = mq[p]
                changed = True
        if not changed and mq:
            sq = mq
        swapped = urllib.parse.urlunparse(
            parts._replace(query=urllib.parse.urlencode(sq)))
    except Exception:
        swapped = None

    try:
        m_host = (urllib.parse.urlparse(master).hostname or "").lower()
        e_host = (urllib.parse.urlparse(expired_url).hostname or "").lower()
    except Exception:
        m_host = e_host = ""
    if (m_host and e_host and m_host != e_host) or not changed:
        name = _basename_path(expired_url)
        if name:
            fresh = _fresh_segment_map(master, headers or {}).get(name)
            if fresh:
                return fresh
    return swapped


def _open_stream_response(url, headers, stream=True, client_range=None,
                          max_retries=4):
    """Fetch a playlist/segment/video, transparently re-resolving an expired
    token (401/403/410) before any bytes are sent to the player.

    Returns ``(resp, effective_url)``. ``resp`` is None on a hard failure.
    """
    current = url
    for _ in range(3):
        resp = fetch_with_retry(
            current, headers, stream=stream, max_retries=max_retries,
            client_range=client_range,
        )
        if not resp:
            return None, current
        if getattr(resp, "status_code", 0) in (401, 403, 410):
            fresh = _refreshed_url(current, headers)
            _close_quietly(resp)
            if not fresh or fresh == current:
                return None, current
            current = fresh
            continue
        return resp, current
    return None, current


def _retry_after_seconds(resp, default: float) -> float:
    """Honour ``Retry-After`` (seconds form) on 429/503, capped for playback."""
    try:
        raw = (resp.headers.get("Retry-After")
               or resp.headers.get("retry-after") or "")
        sec = float(str(raw).strip())
        return max(0.5, min(15.0, sec))
    except Exception:
        return default


def _close_quietly(resp) -> None:
    try:
        resp.close()
    except Exception:
        pass


def resilient_body(url, base_headers, start_offset=0, first_resp=None,
                   first_total=None, no_progress_budget=300.0,
                   client_gone=None):
    """
    A response body that survives a flaky connection, a network switch and
    expired URLs:
      • on a stall/drop it RECONNECTS with an HTTP ``Range`` from the exact
        byte where it stopped (new session → new DNS/TLS/route, so switching
        Wi-Fi or operator just works);
      • on 401/403/410 it RE-RESOLVES the stream, preferring the matching
        segment from the *new* manifest (new host/token), then falls back to
        swapping signature query params;
      • it gives up only on a hard 404/416 or when *no_progress_budget*
        seconds pass with ZERO bytes. ``None`` means "keep trying as long as
        the player is connected" — used by the streaming endpoints so an
        outage (even a long one) resumes instead of ending the video.

    If the server ignores Range after a partial send, raises
    :class:`StreamIncomplete` instead of returning a short body: the caller
    then aborts the HTTP response, which makes the player retry rather than
    accept a gap.
    """
    sent = 0
    total = first_total
    resp = first_resp
    refresh_tries = 0
    last_progress = time.time()
    attempts = 0

    def _budget_exceeded() -> bool:
        return (no_progress_budget is not None
                and time.time() - last_progress > no_progress_budget)

    def _pause(seconds: float) -> bool:
        """Sleep, but wake up quickly if the player is gone. False = stop."""
        deadline = time.time() + max(0.0, seconds)
        while time.time() < deadline:
            if client_gone is not None:
                try:
                    if client_gone():
                        return False
                except Exception:
                    return False
            time.sleep(min(0.25, max(0.0, deadline - time.time())))
        return True

    def _backoff() -> float:
        return min(8.0, 0.5 * (2 ** min(attempts, 4)))

    while True:
        if client_gone is not None:
            try:
                if client_gone():
                    return
            except Exception:
                return

        if resp is None:
            if _budget_exceeded():
                raise StreamIncomplete(
                    f"no data for {no_progress_budget:.0f}s") from None
            h = dict(base_headers or {})
            h["Range"] = f"bytes={start_offset + sent}-"
            try:
                resp = get_session().request(
                    "GET", url, headers=h, stream=True, timeout=60)
            except Exception:
                _reset_session()
                resp = None
                attempts += 1
                if not _budget_exceeded() and not _pause(_backoff()):
                    return
                continue

        st = getattr(resp, "status_code", 0)
        if st in (401, 403, 410):
            fresh = _refreshed_url(url, base_headers)
            if fresh and fresh != url and refresh_tries < 6:
                refresh_tries += 1
                url = fresh
                _close_quietly(resp)
                resp = None
                attempts = 0
                if not _pause(0.5):
                    return
                continue
            raise StreamIncomplete(f"upstream HTTP {st}")
        if st == 416:
            # Requested range already satisfied (or resource shrank). If we
            # really sent everything expected, this is a clean end.
            if total is not None and sent >= total:
                _close_quietly(resp)
                return
            _close_quietly(resp)
            raise StreamIncomplete("HTTP 416")
        if st == 404:
            _close_quietly(resp)
            raise StreamIncomplete("HTTP 404")
        if st not in (200, 206):
            retryable = st in (408, 425, 429) or st >= 500
            delay = _retry_after_seconds(resp, _backoff()) if retryable else 0
            _close_quietly(resp)
            resp = None
            if not retryable:
                raise StreamIncomplete(f"upstream HTTP {st}")
            attempts += 1
            if _budget_exceeded() or not _pause(delay):
                if _budget_exceeded():
                    raise StreamIncomplete(
                        f"no data for {no_progress_budget:.0f}s")
                return
            continue
        if st == 200 and sent > 0:
            # The server ignored our Range: we cannot append without
            # duplicating bytes. Abort so the client restarts cleanly.
            _close_quietly(resp)
            raise StreamIncomplete("server ignored Range")
        if st == 206:
            try:
                cr = (resp.headers.get("Content-Range")
                      or resp.headers.get("content-range") or "")
                m = re.match(r"bytes\s+(\d+)-", cr)
                if m and int(m.group(1)) != start_offset + sent:
                    _close_quietly(resp)
                    raise StreamIncomplete("wrong Content-Range")
            except StreamIncomplete:
                raise
            except Exception:
                pass
        if total is None:
            total = _upstream_total(resp, start_offset)

        try:
            for chunk in resp.iter_content():
                if not chunk:
                    continue
                sent += len(chunk)
                add_bytes(len(chunk))
                last_progress = time.time()
                yield chunk
            # Body ended naturally: either complete, or short → reconnect.
            if total is None or sent >= total:
                _close_quietly(resp)
                return
            _close_quietly(resp)
            resp = None
            attempts += 1
            if _budget_exceeded() or not _pause(_backoff()):
                if _budget_exceeded():
                    raise StreamIncomplete(
                        f"no data for {no_progress_budget:.0f}s")
                return
        except GeneratorExit:
            _close_quietly(resp)
            return
        except Exception:
            _reset_session()
            _close_quietly(resp)
            resp = None
            if _budget_exceeded():
                raise StreamIncomplete(
                    f"no data for {no_progress_budget:.0f}s") from None
            attempts += 1
            if not _pause(_backoff()):
                return


def fetch_with_retry(url, headers, method="GET", stream=False, max_retries=4,
                     client_range=None, _max_hops=3):
    """Request with retries, reusing the thread-local session. *client_range*
    (the player's Range header) is forwarded when present (MP4 seeking).

    Redirects are followed MANUALLY (≤3 sauts) : chaque hop est re-soumis au
    garde SSRF, sinon une cible publique qui 302 vers l'interne contournerait
    le contrôle initial (fonctionne partout : Windows, Linux, macOS).

    429/5xx are retried with exponential backoff and ``Retry-After`` support;
    a fresh session is built each retry (new DNS/TLS/route) so switching
    network/operator recovers instead of staying stuck on a dead connection.
    """
    attempt = 0
    while attempt < max_retries:
        retry_delay = None
        try:
            session = get_session()
            req_headers = headers.copy() if headers else {}
            if client_range:
                req_headers["Range"] = client_range
            effective_timeout = 180 if stream else 15
            current = url
            response = None
            for _ in range(_max_hops + 1):
                response = session.request(
                    method=method, url=current, headers=req_headers,
                    stream=stream, timeout=effective_timeout,
                    allow_redirects=False,
                )
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                loc = ""
                try:
                    loc = (response.headers.get("location")
                           or response.headers.get("Location") or "")
                except Exception:
                    loc = ""
                try:
                    response.close()
                except Exception:
                    pass
                if not loc:
                    break
                current = urllib.parse.urljoin(current, loc)
                if _is_ssrf_blocked(current):
                    from . import logsetup as _ls
                    _ls.warning(f"proxy: blocked redirect to {current}")
                    return None
            if response is None:
                raise requests.RequestsError("no response")
            if (response.status_code in (408, 425, 429)
                    or response.status_code >= 500):
                delay = _retry_after_seconds(response, 0.5 * (attempt + 1))
                retry_delay = delay
                try:
                    response.close()
                except Exception:
                    pass
                raise requests.RequestsError(
                    f"Status {response.status_code} (retry in {delay:.1f}s)")
            return response
        except Exception as e:
            attempt += 1
            _reset_session()
            if attempt >= max_retries:
                from . import logsetup as _ls
                _ls.warning(f"proxy: failed to fetch {url} after {max_retries} attempts: {e}")
                return None
            time.sleep(retry_delay if retry_delay is not None
                       else min(8.0, 0.5 * (2 ** min(attempt, 4))))


# ── m3u8 manifest rewriting ───────────────────────────────────────────
_NOT_A_PLAYLIST = object()


def _rewrite_manifest(target_url, headers):
    """Fetch a master/media playlist and rewrite its segment / key / variant
    URLs to go back through this proxy (so they're fetched with the right
    headers). Returns the rewritten text, ``_NOT_A_PLAYLIST`` when the target
    is actually a direct media file (so the caller can switch to /video without
    buffering the whole video), or None on a hard fetch error."""
    resp, effective_url = _open_stream_response(target_url, headers, stream=True)
    if not resp or resp.status_code not in (200, 206):
        return None
    target_url = effective_url
    try:
        ctype = (resp.headers.get("content-type") or "").lower()
        playlist_type = "mpegurl" in ctype or "m3u" in ctype
        chunks = []
        total = 0
        for chunk in resp.iter_content():
            if not chunk:
                continue
            if not chunks and not playlist_type and b"#EXTM3U" not in chunk[:4096]:
                # Direct MP4/MKV/... mislabelled as a playlist: do NOT read
                # the body here (it can be gigabytes). The caller re-opens it
                # through the binary passthrough.
                return _NOT_A_PLAYLIST
            chunks.append(chunk)
            total += len(chunk)
            if total > 16 * 1024 * 1024:
                break
        content = b"".join(chunks).decode("utf-8", "ignore")
    except Exception:
        return None
    finally:
        try:
            resp.close()
        except Exception:
            pass
    if "#EXTM3U" not in content[:4096]:
        return _NOT_A_PLAYLIST
    base_uri = get_base_url(target_url)

    try:
        m3u8_obj = m3u8.loads(content, uri=target_url)
    except Exception:
        return content  # unparseable → pass through as-is

    def make_proxy_url(endpoint, original_uri):
        absolute_url = urllib.parse.urljoin(base_uri, original_uri)
        encoded_url = urllib.parse.quote(absolute_url)
        encoded_headers = urllib.parse.quote(json.dumps(headers))
        return f"http://{PROXY_HOST}:{PROXY_PORT}/{endpoint}?url={encoded_url}&headers={encoded_headers}"

    if m3u8_obj.playlists:
        for p in m3u8_obj.playlists:
            p.uri = make_proxy_url("stream", p.uri)
        for mm in m3u8_obj.media:
            if mm.uri:
                mm.uri = make_proxy_url("stream", mm.uri)
    else:
        for key in m3u8_obj.keys:
            if key and key.uri:
                key.uri = make_proxy_url("ts", key.uri)
        if hasattr(m3u8_obj, "segment_map"):
            for seg_map in m3u8_obj.segment_map:
                if seg_map and seg_map.uri:
                    seg_map.uri = make_proxy_url("ts", seg_map.uri)
        for segment in m3u8_obj.segments:
            segment.uri = make_proxy_url("ts", segment.uri)

    new_content = m3u8_obj.dumps()

    def replace_map_uri(match):
        original_uri = match.group(1)
        if str(PROXY_PORT) in original_uri and "/ts?url=" in original_uri:
            return match.group(0)
        return f'#EXT-X-MAP:URI="{make_proxy_url("ts", original_uri)}"'

    return re.sub(r'#EXT-X-MAP:URI="([^"]+)"', replace_map_uri, new_content)


def _srt_to_vtt(content: bytes, is_srt: bool) -> str:
    if is_srt:
        text = content.decode("utf-8", errors="ignore")
        return "WEBVTT\n\n" + re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
    return content.decode("utf-8", errors="ignore")


# ── The web player HTML (unchanged from the Flask version) ────────────
_PLAYER_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>FreeFlix Web Player</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #000; overflow: hidden; font-family: sans-serif; }
        .plyr { width: 100%; height: 100%; }
        #controls-overlay { position: absolute; top: 20px; right: 20px; z-index: 1000; opacity: 0; transition: opacity 0.3s; }
        body:hover #controls-overlay, .plyr--active #controls-overlay { opacity: 1; }
        .action-btn { background-color: rgba(255, 0, 0, 0.7); color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .action-btn:hover { background-color: rgba(255, 0, 0, 1); }
        .message { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: white; font-size: 24px; display: none; text-align: center; z-index: 2000; }
        .message button { margin-top: 20px; padding: 10px 20px; font-size: 18px; cursor: pointer; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
</head>
<body>
    <div id="controls-overlay">
        <button id="closeBtn" class="action-btn">Mark as watched & Close</button>
    </div>
    <video id="video" controls crossorigin="anonymous" playsinline></video>
    <div id="finishedMsg" class="message">
        Video finished! You can safely close this tab.<br>
        <button onclick="window.close()">Close Tab</button>
    </div>
    <script>
        document.addEventListener("DOMContentLoaded", () => {
            const video = document.getElementById('video');
            const urlParams = new URLSearchParams(window.location.search);
            const source = urlParams.get('url');
            const subPath = urlParams.get('sub_path');
            const isMp4 = source && source.indexOf('/video') !== -1;
            const closeBtn = document.getElementById('closeBtn');
            if (subPath) {
                const track = document.createElement('track');
                track.kind = 'captions'; track.label = 'Subtitles';
                track.src = '/player/subtitle?path=' + encodeURIComponent(subPath);
                track.default = true; video.appendChild(track);
            }
            const defaultOptions = {
                captions: { active: true, update: true, language: 'auto' },
                controls: ['play-large','play','progress','current-time','mute','volume','captions','settings','pip','airplay','fullscreen'],
                settings: ['captions', 'quality', 'speed']
            };
            let player;
            if (source) {
                if (isMp4 || !Hls.isSupported()) {
                    video.src = source; player = new Plyr(video, defaultOptions); player.play();
                } else {
                    const hls = new Hls({ xhrSetup: function(xhr, url) { xhr.withCredentials = false; } });
                    hls.loadSource(source); hls.attachMedia(video);
                    hls.on(Hls.Events.MANIFEST_PARSED, function (event, data) {
                        const availableQualities = hls.levels.map((l) => l.height);
                        availableQualities.unshift(0);
                        defaultOptions.quality = { default: 0, options: availableQualities, forced: true, onChange: (e) => updateQuality(e) };
                        defaultOptions.i18n = { qualityLabel: { 0: 'Auto' } };
                        player = new Plyr(video, defaultOptions); player.play();
                    });
                    hls.on(Hls.Events.ERROR, function(event, data) {
                        if (data.fatal) {
                            switch (data.type) {
                                case Hls.ErrorTypes.NETWORK_ERROR: hls.startLoad(); break;
                                case Hls.ErrorTypes.MEDIA_ERROR: hls.recoverMediaError(); break;
                                default: hls.destroy(); break;
                            }
                        }
                    });
                    function updateQuality(newQuality) {
                        if (newQuality === 0) { window.hls.currentLevel = -1; }
                        else { const i = hls.levels.findIndex((l) => l.height === newQuality); if (i !== -1) hls.currentLevel = i; }
                    }
                    window.hls = hls;
                }
            }
            let heartbeatInterval = setInterval(() => { fetch('/player/heartbeat').catch(e => {}); }, 2000);
            function endPlayback() {
                clearInterval(heartbeatInterval);
                fetch('/player/end').then(() => {
                    document.getElementById('finishedMsg').style.display = 'block';
                    document.getElementById('controls-overlay').style.display = 'none';
                    if (player) { player.destroy(); } else { video.style.display = 'none'; }
                    setTimeout(() => window.close(), 1000);
                }).catch(e => {
                    document.getElementById('finishedMsg').style.display = 'block';
                    if (player) { player.destroy(); } else { video.style.display = 'none'; }
                });
            }
            video.addEventListener('ended', endPlayback);
            closeBtn.addEventListener('click', endPlayback);
        });
    </script>
</body>
</html>"""


# ── The stdlib request handler ────────────────────────────────────────
_FETCH_PATHS = {"/stream", "/ts", "/video"}


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # silence the default stderr access log

    # ── low-level response helpers ──
    def _send_headers(self, status, headers):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()

    def _send_bytes(self, status, body, content_type="text/plain; charset=utf-8",
                    extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        headers = {"Content-Type": content_type, "Content-Length": str(len(data))}
        if extra:
            headers.update(extra)
        try:
            self._send_headers(status, headers)
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _client_gone(self) -> bool:
        """True when the player closed its socket (best effort, non-blocking).

        Used by the long-resilience streaming body so a network outage can be
        retried indefinitely without leaking a worker forever after the user
        quits playback.
        """
        try:
            import select
            ready, _, _ = select.select([self.connection], [], [], 0)
            if not ready:
                return False
            data = self.connection.recv(1, socket.MSG_PEEK)
            return data == b""
        except Exception:
            return True

    def _stream(self, status, headers, generator, total=None):
        """Stream a generator to the client.

        When the upstream length is known we announce ``Content-Length`` and
        send raw bytes: a short body is then an unambiguous HTTP protocol
        error for mpv/yt-dlp. Without a length we use chunked encoding, and an
        incomplete generator simply does NOT emit the terminating ``0`` chunk
        — again a protocol error, never a silently truncated segment. This is
        what prevents "the video skips bad parts": a gap can no longer look
        like a valid, complete response.
        """
        h = dict(headers)
        known_total = total is not None and int(total) >= 0
        if known_total:
            total = int(total)
            h["Content-Length"] = str(total)
            h.pop("Transfer-Encoding", None)
        else:
            h["Transfer-Encoding"] = "chunked"
        sent = 0
        try:
            self._send_headers(status, h)
            for chunk in generator:
                if not chunk:
                    continue
                if known_total:
                    remaining = total - sent
                    if remaining <= 0:
                        break
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                    self.wfile.write(chunk)
                else:
                    self.wfile.write(b"%X\r\n" % len(chunk) + chunk + b"\r\n")
                sent += len(chunk)
            if known_total and sent < total:
                raise StreamIncomplete(
                    f"client got {sent}/{total} bytes")
            if not known_total:
                self.wfile.write(b"0\r\n\r\n")
            try:
                self.wfile.flush()
            except Exception:
                pass
        except StreamIncomplete:
            # The response already started: close the connection WITHOUT a
            # valid terminator. Do NOT pretend this was a complete body.
            self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # client (mpv) closed — stop quietly
        except Exception:
            self.close_connection = True
        finally:
            try:
                generator.close()
            except Exception:
                pass

    def _args(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        return parsed.path, {k: v[0] for k, v in q.items()}

    # ── routing ──
    def do_GET(self):
        global player_heartbeat_time
        path, args = self._args()

        # SSRF guard for the endpoints that fetch an external URL.
        if path in _FETCH_PATHS:
            target = args.get("url")
            if target and _is_ssrf_blocked(target):
                self._send_bytes(403, "Blocked target host")
                return

        try:
            if path == "/stream":
                self._h_stream(args)
            elif path == "/ts":
                self._h_ts(args)
            elif path == "/video":
                self._h_video(args)
            elif path == "/player":
                self._send_bytes(200, _PLAYER_HTML, "text/html; charset=utf-8")
            elif path == "/player/subtitle":
                self._h_subtitle(args)
            elif path == "/player/heartbeat":
                player_heartbeat_time = time.time()
                self._send_bytes(200, "ok")
            elif path == "/player/end":
                player_finished_event.set()
                self._send_bytes(200, "ok")
            else:
                self._send_bytes(404, f"Not Found: {path}")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            from . import logsetup as _ls
            _ls.warning(f"proxy handler error on {path}: {type(e).__name__}: {e}")
            try:
                self._send_bytes(500, "proxy error")
            except Exception:
                pass

    # ── handlers ──
    def _parse_headers_arg(self, args):
        try:
            return json.loads(args.get("headers", "{}"))
        except Exception:
            return {}

    def _h_stream(self, args):
        target_url = args.get("url")
        if not target_url:
            self._send_bytes(400, "Missing URL parameter")
            return
        # Fast path: a direct media URL must never be read as a playlist (that
        # would buffer the whole video just to return garbage). Serve it through
        # the binary passthrough.
        try:
            _path = urllib.parse.urlparse(target_url).path.lower()
        except Exception:
            _path = str(target_url).lower().split("?")[0]
        if _path.endswith((".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v")):
            self._h_video(args)
            return
        headers = self._parse_headers_arg(args)
        new_content = _rewrite_manifest(target_url, headers)
        if new_content is None:
            self._send_bytes(502, "Error fetching upstream m3u8")
            return
        # Safety net: if a DIRECT media file is opened through /stream (a
        # mislabelled source or a player config that no longer matches), serve
        # it through the binary passthrough instead of an empty playlist that
        # the player reports as "Failed to open".
        if new_content is _NOT_A_PLAYLIST or "#EXTM3U" not in new_content[:4096]:
            self._h_video(args)
            return
        self._send_bytes(200, new_content, "application/vnd.apple.mpegurl",
                         {"Access-Control-Allow-Origin": "*"})

    def _h_ts(self, args):
        target_url = args.get("url")
        if not target_url:
            self._send_bytes(400, "Missing URL")
            return
        headers = self._parse_headers_arg(args)
        # Segment-level resilience: keep retrying for as long as the player is
        # connected (network switch, operator change, long outage). The
        # callable stops the loop immediately if the player closed its socket.
        client_range = self.headers.get("Range")
        resp, target_url = _open_stream_response(
            target_url, headers, stream=True, client_range=client_range,
            max_retries=4,
        )
        if not resp:
            self._send_bytes(502, "Error fetching segment")
            return
        status = getattr(resp, "status_code", 200) or 200
        if status == 416:
            self._send_bytes(416, "Range Not Satisfiable")
            try:
                resp.close()
            except Exception:
                pass
            return

        start_offset = 0
        if status == 206 and client_range:
            m = re.match(r"bytes=(\d+)-", client_range)
            if m:
                start_offset = int(m.group(1))
        total = (_declared_length(resp) if _range_is_closed(client_range)
                 else _upstream_total(resp, start_offset))
        excluded = {"content-length", "transfer-encoding", "connection",
                    "content-encoding"}
        out_headers = {"Access-Control-Allow-Origin": "*"}
        try:
            for k, v in resp.headers.items():
                if k.lower() not in excluded:
                    out_headers[k] = v
        except Exception:
            pass
        out_headers.setdefault("Content-Type", "video/mp2t")

        self._stream(
            status, out_headers,
            resilient_body(target_url, headers, start_offset=start_offset,
                           first_resp=resp, first_total=total,
                           no_progress_budget=None,
                           client_gone=self._client_gone),
            total=total,
        )

    def _h_video(self, args):
        target_url = args.get("url")
        if not target_url:
            self._send_bytes(400, "Missing URL")
            return
        headers = self._parse_headers_arg(args)
        client_range = self.headers.get("Range")
        resp, target_url = _open_stream_response(
            target_url, headers, stream=True, client_range=client_range,
            max_retries=4,
        )
        if not resp:
            self._send_bytes(502, "Error fetching video")
            return
        status = getattr(resp, "status_code", 200) or 200
        if status == 416:
            out = {}
            try:
                cr = (resp.headers.get("Content-Range")
                      or resp.headers.get("content-range"))
                if cr:
                    out["Content-Range"] = cr
            except Exception:
                pass
            self._send_bytes(416, b"", extra=out)
            try:
                resp.close()
            except Exception:
                pass
            return

        excluded = {"content-encoding", "content-length", "transfer-encoding",
                    "connection"}
        out_headers = {"Access-Control-Allow-Origin": "*"}
        try:
            for k, v in resp.headers.items():
                if k.lower() not in excluded:
                    out_headers[k] = v
        except Exception:
            pass
        out_headers.setdefault("Accept-Ranges", "bytes")

        # Only a real 206 starts at the requested offset. If the origin
        # ignored Range and returned 200, the body starts at 0 — forwarding
        # the client's offset would corrupt every subsequent byte.
        start_offset = 0
        if status == 206 and client_range:
            m = re.match(r"bytes=(\d+)-", client_range)
            if m:
                start_offset = int(m.group(1))
        total = (_declared_length(resp) if _range_is_closed(client_range)
                 else _upstream_total(resp, start_offset))
        self._stream(
            status, out_headers,
            resilient_body(target_url, headers, start_offset=start_offset,
                           first_resp=resp, first_total=total,
                           no_progress_budget=None,
                           client_gone=self._client_gone),
            total=total,
        )

    def _h_subtitle(self, args):
        import os
        sub_path = args.get("path")
        if not sub_path:
            self._send_bytes(404, "Subtitle not found")
            return
        # Jail to known subtitle locations (serveur-local temp + download dir).
        # realpath() neutralise `..` et symlinks ; pas de CORS ici (le player
        # est servi par ce même proxy, same-origin suffit).
        try:
            real = os.path.realpath(sub_path)
        except Exception:
            self._send_bytes(403, "Forbidden")
            return
        allowed = [os.path.realpath(d) for d in _subtitle_allowed_dirs()]
        if not any(real == a or real.startswith(a + os.sep) for a in allowed):
            self._send_bytes(403, "Forbidden")
            return
        if not os.path.isfile(real):
            self._send_bytes(404, "Subtitle not found")
            return
        try:
            if os.path.getsize(real) > _SUBTITLE_MAX_BYTES:
                self._send_bytes(413, "Subtitle too large")
                return
            with open(real, "rb") as f:
                content = f.read()
            vtt = _srt_to_vtt(content, real.lower().endswith(".srt"))
            self._send_bytes(200, vtt, "text/vtt")
        except Exception as e:
            self._send_bytes(500, f"Error loading subtitle: {e}")


# ---------------------------------------------------------------------------
# Server launch
# ---------------------------------------------------------------------------
_start_lock = threading.Lock()
_ready_event = threading.Event()


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # mpv opens MANY connections for segments and drops them abruptly (end
        # of segment, seek, quality switch) → a flood of ConnectionResetError /
        # BrokenPipe tracebacks with the stdlib server. Those are NORMAL, not
        # errors : swallow them (Flask/werkzeug hid them too). Anything else is
        # logged, not printed.
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError,
                            ConnectionAbortedError, TimeoutError)):
            return
        try:
            from . import logsetup
            logsetup.warning(f"proxy server error from {client_address}: {exc}")
        except Exception:
            pass


def _run_server(port):
    global _server_instance
    # ThreadingHTTPServer binds immediately, so once it's constructed the port
    # is accepting — signal readiness before serve_forever (no race).
    _server_instance = _ProxyServer((PROXY_HOST, port), _ProxyHandler)
    _ready_event.set()
    _server_instance.serve_forever()


def start_proxy_server(port=0):
    global PROXY_PORT, PROXY_URL
    if port == 0:
        port = find_free_port()
    PROXY_PORT = port
    PROXY_URL = f"http://{PROXY_HOST}:{PROXY_PORT}"
    _ready_event.clear()
    t = threading.Thread(target=_run_server, args=(port,))
    t.daemon = True
    t.start()
    return port


def ensure_started(port=0, wait=5.0):
    """Idempotent proxy start, called lazily on first playback. Blocks until the
    socket is accepting. Returns the proxy port."""
    with _start_lock:
        if PROXY_URL is None or _server_instance is None:
            start_proxy_server(port)
    _ready_event.wait(timeout=wait)
    return PROXY_PORT


def stop_proxy_server():
    """Shut the proxy server down gracefully."""
    global _server_instance
    if _server_instance:
        try:
            _server_instance.shutdown()
            _server_instance.server_close()
        except Exception:
            pass
        _server_instance = None


if __name__ == "__main__":
    my_port = start_proxy_server(0)
    print(f"{t('Proxy on')} http://{PROXY_HOST}:{my_port} — {t('Ctrl+C to quit.')}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(t("Stopping."))
        stop_proxy_server()
