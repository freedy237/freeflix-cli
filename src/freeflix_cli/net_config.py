"""
Lightweight networking config shared by the scrapers and the proxy.

Kept SEPARATE from proxy.py (which pulls in Flask, ~100 ms) so importing a
scraper doesn't drag Flask into startup. The proxy server is now started lazily
on first playback instead of at launch.
"""

from curl_cffi import CurlOpt

# DoH TLS relax — some networks' DoH resolver has a self-signed / mismatched
# cert; without this, curl_cffi's DoH path fails. Harmless when DoH isn't used.
DNS_OPTIONS = {
    CurlOpt.DOH_SSL_VERIFYPEER: 0,
    CurlOpt.DOH_SSL_VERIFYHOST: 0,
}
