"""
Hot-patchable extractor selectors + multi-strategy helpers.

Scrapers break the day a site changes its HTML. Two defenses live here :

1. **Hot-patchable selectors** — instead of hardcoding one CSS class deep in a
   scraper, the fragile bits are looked up by name from a table that can be
   OVERRIDDEN by a remote ``data/selectors.jsonc`` (in our repo). When a source
   breaks we push a new selector and every user picks it up on next launch —
   no release, no reinstall. The baked-in DEFAULTS always keep today's working
   behavior, so an empty/unavailable remote changes nothing.

2. **Multi-strategy extraction** — ``first_text`` / ``first_attr`` try a LIST
   of CSS selectors in order and return the first hit, so a layout tweak that
   renames one class still resolves via the next fallback.

Everything is best-effort and synchronous-safe : the remote patch is fetched in
a background thread (like portals), so importing this module never blocks.
"""

from __future__ import annotations

import threading

# Baked-in defaults = exactly today's working selectors. Each value is a LIST of
# CSS selectors tried in order (first match wins). Adding a fallback here — or
# via the remote file — is how a source is repaired.
DEFAULT_SELECTORS: dict[str, dict[str, list[str]]] = {
    "anime-sama": {
        "search_container": ["#list_catalog"],
        "search_card": ["div.card-content"],
        "search_title": ["h2"],
        "search_genre": ["p.info-value"],
        "search_info": ["p.info-value"],
        "series_title": ["h4#titreOeuvre", "h1"],
        "series_cover": [
            "meta[property='og:image']",
            "img#coverOeuvre",
        ],
        "series_genres": ["a.text-sm.text-gray-300"],
    },
}

# Live table (defaults, then remote/local overrides merged in). Mutated in place
# so importers keep seeing the live dict.
_selectors: dict[str, dict[str, list[str]]] = {
    src: {k: list(v) for k, v in keys.items()}
    for src, keys in DEFAULT_SELECTORS.items()
}
_lock = threading.Lock()


def selectors(source: str) -> dict[str, list[str]]:
    """Selector table for *source* (live, with any remote overrides applied)."""
    with _lock:
        return dict(_selectors.get(source, {}))


def get(source: str, key: str, default: list[str] | None = None) -> list[str]:
    """Ordered list of CSS selectors for (source, key)."""
    with _lock:
        table = _selectors.get(source, {})
        if key in table:
            return list(table[key])
    if default is not None:
        return default
    return DEFAULT_SELECTORS.get(source, {}).get(key, [])


# ── Multi-strategy BeautifulSoup helpers ──────────────────────────────
def first(soup, source: str, key: str):
    """First Tag matching any of (source, key)'s selectors, or None."""
    for css in get(source, key):
        try:
            el = soup.select_one(css)
        except Exception:
            el = None
        if el is not None:
            return el
    return None


def first_text(soup, source: str, key: str, default: str = "") -> str:
    el = first(soup, source, key)
    return el.get_text(strip=True) if el is not None else default


def first_attr(soup, source: str, key: str, *attrs: str, default: str = "") -> str:
    """First non-empty value among *attrs* on the first matching element.

    ``meta`` tags are handled specially : their value is the ``content`` attr.
    """
    el = first(soup, source, key)
    if el is None:
        return default
    names = attrs or ("content", "src", "data-src", "data-lazy-src", "href")
    for a in names:
        v = el.attrs.get(a)
        if v:
            return v.strip()
    return default


# ── Remote hot-patch (background, best-effort) ────────────────────────
REMOTE_SELECTORS_URL = (
    "https://raw.githubusercontent.com/freedy237/freeflix-cli/main/"
    "data/selectors.jsonc"
)


def _merge(remote: dict) -> None:
    if not isinstance(remote, dict):
        return
    with _lock:
        for src, keys in remote.items():
            if not isinstance(keys, dict):
                continue
            table = _selectors.setdefault(src, {})
            for k, v in keys.items():
                # Accept a single string or a list ; normalise to a list.
                table[k] = [v] if isinstance(v, str) else list(v)


def _refresh_remote() -> None:
    try:
        from ..config_loader import load_remote_jsonc
        remote = load_remote_jsonc(REMOTE_SELECTORS_URL, None)
        if remote:
            _merge(remote)
    except Exception:
        pass


def start_background_refresh() -> None:
    threading.Thread(target=_refresh_remote, daemon=True).start()
