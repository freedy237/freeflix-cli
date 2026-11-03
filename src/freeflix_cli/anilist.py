from curl_cffi import requests
from typing import Optional, Dict, Any, List

from .i18n import t


class AniListClient:
    def __init__(self, token: Optional[str] = None):
        self.url = "https://graphql.anilist.co"
        self.token = token
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Last HTTP status (0 = network/other failure). Used to tell a dead
        # token (401/400 "Invalid token") from a real outage, so the UI shows
        # ONE actionable message instead of a raw "404/401" dump.
        self.last_status = 0
        self.last_error = ""
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def set_token(self, token: str):
        """Set the authorization token."""
        self.token = token
        self.headers["Authorization"] = f"Bearer {token}"

    def _query(
        self, query: str, variables: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Send a GraphQL query to AniList.

        Retries transient failures (timeouts, 429, 5xx) with a short backoff;
        a 400 "Invalid token" / 401 is reported once, clearly, without a raw
        traceback. Returns None on any failure (callers already handle it).
        """
        import time as _t
        self.last_status = 0
        self.last_error = ""
        payload = {"query": query, "variables": variables}
        for attempt in range(3):
            try:
                response = requests.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=(10, 20),
                    impersonate="chrome",
                )
                self.last_status = response.status_code
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < 2:
                        _t.sleep(1.5 * (attempt + 1))
                        continue
                try:
                    data = response.json()
                except Exception:
                    data = None
                if isinstance(data, dict) and data.get("errors"):
                    msgs = [
                        str(e.get("message") or e)
                        for e in data["errors"] if isinstance(e, dict)
                    ] or [str(data["errors"])]
                    self.last_error = " · ".join(msgs)[:300]
                    status = 0
                    for e in data["errors"]:
                        if isinstance(e, dict) and e.get("status"):
                            status = int(e["status"])
                            break
                    if status:
                        self.last_status = status
                    # AniList reports an expired/revoked token as HTTP 400
                    # "Invalid token" (or 401). That is NOT a network outage:
                    # it needs a new token, so say so once — no retry.
                    if (status in (400, 401) or self.last_status in (401, 403)
                            or "invalid token" in self.last_error.lower()
                            or "unauthorized" in self.last_error.lower()):
                        print(t("AniList: your token is invalid or expired. "
                                "Settings → AniList → Change token."))
                        return None
                    print(f"{t('AniList API Error:')} {self.last_error}")
                    return None
                if response.status_code >= 400:
                    self.last_error = f"HTTP {response.status_code}"
                    if attempt < 2:
                        _t.sleep(1.5 * (attempt + 1))
                        continue
                    print(f"{t('AniList is unreachable right now:')} {self.last_error}")
                    return None
                return (data or {}).get("data")
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                if attempt < 2:
                    _t.sleep(1.5 * (attempt + 1))
                    continue
                print(f"{t('AniList is unreachable right now:')} {self.last_error}")
                return None
        return None

    def validate_token(self) -> Optional[Dict[str, Any]]:
        """Check if the current token is valid and return user info."""
        query = """
        query {
            Viewer {
                id
                name
                avatar {
                    large
                }
            }
        }
        """
        data = self._query(query)
        if data and data.get("Viewer"):
            return data["Viewer"]
        return None

    def search_media(self, search: str) -> List[Dict[str, Any]]:
        """Search for an anime/manga by title."""
        query = """
        query ($search: String) {
            Page(page: 1, perPage: 20) {
                media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
                    id
                    title {
                        romaji
                        english
                        native
                    }
                    coverImage {
                        medium
                        large
                        extraLarge
                    }
                    genres
                    format
                    episodes
                    status
                    seasonYear
                }
            }
        }
        """
        variables = {"search": search}
        # NOT cached: AniList must never answer a new query from the previous
        # one (that silently returned the wrong show's candidates).
        data = self._query(query, variables)
        if data and data.get("Page") and data.get("Page", {}).get("media"):
            return data["Page"]["media"]
        return []

    def trending(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Trending-now anime (no query needed) for the Latest view.

        Public data: never send the (possibly dead) user token here, otherwise
        an expired token would also hide the home's new-releases feed.
        """
        query = """
        query {
            Page(page: 1, perPage: %d) {
                media(type: ANIME, sort: TRENDING_DESC) {
                    id
                    title {
                        romaji
                        english
                        native
                    }
                    coverImage {
                        medium
                        large
                        extraLarge
                    }
                    genres
                    format
                    episodes
                    status
                    seasonYear
                }
            }
        }
        """ % max(1, min(25, limit))
        saved = dict(self.headers)
        self.headers.pop("Authorization", None)
        try:
            data = self._query(query)
            if data and data.get("Page") and data.get("Page", {}).get("media"):
                return data["Page"]["media"]
        except Exception:
            pass
        finally:
            self.headers = saved
        return []



    def update_progress(self, media_id: int, progress: int) -> bool:
        """Update the progress for a media item. Also sets status to CURRENT if not already."""
        query = """
        mutation ($mediaId: Int, $progress: Int, $status: MediaListStatus) {
            SaveMediaListEntry(mediaId: $mediaId, progress: $progress, status: $status) {
                id
                progress
                status
            }
        }
        """
        # We enforce status to CURRENT whenever we update progress,
        # unless it's already completed (logic could be refined)
        variables = {"mediaId": media_id, "progress": progress, "status": "CURRENT"}
        data = self._query(query, variables)
        return data is not None and "SaveMediaListEntry" in data

    def get_user_watching(self, user_id: int) -> List[Dict[str, Any]]:
        """Get the user's current watching list."""
        query = """
        query ($userId: Int) {
            MediaListCollection(userId: $userId, type: ANIME, status: CURRENT, sort: UPDATED_TIME_DESC) {
                lists {
                    entries {
                        mediaId
                        progress
                        media {
                            title {
                                romaji
                                english
                            }
                            coverImage {
                                medium
                                large
                                extraLarge
                            }
                            format
                            episodes
                            seasonYear
                        }
                    }
                }
            }
        }
        """
        variables = {"userId": user_id}
        data = self._query(query, variables)
        if (
            data
            and data.get("MediaListCollection")
            and data["MediaListCollection"].get("lists")
        ):
            # Flatten lists (there should be only one for CURRENT usually, but structure is a list of lists)
            entries = []
            for lst in data["MediaListCollection"]["lists"]:
                entries.extend(lst.get("entries", []))
            return entries
        return []

    def get_media_with_relations(self, media_id: int) -> Optional[Dict[str, Any]]:
        """Get media details including episode count and relations (sequels)."""
        query = """
        query ($mediaId: Int) {
            Media(id: $mediaId) {
                id
                title {
                    romaji
                    english
                }
                episodes
                relations {
                    edges {
                        relationType
                        node {
                            id
                            title {
                                romaji
                                english
                            }
                            episodes
                            format
                        }
                    }
                }
            }
        }
        """
        variables = {"mediaId": media_id}
        data = self._query(query, variables)
        if data and data.get("Media"):
            return data["Media"]
        return None


# Global instance
anilist_client = AniListClient()
