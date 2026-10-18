from __future__ import annotations

from typing import List
import re
from .objects import Player, Episode


def parse_episodes_from_js(js_code: str) -> List[Episode]:
    """
    Parse a JavaScript code into a list of episodes.
    """
    matches = re.findall(r"var\s+eps(\d+)\s*=\s*\[(.*?)\];", js_code, re.DOTALL)

    lecteurs = {}
    for lecteur_num, content in matches:
        urls = re.findall(r"'(https?://.*?)'", content)
        urls += [u for u in re.findall(r'"(https?://.*?)"', content) if u not in urls]
        lecteurs[int(lecteur_num)] = urls

    lecteurs = dict(sorted(lecteurs.items()))

    if not lecteurs:
        return []
    max_episodes = max(len(lst) for lst in lecteurs.values())

    lecteur_names = [f"Lecteur {i+1}" for i in range(len(lecteurs))]

    episodes = []
    for i in range(max_episodes):
        players = []
        for name, urls in zip(lecteur_names, lecteurs.values()):
            url = urls[i] if i < len(urls) else None
            if url:
                players.append(Player(name, url))
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
