"""YouTube Music source adapter.

This module provides `YouTubeMusicSource`, an `InputSource` implementation
that fetches public or (optionally) authenticated YouTube Music data using
`ytmusicapi` and normalizes it to the internal schema expected by converters.

Usage notes:
- Install dependency: `pip install ytmusicapi`
- For accessing a user's private library (liked songs / library playlists),
  create an `headers_auth.json` file as explained in ytmusicapi docs and pass
  its path to `YouTubeMusicSource(auth_headers_path=...)`.
"""

from typing import Optional, Dict, Any, List
from musixporter.interfaces import InputSource

try:
    from ytmusicapi import YTMusic
except Exception:
    YTMusic = None


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
    def __init__(self, auth_headers_path: Optional[str] = None):
        self.auth_headers_path = auth_headers_path
        self.client = None

    def authenticate(self):
        if YTMusic is None:
            raise RuntimeError(
                "ytmusicapi is not installed. Run 'pip install ytmusicapi'."
            )
        if self.auth_headers_path:
            self.client = YTMusic(self.auth_headers_path)
        else:
            # Unauthenticated client still supports public search and some reads
            self.client = YTMusic()

    def fetch_data(self) -> Dict[str, Any]:
        """Fetch a minimal dataset and return normalized dict.

        This implementation focuses on liked songs and playlists as an example.
        It returns a dict with keys: `tracks`, `albums`, `artists`, `user_playlists`.
        Converters expect track dicts to contain at least `title`, `duration`,
        and either `artist` or `artists`.
        """
        if self.client is None:
            self.authenticate()

        result = {
            "tracks": [],
            "albums": [],
            "artists": [],
            "user_playlists": [],
        }

        # 1) Liked songs (example)
        try:
            liked = self.client.get_liked_songs(limit=100)
            for it in liked.get("tracks", [])[:500]:
                artists = it.get("artists") or []
                artist_name = artists[0].get("name") if artists else "Unknown"
                track = {
                    "id": it.get("videoId") or it.get("playlistItemId") or 0,
                    "title": it.get("title", ""),
                    "duration": _parse_duration(it.get("length")),
                    "artist": {"id": 0, "name": artist_name},
                    "date_add": None,
                }
                result["tracks"].append(track)
        except Exception:
            # If liked songs not available or auth missing, skip silently
            pass

        # 2) Playlists (user library playlists)
        try:
            pls = self.client.get_library_playlists(limit=50)
            for pl in pls:
                pl_id = pl.get("playlistId")
                pl_title = pl.get("title")
                # fetch playlist tracks (first 200)
                pl_items = []
                try:
                    items = self.client.get_playlist(pl_id, limit=200)
                    for it in items.get("tracks", []):
                        artists = it.get("artists") or []
                        artist_name = (
                            artists[0].get("name") if artists else "Unknown"
                        )
                        pl_items.append(
                            {
                                "id": it.get("videoId") or 0,
                                "title": it.get("title", ""),
                                "duration": _parse_duration(it.get("length")),
                                "artist": {"id": 0, "name": artist_name},
                                "date_add": None,
                            }
                        )
                except Exception:
                    pl_items = []

                result["user_playlists"].append(
                    {"id": pl_id, "title": pl_title, "tracks": pl_items}
                )
        except Exception:
            pass

        # Note: Albums & artists can be implemented using search and browse endpoints
        # if you need them. For most converters `tracks` + `user_playlists` is enough.

        return result
