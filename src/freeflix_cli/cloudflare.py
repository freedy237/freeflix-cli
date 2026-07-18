"""
Optional Cloudflare cf_clearance fallback.

Some sources (Coflix, Anime-Sama…) occasionally put up a Cloudflare
challenge — typically under heavy load, when the captcha hits everyone.
There's no clean automatic bypass, but a user who solved the challenge in
their browser can paste their **cf_clearance** cookie (and the matching
User-Agent) so FreeFlix rides their already-cleared session.

cf_clearance is bound to IP + User-Agent, so the UA must match the browser
that obtained the cookie — that's why we let the user provide it.

Idea borrowed from SertraFurr/Anime-Sama-Downloader.
"""

from urllib.parse import urlparse

from .tracker import tracker

try:
    from curl_cffi import requests as _cffi, CurlOpt as _CurlOpt
except Exception:  # pragma: no cover
    _cffi = None
    _CurlOpt = None

# Session-level cache : once we've found FlareSolverr to be unreachable we
# stop hammering it (so a missing solver costs at most one quick failure).
_FS_DEAD = False


def host_of(url: str) -> str:
    """Registrable-ish host (last two labels): coflix.cymru, anime-sama.to."""
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    parts = h.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def get_cf_headers(url: str) -> dict:
    """
    Cookie / User-Agent headers to ride the user's cf_clearance for this
    host, or {} if none is set. Safe to merge into any request.
    """
    rec = tracker.get_cf_clearance(host_of(url))
    if not rec:
        return {}
    headers = {}
    token = (rec.get("token") or "").strip()
    if token:
        # Keep just the value if the user pasted "cf_clearance=…".
        if token.lower().startswith("cf_clearance="):
            token = token.split("=", 1)[1]
        headers["Cookie"] = f"cf_clearance={token}"
    ua = (rec.get("ua") or "").strip()
    if ua:
        headers["User-Agent"] = ua
    return headers


def has_token(url: str) -> bool:
    rec = tracker.get_cf_clearance(host_of(url))
    return bool(rec and rec.get("token"))


_MARKERS = (
    "cloudflare",
    "cf-ray",
    "cdn-cgi",
    "attention required",
    "just a moment",
    "checking your browser",
)


def is_blocked(response) -> bool:
    """Heuristic : does this response look like a Cloudflare challenge?"""
    try:
        if response.status_code not in (403, 429, 503):
            return False
        body = (response.text or "").lower()
    except Exception:
        return False
    return any(m in body for m in _MARKERS)


CF_HELP = (
    "Cloudflare is challenging this source (often happens under load).\n"
    "  To get past it : open the site in your browser, pass the check, then\n"
    "  copy the 'cf_clearance' cookie value + your browser User-Agent into\n"
    "  Settings → Cloudflare token. FreeFlix will reuse them for this host."
)


def solve_and_store(url: str, timeout: int = 60) -> bool:
    """
    Ask FlareSolverr to solve the Cloudflare JS challenge for `url`,
    harvest the cf_clearance cookie + the browser User-Agent it used, and
    store them so the normal (fast) scraper can ride that cleared session.

    Returns True if a fresh cf_clearance was obtained and stored. Fails
    gracefully (and remembers a dead solver) so it never blocks the app.
    """
    global _FS_DEAD
    fs = (tracker.get_flaresolverr_url() or "").strip()
    if not fs or _FS_DEAD or _cffi is None:
        return False

    try:
        r = _cffi.post(
            fs.rstrip("/") + "/v1",
            json={"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000},
            timeout=timeout + 5,
        )
        data = r.json()
    except Exception:
        # Connection refused / not installed / crashed → stop trying this run.
        _FS_DEAD = True
        return False

    if (data or {}).get("status") != "ok":
        return False

    solution = data.get("solution") or {}
    ua = solution.get("userAgent")
    token = None
    for c in solution.get("cookies") or []:
        if c.get("name") == "cf_clearance":
            token = c.get("value")
            break
    if not token:
        return False

    tracker.set_cf_clearance(host_of(url), token, ua)
    return True


def cf_get(session, url, **kw):
    """
    Central Cloudflare-aware GET for any scraper session.

    Cascade : ride a stored cf_clearance cookie → request → if the response
    looks like a Cloudflare challenge, ask FlareSolverr to solve it, store
    the fresh clearance, and retry once. Fully transparent when no Cloudflare
    is involved (a 200 isn't even inspected), so it's safe to use everywhere.
    """
    import time as _t

    base_headers = kw.pop("headers", {})
    kw.setdefault("timeout", 20)  # never hang a fetch on a dead host

    def _headers():
        cf = get_cf_headers(url)
        return {**cf, **base_headers} if cf else dict(base_headers)

    def _fetch():
        h = _headers()
        return session.get(url, headers=h, **kw) if h else session.get(url, **kw)

    # Transient "Connection reset by peer" / DNS hiccups are common with
    # these hosts (often the DoH resolver flaking). Retry a few times, then
    # fall back to a plain request (system DNS, no DoH), and finally to
    # DNS-over-HTTPS (bypasses ISP DNS blocks) as a last resort.
    resp = None
    last_exc = None
    for attempt in range(3):
        try:
            resp = _fetch()
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            _t.sleep(0.4 * (attempt + 1))
    if last_exc is not None:
        try:
            from curl_cffi import requests as _rq
            h = _headers()
            resp = _rq.get(url, impersonate="chrome", headers=h or None, **kw)
        except Exception:
            try:
                _doh = _rq.Session(
                    impersonate="chrome",
                    curl_options={
                        _CurlOpt.DOH_URL: "https://1.1.1.1/dns-query",
                        _CurlOpt.DOH_SSL_VERIFYPEER: 0,
                        _CurlOpt.DOH_SSL_VERIFYHOST: 0,
                    },
                )
                h = _headers()
                resp = _doh.get(url, headers=h or None, **kw) if h else _doh.get(url, **kw)
            except Exception:
                raise last_exc from None

    try:
        blocked = is_blocked(resp)
    except Exception:
        blocked = False
    if blocked and solve_and_store(url):
        try:
            resp = _fetch()
        except Exception:
            pass
    return resp
