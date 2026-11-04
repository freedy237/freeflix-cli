"""
Lightweight networking config shared by the scrapers and the proxy.

Kept SEPARATE from proxy.py (which pulls in the m3u8 lib + starts a server) so importing a
scraper doesn't drag the proxy into startup. The proxy server is now started lazily
on first playback instead of at launch.
"""

from curl_cffi import CurlOpt

# DoH TLS: verify the resolver certificate. It used to be disabled to tolerate
# networks with a self-signed/mismatched DoH endpoint, but that let a MITM
# forge DNS answers on the fallback path. 1.1.1.1 presents a valid cert; if a
# network intercepts DoH, point CurlOpt.DOH_URL at its resolver instead.
#
# CONNECTTIMEOUT caps the CONNECT phase (DNS + TCP + TLS) at 15 s on EVERY
# session that uses these options — so a dead host can never hang a request
# forever, even a call site that forgot an explicit ``timeout=``. It only limits
# connecting, NOT the transfer, so slow-but-alive streams are unaffected.
DNS_OPTIONS = {
    CurlOpt.CONNECTTIMEOUT: 15,
}


# ── Shared per-thread session ─────────────────────────────────────────
# Some call sites (stream resolution, size probing) used to spin up a BRAND
# NEW curl_cffi Session on every call — repaying DNS + TLS each time. This
# hands back ONE persistent session per thread (keep-alive + cached DoH),
# already carrying DNS_OPTIONS + chrome impersonation. Thread-local because
# curl_cffi sessions are not safe to share across threads.
import threading as _threading

_session_tls = _threading.local()


def shared_session():
    """Return this thread's reusable curl_cffi session (created on first use)."""
    s = getattr(_session_tls, "s", None)
    if s is None:
        from curl_cffi import requests as _rq
        s = _rq.Session(impersonate="chrome")
        try:
            s.curl_options.update(DNS_OPTIONS)
        except Exception:
            pass
        _session_tls.s = s
    return s
