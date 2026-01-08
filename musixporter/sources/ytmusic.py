"""YouTube Music source adapter.

This module provides `YouTubeMusicSource`, an `InputSource` implementation
that fetches public or (optionally) authenticated YouTube Music data using
`ytmusicapi` and normalizes it to the internal schema expected by converters.
"""

from typing import Optional, Dict, Any, List
from ytmusicapi import YTMusic

from musixporter.interfaces import InputSource
from musixporter.console import info, warn


def _parse_duration(dur_str: Optional[str]) -> int:
    """Convert duration like '3:45' or '1:02:30' to seconds."""
    if not dur_str:
        return 0
    parts = dur_str.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0

    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


class YouTubeMusicSource(InputSource):
    def __init__(
        self,
        auth_headers_path: Optional[str] = None,
        playlist_id: Optional[str] = None,
        user: Optional[str] = None,
    ):
        self.auth_headers_path = auth_headers_path
        self.playlist_id = playlist_id
        self.user = user
        self.client: Optional[YTMusic] = None

    def authenticate(self):
        self.client = YTMusic(self.auth_headers_path)
        info("[YouTube] Client initialized")

    # ----------------------------
    # Normalization (pure logic)
    # ----------------------------

    def _normalize_track(self, it: Dict[str, Any]) -> Dict[str, Any]:
        artists = it.get("artists") or []
        artist_name = artists[0].get("name") if artists else "Unknown"

        return {
            "id": it.get("videoId") or it.get("playlistItemId") or 0,
            "title": it.get("title", ""),
            "duration": _parse_duration(it.get("length")),
            "artist": {"id": 0, "name": artist_name},
            "date_add": None,
        }

    def _normalize_playlist(
        self,
        pl: Dict[str, Any],
        raw_tracks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "id": pl.get("playlistId"),
            "title": pl.get("title"),
            "tracks": [self._normalize_track(it) for it in raw_tracks],
            "creation_date": pl.get("published")
            or pl.get("publishedAt")
            or pl.get("lastUpdated")
            or 0,
        }

    # ----------------------------
    # Raw fetchers (API only)
    # ----------------------------

    def _fetch_raw_liked_tracks(self) -> List[Dict[str, Any]]:
        liked = self.client.get_liked_songs(limit=None)
        return liked.get("tracks", [])

    def _fetch_raw_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        items = self.client.get_playlist(playlist_id, limit=None)
        return items.get("tracks", [])

    def _fetch_raw_library_playlists(self) -> List[Dict[str, Any]]:
        return self.client.get_library_playlists(limit=50)

    def _fetch_raw_user_playlists(self) -> List[Dict[str, Any]]:
        if not self.user:
            return []

        user_info = self.client.get_user(self.user)
        result = user_info.get("playlists", {})
        playlists = result.get("results", [])
        params = result.get("params")

        if params:
            playlists.extend(
                self.client.get_user_playlists(self.user, params).get("results", [])
            )

        return playlists

    # ----------------------------
    # Orchestrators (IO + logging)
    # ----------------------------

    def _fetch_liked_tracks(self) -> List[Dict[str, Any]]:
        try:
            raw_tracks = self._fetch_raw_liked_tracks()
            return [self._normalize_track(it) for it in raw_tracks]
        except Exception as e:
            warn(f"Failed to fetch liked songs: {e}")
            return []

    def _fetch_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        try:
            items = self.client.get_playlist(playlist_id, limit=None)
            raw_tracks = items.get("tracks", [])

            playlist = {
                "id": playlist_id,
                "title": items.get("title", ""),
                "tracks": [self._normalize_track(it) for it in raw_tracks],
                "creation_date": items.get("published")
                or items.get("publishedAt")
                or 0,
            }

            info(
                f"[YouTube] Fetched public playlist {playlist_id}: "
                f"'{playlist['title']}' ({len(playlist['tracks'])} tracks)"
            )
            return playlist

        except Exception as e:
            warn(f"Failed to fetch playlist {playlist_id}: {e}")
            return None

    def _fetch_library_playlists(self) -> List[Dict[str, Any]]:
        out = []

        try:
            playlists = self._fetch_raw_library_playlists()
            info(f"[YouTube] Found {len(playlists)} library playlists")
        except Exception as e:
            warn(f"Failed to fetch library playlists: {e}")
            return out

        for pl in playlists:
            pl_id = pl.get("playlistId")
            pl_title = pl.get("title")

            try:
                raw_tracks = self._fetch_raw_playlist_tracks(pl_id)
                playlist = self._normalize_playlist(pl, raw_tracks)
                info(
                    f"[YouTube] Library playlist '{pl_title}' ({pl_id}): "
                    f"{len(playlist['tracks'])} tracks fetched"
                )
            except Exception as e:
                warn(f"Failed to fetch library playlist '{pl_title}': {e}")
                playlist = self._normalize_playlist(pl, [])

            out.append(playlist)

        return out

    def _fetch_user_playlists(self) -> List[Dict[str, Any]]:
        out = []

        try:
            playlists = self._fetch_raw_user_playlists()
        except Exception as e:
            warn(f"Failed to fetch user playlists metadata: {e}")
            return out

        for pl in playlists:
            pl_id = pl.get("playlistId")
            pl_title = pl.get("title")

            try:
                raw_tracks = self._fetch_raw_playlist_tracks(pl_id)
                playlist = self._normalize_playlist(pl, raw_tracks)
                info(
                    f"[YouTube] User playlist '{pl_title}' ({pl_id}): "
                    f"{len(playlist['tracks'])} tracks fetched"
                )
            except Exception as e:
                warn(f"Failed to fetch user playlist '{pl_title}': {e}")
                playlist = self._normalize_playlist(pl, [])

            out.append(playlist)

        return out

    # ----------------------------
    # Public API
    # ----------------------------

    def fetch_data(self) -> Dict[str, Any]:
        if self.client is None:
            self.authenticate()

        result = {
            "tracks": [],
            "albums": [],
            "artists": [],
            "user_playlists": [],
        }

        result["tracks"] = self._fetch_liked_tracks()

        if self.playlist_id:
            pl = self._fetch_playlist(self.playlist_id)
            if pl:
                result["user_playlists"].append(pl)

        result["user_playlists"].extend(self._fetch_library_playlists())
        result["user_playlists"].extend(self._fetch_user_playlists())

        return result
