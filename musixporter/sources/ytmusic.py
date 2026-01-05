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
from musixporter.console import info, warn

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
    def __init__(
        self,
        auth_headers_path: Optional[str] = None,
        playlist_id: Optional[str] = None,
    ):
        self.auth_headers_path = auth_headers_path
        self.playlist_id = playlist_id
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
        info("[YouTube] Client initialized")

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

        try:
            liked = self.client.get_liked_songs(limit=None)
            for it in liked.get("tracks", []):
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
            pass

        if self.playlist_id:
            try:
                items = self.client.get_playlist(self.playlist_id, limit=None)
                pl_items = []
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
                info(f"[YouTube] Fetched public playlist {self.playlist_id}: '{items.get('title','')}' ({len(pl_items)} tracks)")

                result["user_playlists"].append(
                    {
                        "id": self.playlist_id,
                        "title": items.get("title", ""),
                        "tracks": pl_items,
                        "creation_date": items.get("published")
                        or items.get("publishedAt")
                        or 0,
                    }
                )
            except Exception:
                pass

        try:
            pls = self.client.get_library_playlists(limit=50)
            info(f"[YouTube] Found {len(pls)} library playlists")
            for pl in pls:
                pl_id = pl.get("playlistId")
                pl_title = pl.get("title")
                pl_items = []
                try:
                    items = self.client.get_playlist(pl_id, limit=None)
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
                    info(f"[YouTube] Library playlist '{pl_title}' ({pl_id}): {len(pl_items)} tracks fetched")
                except Exception:
                    pl_items = []

                result["user_playlists"].append(
                    {
                        "id": pl_id,
                        "title": pl_title,
                        "tracks": pl_items,
                        "creation_date": pl.get("published")
                        or pl.get("publishedAt")
                        or pl.get("lastUpdated")
                        or 0,
                    }
                )
        except Exception:
            pass

        

        return result
