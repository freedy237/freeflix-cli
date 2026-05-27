"""
OpenSubtitles.com REST API client.

Used as a fallback when a streaming source does not expose subtitles.
Requires a free API key from https://www.opensubtitles.com/en/consumers
which the user provides via the Settings menu (saved in tracker).
"""

import os
import re
import tempfile
from typing import Optional, List, Dict, Any
from curl_cffi import requests

from .tracker import tracker


API_BASE = "https://api.opensubtitles.com/api/v1"
DEFAULT_USER_AGENT = "FreeFlixCLI v0.5"


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Api-Key": api_key,
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _parse_episode_info(title: str) -> Dict[str, Any]:
    """
    Best-effort extraction of (series, season, episode) from a window title
    like "Naruto - Saison 1 - Episode 5".
    """
    s = re.search(r"(?:saison|season|s)[\s_-]*(\d+)", title, re.IGNORECASE)
    e = re.search(r"(?:episode|ep|e)[\s_-]*(\d+)", title, re.IGNORECASE)
    parts = re.split(r"\s+-\s+|\s+—\s+", title, maxsplit=1)
    series = parts[0].strip() if parts else title.strip()
    return {
        "series": series,
        "season": int(s.group(1)) if s else None,
        "episode": int(e.group(1)) if e else None,
    }


def search_subtitles(
    title: str, languages: str = "en"
) -> Optional[List[Dict[str, Any]]]:
    """
    Search OpenSubtitles for a matching subtitle file. Returns the raw
    list of results from the API, or None on error / no key configured.
    """
    api_key = tracker.get_opensubtitles_key()
    if not api_key:
        return None

    info = _parse_episode_info(title)
    params = {
        "query": info["series"],
        "languages": languages,
    }
    if info["season"] is not None:
        params["season_number"] = info["season"]
    if info["episode"] is not None:
        params["episode_number"] = info["episode"]

    try:
        r = requests.get(
            f"{API_BASE}/subtitles",
            params=params,
            headers=_headers(api_key),
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data") or []
    except Exception:
        return None


def download_subtitle(file_id: int) -> Optional[str]:
    """
    Request a download URL for a given subtitle file_id, fetch the file,
    save it to a temp .srt, and return the local path.
    Returns None on any failure.
    """
    api_key = tracker.get_opensubtitles_key()
    if not api_key:
        return None

    try:
        # Step 1 — ask OS for a download URL
        r = requests.post(
            f"{API_BASE}/download",
            json={"file_id": file_id},
            headers=_headers(api_key),
            timeout=15,
        )
        r.raise_for_status()
        info = r.json()
        link = info.get("link")
        if not link:
            return None

        # Step 2 — fetch the actual file
        r2 = requests.get(link, timeout=20)
        r2.raise_for_status()
        fd, path = tempfile.mkstemp(suffix=".srt", prefix="freeflix_os_")
        with os.fdopen(fd, "wb") as f:
            f.write(r2.content)
        return path
    except Exception:
        return None


def fetch_best_subtitle(title: str, languages: str = "en") -> Optional[str]:
    """
    Convenience: search + download the top match. Returns a local .srt
    path or None if nothing could be found.
    """
    results = search_subtitles(title, languages=languages)
    if not results:
        return None

    # First result is best per OS ranking. Make sure it has a downloadable file.
    for entry in results:
        files = (entry.get("attributes") or {}).get("files") or []
        for f in files:
            file_id = f.get("file_id")
            if file_id:
                local = download_subtitle(int(file_id))
                if local:
                    return local
    return None
