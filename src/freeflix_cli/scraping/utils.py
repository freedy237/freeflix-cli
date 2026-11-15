from __future__ import annotations

from typing import List
import re
import urllib.parse
from .objects import Player, Episode

# Marks a reader slot whose real URL is minted on demand by animes-sama.fr's
# signed /api/player/sign endpoint (the site no longer exposes player URLs).
ANIME_SAMA_SIGNED_SENTINEL = "anime-sama:signed"


def parse_episodes_from_js(js_code: str, host_map: dict = None) -> List[Episode]:
    """
    Parse a JavaScript code into a list of episodes.

    Three formats exist, because the Anime-Sama mirrors do not agree:

    * ``var eps1 = ["https://player/…", …]`` — the URL sits in the array.
    * ``var eps1 = ["lien:62233", …]`` — the 12/11/2026 format: the array
      holds a row id, and the real embed URL is fetched from
      ``/api/lien.php?j=<page token>&l=<id>``. ``epsMeta`` (passed as
      *host_map*) maps the id to its host so the menu can still say where the
      row points.
    * ``var eps1 = ["1","1","",…]`` — animes-sama.fr only publishes whether a
      reader exists; ``/api/player/sign`` mints the URL.

    Both indirect formats yield ``ANIME_SAMA_SIGNED_SENTINEL`` URLs plus the
    metadata a resolver needs, so the rest of the app never sees a fake URL.
    """
    host_map = host_map or {}
    matches = re.findall(r"var\s+eps(\d+)\s*=\s*\[(.*?)\];", js_code, re.DOTALL)

    lecteurs = {}
    for lecteur_num, content in matches:
        urls = re.findall(r"'(https?://.*?)'", content)
        urls += [u for u in re.findall(r'"(https?://.*?)"', content) if u not in urls]
        if urls:
            lecteurs[int(lecteur_num)] = urls
            continue
        # Indirect format: one quoted entry per episode slot.
        entries = re.findall(r'"([^"]*)"', content)
        slots = []
        for entry in entries:
            entry = entry.strip()
            if not entry:
                slots.append(None)
            elif entry.startswith("lien:"):
                slots.append(("lien", entry[5:].strip()))
            else:
                # Availability flag ("1") — resolved by the signed API.
                slots.append(("flag", None))
        lecteurs[int(lecteur_num)] = slots

    lecteurs = dict(sorted(lecteurs.items()))

    if not lecteurs:
        return []
    max_episodes = max(len(lst) for lst in lecteurs.values())

    lecteur_names = [f"Lecteur {i+1}" for i in range(len(lecteurs))]

    episodes = []
    for i in range(max_episodes):
        players = []
        for j, (lecteur_num, slots) in enumerate(lecteurs.items()):
            url = slots[i] if i < len(slots) else None
            if not url:
                continue
            meta = {}
            if url == ANIME_SAMA_SIGNED_SENTINEL:
                # 1-based reader index + episode; the resolver completes it.
                meta = {"slot": {"ep": i + 1, "lecteur": lecteur_num}}
            elif isinstance(url, tuple):
                kind, value = url
                meta = {"slot": {"ep": i + 1, "lecteur": lecteur_num}}
                if kind == "lien" and value:
                    info = host_map.get(value) or ()
                    host = info[0] if isinstance(info, (tuple, list)) and info else ""
                    dead = bool(isinstance(info, (tuple, list))
                                and len(info) > 1 and info[1] in (1, 2))
                    # Keep the row id on the slot too: the resolver reads the
                    # slot (it travels in the player headers), not meta.
                    meta["slot"]["lien_id"] = value
                    if host:
                        meta["host"] = host
                        meta["slot"]["host"] = host
                    if dead:
                        meta["dead"] = True
                url = ANIME_SAMA_SIGNED_SENTINEL
            players.append(Player(lecteur_names[j], url, meta))
        # A placeholder slot with no player at all is NOT an episode. Some
        # shows pad one player array with extra slots, which used to inflate
        # the episode count in the menu.
        if players:
            episodes.append(Episode(title=f"Épisode {i+1}", players=players))

    return episodes


_WS_RE = __import__("re").compile(r"\s+")


def clean_text(value, fallback: str = "") -> str:
    """Normalise a scraped human-readable string, everywhere.

    HTML entities decoded, non-breaking/zero-width spaces removed, whitespace
    collapsed, leading/trailing separators trimmed. This is what keeps the UI
    free of double spaces, stray "&amp;", trailing " | Site" and the like —
    scraped titles flow straight into menus and posters."""
    if value is None:
        return fallback
    try:
        import html as _html
        text = str(value)
        text = _html.unescape(text)
        text = (text.replace("\u00a0", " ").replace("\u200b", "")
                    .replace("\u200e", "").replace("\ufeff", ""))
        text = _WS_RE.sub(" ", text).strip()
        text = text.strip(" -|·—:;,")
        return text or fallback
    except Exception:
        return fallback


def parse_html(markup):
    """BeautifulSoup with the FAST lxml parser (now a default dependency),
    falling back to html5lib (lenient, always installed) on platforms where
    the lxml wheel is unavailable (e.g. some Termux setups). lxml is
    ~10-30x faster on big pages, so sources feel much snappier."""
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(markup, "lxml")
    except Exception:
        return BeautifulSoup(markup, "html5lib")


# Markers that identify a Cloudflare / anti-bot CHALLENGE page (not a normal
# page that merely embeds a Cloudflare script). Such a body must NEVER be
# written to the TTL cache: one transient block would otherwise poison the
# source for the whole TTL ("no results" for 5-30 minutes after the challenge
# passed).
_CHALLENGE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "cf_chl_opt",
    "cf-challenge",
    "anti-robot",
    "antirobot",
    "botblocker",
    "globus.studio",
    "attention required",
    "checking your browser",
    "verifying you are human",
    "enable javascript and cookies to continue",
)


def cacheable_body(text) -> bool:
    """True when a fetched body is worth caching: non-empty and not a bot
    challenge. Best-effort — only ever prevents a bad cache entry."""
    if not text:
        return False
    low = str(text)[:4000].lower()
    return not any(m in low for m in _CHALLENGE_MARKERS)


# ─── Portal origin cache (persisted, 24 h) ─────────────────────────
# Resolving a source's live mirror costs 1-4 s (2 requests + possibly a DoH
# retry) on EVERY launch / provider entry. The settled origin is stable for
# days, so we persist it for 24 h — first entry of the day pays the cost,
# every later one is instant. A moved domain self-heals after the TTL.
_ORIGIN_TTL = 24 * 3600


def _origin_cache_file():
    from platformdirs import user_cache_dir
    from pathlib import Path
    d = Path(user_cache_dir("AutoFlixCLI", "PaulExplorer"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "origins.json"


def load_origin(key: str):
    """Cached settled origin for a source, or None when absent/expired."""
    import json
    import time
    try:
        with open(_origin_cache_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None
    origin = entry.get("origin")
    ts = entry.get("ts", 0)
    if not origin or not isinstance(ts, (int, float)):
        return None
    if time.time() - ts > _ORIGIN_TTL:
        return None  # expired — re-resolve once
    return str(origin)


def store_origin(key: str, origin: str):
    """Persist a settled origin (best-effort, never raises)."""
    import json
    import time
    try:
        path = _origin_cache_file()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data[key] = {"origin": origin, "ts": time.time()}
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
    except Exception:
        pass


def clear_origin_cache():
    try:
        _origin_cache_file().unlink()
    except OSError:
        pass


def mask_url(url: str, max_len: int = 120) -> str:
    """Return a log/UI-safe URL: query and fragment removed, length capped.

    Signed CDN links (CloudFront, Vidzy, uqload) carry short-lived credentials
    in the query string; printing them leaked working links into the terminal,
    scrollback and the log file. The host and path are enough to diagnose.
    """
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(str(url))
        safe = f"{parts.scheme}://{parts.netloc}{parts.path}"
        if parts.query:
            safe += "?…"
        return safe[:max_len]
    except Exception:
        return str(url)[:max_len]
