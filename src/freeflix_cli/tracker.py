import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from platformdirs import user_data_dir
from urllib.parse import urlparse


class ProgressTracker:
    def __init__(self):
        self.app_name = "AutoFlixCLI"
        self.app_author = "PaulExplorer"
        self.data_dir = Path(user_data_dir(self.app_name, self.app_author))
        self.data_file = self.data_dir / "progress.json"

        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        """Load progress data from JSON file."""
        if not self.data_file.exists():
            return {}

        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_data(self):
        """Save progress data to JSON file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except OSError as e:
            print(f"Warning: Could not save progress: {e}")

    def _to_relative(self, url: str) -> str:
        """Convert an absolute URL to a relative path."""
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            # Only convert standard web URLs to relative paths.
            # Custom schemes like 'anilist:', 'tmdb:', 'imdb:' should be kept as is.
            if parsed.scheme in ["http", "https"]:
                path = parsed.path
                if parsed.query:
                    path += "?" + parsed.query
                return path
            return url  # Keep custom schemes or relative paths as is
        except Exception:
            return url

    def save_progress(
        self,
        provider: str,
        series_title: str,
        season_title: str,
        episode_title: str,
        series_url: str,
        season_url: str,
        episode_url: str,
        logo_url: Optional[str] = None,
    ):
        """
        Save the progress for a specific episode.

        Args:
            provider: The name of the provider (e.g., 'Anime-Sama').
            series_title: Title of the series.
            season_title: Title of the season.
            episode_title: Title of the episode (e.g., 'Episode 1').
            series_url: URL of the series page.
            season_url: URL of the season page.
            episode_url: URL of the episode page or player.
            logo_url: Optional URL for the series cover image.
        """
        if "history" not in self.data:
            self.data["history"] = {}

        # Convert URLs to relative paths (except logo which is external)
        series_rel = self._to_relative(series_url)
        season_rel = self._to_relative(season_url)
        episode_rel = self._to_relative(episode_url)

        # Update specific series progress
        key = f"{provider}|{series_title}"
        entry = {
            "provider": provider,
            "series_title": series_title,
            "season_title": season_title,
            "episode_title": episode_title,
            "series_url": series_rel,
            "season_url": season_rel,
            "episode_url": episode_rel,
            "last_watched": datetime.now().isoformat(),
            "logo_url": logo_url,
        }
        self.data["history"][key] = entry

        # Update last global watched for "Quick Resume"
        self.data["last_watched_global"] = entry

        self._save_data()

    def get_last_global(self) -> Optional[Dict[str, Any]]:
        """Get the absolute last thing watched."""
        return self.data.get("last_watched_global")

    def get_series_progress(
        self, provider: str, series_title: str
    ) -> Optional[Dict[str, Any]]:
        """Get the last progress for a specific series."""
        if "history" not in self.data:
            return None
        return self.data["history"].get(f"{provider}|{series_title}")

    def get_history(self) -> list[Dict[str, Any]]:
        """Get all history entries sorted by last_watched (descending)."""
        if "history" not in self.data:
            return []

        entries = list(self.data["history"].values())
        # Parse date and sort
        entries.sort(
            key=lambda x: datetime.fromisoformat(x["last_watched"]), reverse=True
        )
        return entries

    def delete_history_item(self, provider: str, series_title: str):
        """Delete a specific history entry."""
        if "history" not in self.data:
            return

        key = f"{provider}|{series_title}"
        if key in self.data["history"]:
            del self.data["history"][key]

            # If this was the last global watched, we might want to clear it or find the next one
            # For simplicity, we just check if it matches and clear it
            last_global = self.data.get("last_watched_global")
            if (
                last_global
                and last_global.get("provider") == provider
                and last_global.get("series_title") == series_title
            ):
                self.data["last_watched_global"] = None

            self._save_data()

    # --- AniList Integration ---

    def get_anilist_token(self) -> Optional[str]:
        """Get the stored AniList token."""
        return self.data.get("anilist_token")

    def set_anilist_token(self, token: str):
        """Save the AniList token."""
        self.data["anilist_token"] = token
        self._save_data()

    # --- Language Preferences ---

    def get_language(self) -> Optional[str]:
        return self.data.get("language")

    def set_language(self, lang_code: str):
        self.data["language"] = lang_code
        self._save_data()

    # Anime content language ('fr' = VF/VOSTFR sources, 'en' = VO/sub
    # sources). Chosen first on the very first launch, before the
    # interface language, and used to filter the anime sources.
    def get_anime_language(self) -> Optional[str]:
        return self.data.get("anime_language")

    def set_anime_language(self, lang_code: str):
        self.data["anime_language"] = lang_code
        self._save_data()

    # Poster display mode for anime covers in the terminal (via chafa) :
    #   "auto"  → chafa picks the best format the terminal supports
    #   "sixel" → force sixel (photo quality ; needs Konsole Sixel enabled)
    #   "off"   → never draw posters
    def get_poster_mode(self) -> str:
        return self.data.get("poster_mode", "auto")

    def set_poster_mode(self, mode: str):
        self.data["poster_mode"] = mode
        self._save_data()

    # --- Player Preferences ---

    def get_player(self) -> Optional[str]:
        return self.data.get("player")

    def set_player(self, player_code: str):
        self.data["player"] = player_code
        self._save_data()

    # --- Theme preference ---

    def get_theme(self) -> str:
        return self.data.get("theme", "default")

    def set_theme(self, name: str):
        self.data["theme"] = name
        self._save_data()

    # --- Watch stats (episodes/day, by provider, by genre) ---

    def record_watch(self, provider: str, series_title: str, genres=None):
        """Append a lightweight watch event for the stats dashboard."""
        if "watch_events" not in self.data:
            self.data["watch_events"] = []
        self.data["watch_events"].append(
            {
                "ts": datetime.now().isoformat(),
                "provider": provider,
                "series": series_title,
                "genres": list(genres) if genres else [],
            }
        )
        # Keep the log bounded (last 5000 events is plenty).
        if len(self.data["watch_events"]) > 5000:
            self.data["watch_events"] = self.data["watch_events"][-5000:]
        self._save_data()

    def get_stats(self) -> Dict[str, Any]:
        """Compute aggregate viewing stats from the watch event log."""
        events = self.data.get("watch_events", [])
        total = len(events)
        stats = {
            "total": total,
            "today": 0,
            "this_week": 0,
            "this_month": 0,
            "by_provider": {},
            "by_genre": {},
            "by_day": {},
            "top_series": {},
            "streak": 0,
        }
        if not events:
            return stats

        now = datetime.now()
        today = now.date()
        days_seen = set()

        for e in events:
            try:
                ts = datetime.fromisoformat(e["ts"])
            except (KeyError, ValueError, TypeError):
                continue
            d = ts.date()
            days_seen.add(d)
            delta = (today - d).days
            if delta == 0:
                stats["today"] += 1
            if delta < 7:
                stats["this_week"] += 1
            if delta < 30:
                stats["this_month"] += 1

            prov = e.get("provider", "?")
            stats["by_provider"][prov] = stats["by_provider"].get(prov, 0) + 1
            for g in e.get("genres", []):
                g = g.strip()
                if g:
                    stats["by_genre"][g] = stats["by_genre"].get(g, 0) + 1
            ser = e.get("series", "?")
            stats["top_series"][ser] = stats["top_series"].get(ser, 0) + 1
            stats["by_day"][d.isoformat()] = stats["by_day"].get(d.isoformat(), 0) + 1

        # Current consecutive-day streak ending today (or yesterday).
        streak = 0
        from datetime import timedelta
        cur = today
        if cur not in days_seen:
            cur = today - timedelta(days=1)
        while cur in days_seen:
            streak += 1
            cur = cur - timedelta(days=1)
        stats["streak"] = streak
        return stats

    # --- Nvidia PRIME offload for hybrid Linux laptops ---

    def get_nvidia_offload(self) -> str:
        """One of 'auto' (detect via nvidia-smi), 'on', 'off'. Default: auto."""
        val = self.data.get("nvidia_offload", "auto")
        return val if val in ("auto", "on", "off") else "auto"

    def set_nvidia_offload(self, val: str):
        if val not in ("auto", "on", "off"):
            val = "auto"
        self.data["nvidia_offload"] = val
        self._save_data()

    # --- Parallel download workers (1..4) ---

    def get_parallel_downloads(self) -> int:
        try:
            n = int(self.data.get("parallel_downloads", 1))
        except (TypeError, ValueError):
            n = 1
        return max(1, min(4, n))

    def set_parallel_downloads(self, n: int):
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 1
        self.data["parallel_downloads"] = max(1, min(4, n))
        self._save_data()

    # --- OpenSubtitles API Key (free, requires registration at opensubtitles.com) ---

    def get_opensubtitles_key(self) -> Optional[str]:
        return self.data.get("opensubtitles_api_key")

    def set_opensubtitles_key(self, key: str):
        self.data["opensubtitles_api_key"] = key
        self._save_data()

    # --- Download Quality Preference ---

    def get_download_quality(self) -> str:
        """One of: 'auto', '1080', '720', '480'. Defaults to 'auto'."""
        return self.data.get("download_quality", "auto")

    def set_download_quality(self, q: str):
        if q not in ("auto", "1080", "720", "480"):
            q = "auto"
        self.data["download_quality"] = q
        self._save_data()

    # --- Episode position (resume mid-episode) ---

    def get_episode_position(self, key: str) -> Optional[float]:
        positions = self.data.get("episode_positions", {})
        val = positions.get(key)
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def set_episode_position(self, key: str, seconds: float):
        if "episode_positions" not in self.data:
            self.data["episode_positions"] = {}
        self.data["episode_positions"][key] = float(seconds)
        self._save_data()

    def clear_episode_position(self, key: str):
        if "episode_positions" in self.data:
            self.data["episode_positions"].pop(key, None)
            self._save_data()

    # --- Portal URL Cache (avoids re-resolving on every launch) ---

    def get_portal_cache(self, name: str, ttl_hours: int = 24) -> Optional[str]:
        """Return a cached portal URL if still fresh, else None."""
        cache = self.data.get("portal_cache", {})
        entry = cache.get(name)
        if not entry:
            return None
        try:
            ts = datetime.fromisoformat(entry["ts"])
        except (KeyError, ValueError, TypeError):
            return None
        age_hours = (datetime.now() - ts).total_seconds() / 3600
        if age_hours > ttl_hours:
            return None
        return entry.get("url")

    def set_portal_cache(self, name: str, url: str):
        if "portal_cache" not in self.data:
            self.data["portal_cache"] = {}
        self.data["portal_cache"][name] = {
            "url": url,
            "ts": datetime.now().isoformat(),
        }
        self._save_data()

    def clear_portal_cache(self, name: Optional[str] = None):
        if "portal_cache" not in self.data:
            return
        if name is None:
            self.data["portal_cache"] = {}
        else:
            self.data["portal_cache"].pop(name, None)
        self._save_data()



    def get_anilist_mapping(
        self, provider: str, series_title: str, season_title: Optional[str] = None
    ) -> Optional[int]:
        """Get the AniList media ID for a given series and season."""
        if "anilist_mappings" not in self.data:
            return None

        # Try specific season mapping first if provided
        if season_title:
            key = f"{provider}|{series_title}|{season_title}"
            if key in self.data["anilist_mappings"]:
                return self.data["anilist_mappings"][key]

        # Fallback to series-only mapping (legacy support or if no season provided)
        # However, for fixing the bug, we might want to be stricter?
        # Let's keep fallback only if season_title is NOT provided.
        if not season_title:
            key = f"{provider}|{series_title}"
            return self.data["anilist_mappings"].get(key)

        return None

    def set_anilist_mapping(
        self,
        provider: str,
        series_title: str,
        media_id: int,
        season_title: Optional[str] = None,
    ):
        """Save the mapping between a series and an AniList media ID."""
        if "anilist_mappings" not in self.data:
            self.data["anilist_mappings"] = {}

        if season_title:
            key = f"{provider}|{series_title}|{season_title}"
        else:
            key = f"{provider}|{series_title}"

        self.data["anilist_mappings"][key] = media_id
        self._save_data()


# Global instance
tracker = ProgressTracker()
