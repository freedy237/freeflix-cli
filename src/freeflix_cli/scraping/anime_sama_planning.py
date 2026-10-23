"""Anime-Sama weekly planning ("planning") scraper.

The planning is LIVE: Anime-Sama publishes a week grid at ``/planning`` and
updates it throughout the day. The server-rendered HTML is only a snapshot:
the site's own ``planning.js`` refreshes the real release state from
``/planning/sorties.php`` (upload timestamps per season link) every two
minutes. Reading only the HTML made a freshly uploaded episode stay "not yet
released" until the server snapshot changed — this module now applies the
same ``sorties.php`` logic.

Nothing here is hard-coded: every call fetches both documents fresh, so
entering the planning always shows the current release state. Posters are
cached separately by ``terminal_image`` and survive between visits.

Only ANIME cards are kept (``as-carte-anime``); scans/webtoons are dropped.
Each card exposes the exact fields we need as ``data-*`` attributes:
``data-nom``, ``data-url``, ``data-lien`` (season+language), ``data-img``,
``data-release-ts``, ``data-debut``, ``data-etat-db`` and the ``pl-sorti``
class.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, date

from . import anime_sama

_NO_CACHE = {"Cache-Control": "no-cache", "Pragma": "no-cache"}

_DAY_RE = re.compile(
    r'<div id="\d+"[^>]*class="[^"]*"[^>]*>\s*'
    r"<h2[^>]*>\s*(.*?)\s*</h2>\s*"
    r"<p[^>]*>\s*(\d{1,2}/\d{1,2})\s*</p>(.*?)(?=<div id=\"\d+\"|$)",
    re.S,
)
_CARD_RE = re.compile(
    r'<div class="([^"]*planning-card[^"]*)"([^>]*)>(.*?)</div>\s*(?=<div class="|$)',
    re.S,
)
_ATTR_RE = re.compile(r'data-([a-z-]+)="([^"]*)"')


class PlanningEntry:
    """One anime release in the weekly planning."""

    def __init__(self, title, url, season_url, img, day, date_label,
                 release_ts, started_ts, released, lang, link="", db_state=""):
        self.title = title            # display name
        self.url = url                # catalogue page
        self.season_url = season_url  # …/saisonN/vostfr/ (playable)
        self.img = img
        self.day = day                # localized day name (from the site)
        self.date_label = date_label  # "23/10"
        self.release_ts = release_ts
        self.started_ts = started_ts
        self.released = released      # "pl-sorti" → already out
        self.lang = lang              # "VOSTFR" / "VF" / ""
        self.link = link              # raw data-lien, key in sorties.php
        self.db_state = db_state      # "Reporté" / "Annulé" / ""

    @property
    def release_dt(self):
        try:
            return datetime.fromtimestamp(self.release_ts) if self.release_ts else None
        except (OverflowError, OSError, ValueError):
            return None

    @property
    def hour_label(self) -> str:
        dt = self.release_dt
        return dt.strftime("%H:%M") if dt else "?"

    @property
    def when_label(self) -> str:
        dt = self.release_dt
        if not dt:
            return self.date_label
        return f"{self.day} {self.date_label} · {dt:%H:%M}"

    @property
    def has_hour(self) -> bool:
        """False when the site hasn't announced a release time yet ("?")."""
        return self.release_dt is not None

    def __repr__(self):
        return f"PlanningEntry({self.title!r}, {self.when_label}, out={self.released})"


def _abs(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return anime_sama.website_origin.rstrip("/") + "/" + path.lstrip("/")


def parse_planning(html: str, lang_filter: str = "") -> list:
    """Parse the /planning page → list[PlanningEntry] (anime only)."""
    entries = []
    for day_name, date_label, block in _DAY_RE.findall(html or ""):
        day_name = re.sub(r"\s+", " ", day_name).strip()
        # Today's column sometimes ships pl-retard (late release).
        for cls, attrs, _inner in _CARD_RE.findall(block):
            if "as-carte-anime" not in cls:
                continue  # scans / webtoons are not animes
            d = dict(_ATTR_RE.findall(attrs))
            title = (d.get("nom") or d.get("title") or "").strip()
            url = _abs(d.get("url", ""))
            if not title or not url:
                continue
            lang = "VOSTFR" if "vostfr" in cls.lower() else (
                "VF" if re.search(r"\bvf\b", cls.lower()) else ""
            )
            if lang_filter and lang and lang != lang_filter:
                continue
            try:
                ts = int(d.get("release-ts") or 0)
            except ValueError:
                ts = 0
            # Some cards have no release-ts yet; fall back to their own
            # heure-ts before treating the hour as unknown.
            if not ts:
                try:
                    ts = int(d.get("heure-ts") or 0)
                except ValueError:
                    ts = 0
            try:
                debut = int(d.get("debut") or 0)
            except ValueError:
                debut = 0
            entries.append(PlanningEntry(
                title=title,
                url=url,
                season_url=_abs(d.get("lien", "")) or url,
                img=d.get("img", ""),
                day=day_name,
                date_label=date_label,
                release_ts=ts,
                started_ts=debut,
                released="pl-sorti" in cls,
                lang=lang,
                link=d.get("lien", ""),
                db_state=(d.get("etat-db") or "").strip(),
            ))
    return entries


def apply_release_status(entries, sorties) -> None:
    """Overlay the live ``sorties.php`` upload state on parsed entries.

    Anime-Sama marks a card "Sorti" when its season link appears in the upload
    tables with a timestamp >= ``data-debut`` (the planning day). The class in
    the HTML is only the server snapshot, so this is what actually flips a
    release that landed after the page was generated. Hand-edited states
    ("Reporté"/"Annulé") are never overridden, exactly like planning.js.
    """
    if not isinstance(sorties, dict):
        return
    for entry in entries:
        if entry.db_state in ("Reporté", "Annulé"):
            continue
        try:
            uploaded = int(sorties.get(entry.link) or 0)
        except (TypeError, ValueError):
            uploaded = 0
        if uploaded and uploaded >= (entry.started_ts or 0):
            entry.released = True


def _fetch_sorties() -> dict:
    """Live upload timestamps from the endpoint planning.js itself uses."""
    base = anime_sama.website_origin.rstrip("/")
    url = base + "/planning/sorties.php"
    resp = anime_sama._get(
        url, cache_ttl=0,
        headers={**_NO_CACHE, "Referer": base + "/planning"},
    )
    resp.raise_for_status()
    data = json.loads(resp.text or "{}")
    return data if isinstance(data, dict) else {}


def get_planning(lang_filter: str = ""):
    """Fetch the planning fresh, including the live release state.

    No HTTP cache here: the user asked that entering the planning always
    re-checks what is actually out. Poster files keep their own persistent
    cache, so a same-week grid still opens instantly.
    """
    anime_sama.get_website_url()
    base = anime_sama.website_origin.rstrip("/")
    page_url = base + "/planning"
    resp = anime_sama._get(
        page_url, cache_ttl=0,
        headers={**_NO_CACHE, "Referer": base + "/planning"},
    )
    resp.raise_for_status()
    entries = parse_planning(resp.text or "", lang_filter=lang_filter)
    try:
        apply_release_status(entries, _fetch_sorties())
    except Exception:
        # The grid itself is usable even if the live-status endpoint blips;
        # the server-rendered pl-sorti snapshot remains as a fallback.
        pass
    return entries


def group_by_day(entries) -> list:
    """[(day, date_label, [entries sorted by hour])] in the site's order."""
    order = []
    buckets = {}
    for e in entries:
        key = (e.day, e.date_label)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(e)
    out = []
    for key in order:
        items = sorted(buckets[key], key=lambda x: (x.release_ts or 0, x.title.lower()))
        out.append((key[0], key[1], items))
    return out


def today_index(entries) -> int:
    """Index of today's group (0-based), or 0."""
    today = date.today()
    for i, (_day, date_label, _items) in enumerate(group_by_day(entries)):
        try:
            d, m = date_label.split("/")
            if (int(d), int(m)) == (today.day, today.month):
                return i
        except ValueError:
            pass
    return 0
