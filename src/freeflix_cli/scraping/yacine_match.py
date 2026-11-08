"""YacineTV live football catalogue (unofficial API).

The APK hard-codes a dead host; the real one is injected through Firebase
Remote Config (``defaults``).  The API answers **encrypted** payloads:
Base64, then XOR with ``_KEY + <t header>``.  We fetch the schedule on every
entry (the catalogue must stay current, like the Anime-Sama planning) and keep
a small disk cache only as an offline fallback.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from curl_cffi import requests
from platformdirs import user_cache_dir

_KEY = b"c!xZj+N9&G@Ev@vw"
_UA = "okhttp/4.12.0"
_API_HOSTS = ("def001.ycnapi.com", "def.yacinelive.com")
_CAMEROON = timezone(timedelta(hours=1))  # Africa/Douala, no DST

_HOST_CACHE = "host.txt"
_EVENTS_CACHE = "events.json"
_CACHE_MAX_AGE = 24 * 3600
_ARABIC = re.compile(r"[\u0600-\u06ff]")

# Bundled reference data (no network needed for the common case):
#  * clubs.json          → club lookup keys (Arabic / short / EN) → EN + FR
#  * channel_logos.json  → channel name → logo (iptv-org catalogue)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DICT_CACHE: dict = {}


def _load_data(name: str) -> dict:
    """Load a bundled JSON once (empty dict on failure)."""
    if name not in _DICT_CACHE:
        try:
            _DICT_CACHE[name] = json.loads(
                (_DATA_DIR / name).read_text(encoding="utf-8"))
        except Exception:
            _DICT_CACHE[name] = {}
    return _DICT_CACHE[name] or {}


def _norm_key(text: str) -> str:
    """Lowercase, strip accents/punctuation → stable lookup key."""
    import unicodedata
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _cache_dir() -> Path:
    d = Path(user_cache_dir("freeflix-cli", "PaulExplorer")) / "yacine"
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        pass
    return d


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, value) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
    except OSError:
        pass


def decrypt_payload(payload: str, timestamp: str) -> dict:
    """Decrypt one API body (Base64 + repeating XOR with key+t)."""
    raw = base64.b64decode((payload or "").strip())
    key = _KEY + (timestamp or "").encode("utf-8")
    if not key:
        raise ValueError("empty decryption key")
    plain = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return json.loads(plain.decode("utf-8"))


def _request_json(host: str, path: str, timeout: int = 10) -> dict:
    r = requests.get(
        f"https://{host}{path}",
        headers={"User-Agent": _UA, "Accept": "application/json"},
        impersonate="chrome",
        timeout=timeout,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    stamp = r.headers.get("t") or str(int(time.time()))[:10]
    return decrypt_payload(r.text, stamp)


def _cached_host() -> str | None:
    host = (_cache_dir() / _HOST_CACHE).read_text(encoding="utf-8").strip() \
        if (_cache_dir() / _HOST_CACHE).exists() else ""
    if host and host in _API_HOSTS:
        return host
    return None


def _hosts_to_try() -> list[str]:
    cached = _cached_host()
    return ([cached] if cached else []) + [h for h in _API_HOSTS if h != cached]


@dataclass
class MatchEvent:
    id: str
    championship: str
    channel: str
    start: int
    end: int
    home: str
    away: str
    commentary: str = ""
    home_logo: str = ""
    away_logo: str = ""

    @property
    def start_dt(self) -> datetime:
        return datetime.fromtimestamp(self.start, tz=_CAMEROON)

    @property
    def end_dt(self) -> datetime:
        return datetime.fromtimestamp(self.end, tz=_CAMEROON)

    def status(self, now: int | None = None) -> str:
        now = int(time.time()) if now is None else int(now)
        if self.start <= now < max(self.end, self.start + 60):
            return "live"
        if now < self.start:
            return "upcoming"
        return "ended"

    def score(self) -> str:
        return f"{self.home} - {self.away}"


def _event_from_dict(raw: dict) -> MatchEvent | None:
    try:
        start = int(raw.get("start_time") or 0)
        end = int(raw.get("end_time") or 0)
        if not start:
            return None
        if not end or end < start:
            end = start + 2 * 3600
        home = (raw.get("team_1") or {}).get("name") or "?"
        away = (raw.get("team_2") or {}).get("name") or "?"
        return MatchEvent(
            id=str(raw.get("id") or ""),
            championship=str(raw.get("champions") or ""),
            channel=str(raw.get("channel") or ""),
            start=start,
            end=end,
            home=str(home),
            away=str(away),
            commentary=str(raw.get("commentary") or ""),
            home_logo=str((raw.get("team_1") or {}).get("logo") or ""),
            away_logo=str((raw.get("team_2") or {}).get("logo") or ""),
        )
    except Exception:
        return None


def _parse_events(data) -> list[MatchEvent]:
    if isinstance(data, dict):
        data = data.get("data") or []
    if not isinstance(data, list):
        return []
    out = []
    for raw in data:
        if isinstance(raw, dict):
            ev = _event_from_dict(raw)
            if ev and ev.id:
                out.append(ev)
    return out


def _save_events(events: list[MatchEvent]) -> None:
    _write_json(
        _cache_dir() / _EVENTS_CACHE,
        {"fetched_at": int(time.time()),
         "events": [{
             "id": ev.id, "champions": ev.championship, "channel": ev.channel,
             "start_time": ev.start, "end_time": ev.end,
             "team_1": {"name": ev.home, "logo": ev.home_logo},
             "team_2": {"name": ev.away, "logo": ev.away_logo},
             "commentary": ev.commentary,
         } for ev in events]},
    )


def load_cached_events() -> list[MatchEvent]:
    blob = _read_json(_cache_dir() / _EVENTS_CACHE, {})
    raw = blob.get("events") if isinstance(blob, dict) else []
    return [ev for ev in (_event_from_dict(r) for r in (raw or []))
            if ev is not None]


def fetch_events(timeout: int = 10) -> tuple[list[MatchEvent], bool]:
    """Return ``(events, from_cache)``.

    Always tries the network first; falls back to the last disk snapshot when
    the API/host is unreachable.
    """
    last_err = None
    for host in _hosts_to_try():
        try:
            data = _request_json(host, "/api/events", timeout=timeout)
            events = _parse_events(data)
            try:
                (_cache_dir() / _HOST_CACHE).write_text(host, encoding="utf-8")
            except OSError:
                pass
            _save_events(events)
            return events, False
        except Exception as exc:  # noqa: BLE001 - one host failing is normal
            last_err = exc
    cached = load_cached_events()
    if cached:
        return cached, True
    raise RuntimeError(f"YacineTV API unavailable: {last_err}")


def _quality_rank(name: str) -> int:
    n = (name or "").lower()
    # "Multi" sources are official multi-camera feeds: usually the most
    # reliable live source when the per-quality CDN is throttled.
    if "multi" in n:
        return 3
    if any(k in n for k in ("4k", "2160", "uhd")):
        return 5
    if any(k in n for k in ("1440", "2k")):
        return 4
    if any(k in n for k in ("hd", "fhd", "1080", "full")):
        return 3
    if any(k in n for k in ("sd", "720", "medium")):
        return 2
    if any(k in n for k in ("low", "360", "240", "480")):
        return 1
    return 2


def _stream_from_dict(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
    headers = {str(k): str(v) for k, v in headers.items() if v}
    if not headers.get("Referer") and raw.get("referer"):
        headers["Referer"] = str(raw["referer"])
    if not headers.get("User-Agent") and raw.get("user_agent"):
        headers["User-Agent"] = str(raw["user_agent"])
    return {
        "name": str(raw.get("name") or "?"),
        "url": url,
        "headers": headers,
        "url_type": raw.get("url_type"),
        "drm": raw.get("drm"),
    }


def fetch_streams(event_id: str, timeout: int = 10) -> list[dict]:
    """Return playable stream descriptors for one event (fresh tokens)."""
    last_err = None
    for host in _hosts_to_try():
        try:
            data = _request_json(
                host, f"/api/event/{urllib.parse.quote(str(event_id))}",
                timeout=timeout,
            )
            raw = data.get("data") if isinstance(data, dict) else data
            streams = [s for s in (_stream_from_dict(r) for r in (raw or []))
                       if s and not s.get("drm")]
            if streams:
                # Stable sort: rank first, then keep the catalogue order.
                # "Multi" feeds come first (most reliable live source),
                # HD/SD/Low after them.
                order = {id(s): i for i, s in enumerate(streams)}
                streams.sort(
                    key=lambda s: (-_quality_rank(s["name"]), order[id(s)]))
                return streams
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if last_err:
        raise RuntimeError(f"YacineTV stream API unavailable: {last_err}")
    return []


def pick_auto(streams: list[dict]) -> dict | None:
    """Best available stream according to its quality name."""
    if not streams:
        return None
    return max(streams, key=lambda s: _quality_rank(str(s.get("name") or "")))


def _translations_path(lang: str) -> Path:
    return _cache_dir() / f"translations_{lang}.json"


def _translate_one(text: str, lang: str, timeout: int = 5) -> str:
    """Dynamic AR→FR/EN translation (Google gtx endpoint), no static table."""
    if not _ARABIC.search(text or ""):
        return text
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "ar", "tl": lang,
                    "dt": "t", "q": text},
            impersonate="chrome", timeout=timeout,
        )
        data = r.json()
        out = (data[0][0][0] or "").strip()
        return out or text
    except Exception:
        return text


# Words a machine translation gets wrong on its own: generic football nouns
# that are NOT part of a club name. They are only used to reject a translation
# that is obviously a literal word (e.g. "ليل" → "night" instead of "Lille").
_GENERIC_WORDS = {
    "night", "day", "sun", "sunset", "sunrise", "save", "save it", "twenty",
    "the chi", "union of algeria", "union de l'algerie", "lance", "le mans",
    "ren", "man", "city", "united", "real", "sport", "sports", "league",
    "championship", "cup", "super cup", "premier league", "village",
}


# Arabic spellings that a machine translator mangles ("ليل" → "night").
# Values are keys of the bundled clubs.json.
_AR_CLUB_KEYS = {
    "ليل": "lille", "لانس": "lens", "ليون": "lyon", "مان يونايتد": "manchester united",
    "تونتي": "twente", "انجيه": "angers", "رين": "rennes", "كامبور": "cambuur",
    "فينورد روتردام": "feyenoord", "كريستال بلاس": "crystal palace",
    "التشي": "chievo", "ليفانتي": "levante", "برايتون": "brighton",
    "برينتفورد": "brentford", "اشبيلية": "sevilla",
    "اياكس": "ajax", "ايندهوفن": "psv", "فياريال": "villarreal",
    "خيتافي": "getafe", "سيلتا فيغو": "celta", "سندرلاند": "sunderland",
    "تشيلسي": "chelsea", "ليفربول": "liverpool", "برشلونة": "barcelona",
    "ريال مدريد": "real madrid", "اتلتيكو مدريد": "atletico",
    "مارسيليا": "marseille", "موناكو": "monaco", "لاهاي": "den haag",
    "لومان": "le mans", "بريست": "brest", "نيس": "nice", "بون": "bonn",
    "سونداونز": "sundowns", "اتحاد الجزائر": "usm alger",
    "مولودية الجزائر": "mca", "مانشستر يونايتد": "manchester united",
}


def _club_lookup(text: str, lang: str) -> str | None:
    """Bundled club dictionary: Arabic/short/EN name → EN or FR club name."""
    clubs = _load_data("clubs.json")
    if not clubs:
        return None
    ar_text = (text or "").strip().replace("\u0623", "\u0627").replace("\u0625", "\u0627")
    ar = _AR_CLUB_KEYS.get(ar_text) or _AR_CLUB_KEYS.get((text or "").strip())
    if ar:
        entry = clubs.get(ar)
        if entry:
            return entry.get(lang) or entry.get("en")
    key = _norm_key(text)
    if key in clubs:
        return clubs[key].get(lang) or clubs[key].get("en")
    # token fallback: "Manchester City FC" → "manchester city"
    tokens = key.split()
    for size in (3, 2, 1):
        if len(tokens) >= size:
            cand = " ".join(tokens[:size])
            if cand in clubs:
                return clubs[cand].get(lang) or clubs[cand].get("en")
    return None


def channel_logo(channel: str) -> str:
    """Logo URL for a live-TV channel name (bundled iptv-org index)."""
    logos = _load_data("channel_logos.json")
    if not logos:
        return ""
    key = _norm_key(channel)
    if key in logos:
        return logos[key].get("l") or logos[key].get("logo") or ""
    # "beIN SPORTS 1 HD" → "bein sports 1"; "Dubai Sports 1 (HD)" → …
    stripped = re.sub(r"\s+(hd|fhd|uhd|sd|4k|\d{3,4}p?)$", "", key)
    for cand in (stripped, stripped.replace(" ", ""), key.replace(" ", "")):
        if cand in logos:
            return logos[cand].get("l") or logos[cand].get("logo") or ""
    # last resort: same name with a country suffix ("bein sports 1 fr")
    prefix = stripped + " "
    for k, v in logos.items():
        if k.startswith(prefix):
            url = v.get("l") or v.get("logo")
            if url:
                return url
    return ""


def _translate_cached(text: str, lang: str, cache: dict) -> str:
    """Translate one name, preferring curated data then a cached MT result."""
    if not text:
        return text
    if text in cache:
        return cache[text]
    club = _club_lookup(text, lang)
    if club:
        cache[text] = club
        return club
    if _ARABIC.search(text) and lang == "fr":
        # French names straight from English are usually correct for clubs.
        en = _translate_one(text, "en")
        if en and en.lower() not in _GENERIC_WORDS:
            club = _club_lookup(en, "fr")
            if club:
                cache[text] = club
                return club
    out = _translate_one(text, lang)
    if out and out.strip().lower() in _GENERIC_WORDS:
        # Literal word ("ليل" → "night"): keep the original Arabic name rather
        # than a wrong translation, and try the English reference instead.
        en = _translate_one(text, "en")
        if en and en.lower() not in _GENERIC_WORDS:
            club = _club_lookup(en, lang)
            if club:
                cache[text] = club
                return club
        return text
    cache[text] = out
    return out


def localize_events(events: list[MatchEvent], lang: str = "fr") -> list[MatchEvent]:
    """Translate Arabic team/league names to the UI language, with a cache.

    No hard-coded mapping: names change and lower leagues are unknown, so the
    translation is fetched on demand and cached per language.
    """
    lang = "fr" if str(lang).lower().startswith("fr") else "en"
    cache = _read_json(_translations_path(lang), {})
    if not isinstance(cache, dict):
        cache = {}
    names = set()
    for ev in events:
        names.update((ev.home, ev.away, ev.championship))
    # Explainable cache: only values PRODUCED BY THIS PIPELINE are trusted.
    # Older builds cached raw machine translations ("ليل" → "nuit"), which
    # would otherwise stay wrong forever.
    if not isinstance(cache.get("__v"), int) or cache.get("__v") != 2:
        cache = {"__v": 2}
    missing = [n for n in names if n and n not in cache]
    if missing:
        with ThreadPoolExecutor(max_workers=min(6, len(missing))) as pool:
            for src, dst in zip(missing, pool.map(
                    lambda n: _translate_cached(n, lang, cache), missing)):
                if dst and dst != src:
                    cache[src] = dst
        _write_json(_translations_path(lang), cache)
    return [replace(
        ev,
        home=cache.get(ev.home, ev.home),
        away=cache.get(ev.away, ev.away),
        championship=cache.get(ev.championship, ev.championship),
    ) for ev in events]

def is_fresh_cache(max_age: int = _CACHE_MAX_AGE) -> bool:
    blob = _read_json(_cache_dir() / _EVENTS_CACHE, {})
    try:
        return int(time.time()) - int(blob.get("fetched_at") or 0) <= max_age
    except Exception:
        return False
