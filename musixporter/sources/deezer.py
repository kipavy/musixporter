from typing import Optional

import threading
import time

from musixporter.interfaces import InputSource
from musixporter.console import info, warn

import deezer

from limits import RateLimitItemPerSecond
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter


# Deezer API quota: 50 requests / 5 seconds.
# We use a moving-window limiter so we don't exceed this in any rolling 5s window.
_DEEZER_RATE_LIMIT_ITEM = RateLimitItemPerSecond(50, 5, namespace="DEEZER")
_DEEZER_RATE_LIMIT_STORAGE = MemoryStorage()
_DEEZER_RATE_LIMITER = MovingWindowRateLimiter(_DEEZER_RATE_LIMIT_STORAGE)
_DEEZER_RATE_LIMIT_LOCK = threading.Lock()


class DeezerUserSource(InputSource):
    """
    Deezer source backed by python-deezer.
    Authentication-free. Requires only a public user ID.
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
        playlist_id: Optional[str] = None,
    ):
        # If neither a user id nor a playlist id is provided, skip.
        if not user_id and not playlist_id:
            warn(
                "[Deezer] No user ID or playlist ID provided, skipping Deezer source."
            )

        self.user_id = user_id
        self.access_token = access_token
        self.playlist_id = playlist_id

        if not access_token:
            warn(
                "[Deezer] No access token provided: only public data can be fetched. "
                "If you want to include private playlists without authenticating, make them public."
            )

        self.client = deezer.Client(access_token=access_token)
        self._wrap_rate_limited_client()

    # -------------------------
    # Public API
    # -------------------------

    def authenticate(self):
        """
        No authentication needed, but we validate the user exists.
        """
        if not self.user_id:
            return

        info("[Deezer] Validating user…")
        try:
            self.user = self.client.get_user(self.user_id)
        except Exception as e:
            raise RuntimeError(f"Invalid Deezer user ID: {e}")

        info(
            f"[Deezer] Using public profile: {self.user.name} (ID: {self.user_id})"
        )

    def fetch_data(self) -> dict:
        if self.playlist_id:
            info("[Deezer] Fetching playlist…")
            playlist = self._fetch_playlist_by_id(self.playlist_id)

            info("[Deezer] Normalizing data…")

            playlists = [playlist] if playlist else []
            return {
                "tracks": [],
                "albums": [],
                "artists": [],
                "user_playlists": [self._normalize_playlist(p) for p in playlists],
            }

        if not self.user_id:
            return {
                "tracks": [],
                "albums": [],
                "artists": [],
                "user_playlists": [],
            }

        info("[Deezer] Fetching library…")

        tracks = self._fetch_favorite_tracks()
        albums = self._fetch_favorite_albums()
        artists = self._fetch_favorite_artists()
        playlists = self._fetch_user_playlists()

        info("[Deezer] Normalizing data…")

        return {
            "tracks": [self._normalize_track(t) for t in tracks],
            "albums": [self._normalize_album(a) for a in albums],
            "artists": [self._normalize_artist(a) for a in artists],
            "user_playlists": [self._normalize_playlist(p) for p in playlists],
        }

    # -------------------------
    # Rate limiting
    # -------------------------

    def _wait_for_deezer_quota(self, identifier: str = "deezer") -> None:
        """Blocks until we're allowed to perform one Deezer API call.

        Note: This guarantees rate-limiting only within the current Python process.
        """
        with _DEEZER_RATE_LIMIT_LOCK:
            # warned = False
            while not _DEEZER_RATE_LIMITER.hit(
                _DEEZER_RATE_LIMIT_ITEM, identifier
            ):
                window_stats = _DEEZER_RATE_LIMITER.get_window_stats(
                    _DEEZER_RATE_LIMIT_ITEM, identifier
                )
                sleep_seconds = (
                    max(0.0, window_stats.reset_time - time.time()) + 0.05
                )

                # if not warned:
                #     info(
                #         f"[Deezer] Rate limit reached, sleeping {sleep_seconds:.2f}s…"
                #     )
                #     warned = True

                time.sleep(sleep_seconds)

    def _wrap_rate_limited_client(self) -> None:
        """Wrap the underlying HTTP calls so *all* Deezer requests are rate-limited.

        This includes pagination and resource methods that call back into the client.
        """
        if getattr(self.client, "_musixporter_rate_limited", False):
            return

        original_request = self.client.request
        original_get = self.client.get

        def rate_limited_request(*args, **kwargs):
            self._wait_for_deezer_quota()
            return original_request(*args, **kwargs)

        def rate_limited_get(*args, **kwargs):
            self._wait_for_deezer_quota()
            return original_get(*args, **kwargs)

        self.client.request = rate_limited_request
        self.client.get = rate_limited_get
        self.client._musixporter_rate_limited = True

    # -------------------------
    # Fetchers
    # -------------------------

    def _fetch_favorite_tracks(self):
        info("   → Favorite tracks")
        try:
            return list(self.client.get_user_tracks(self.user_id))
        except Exception as e:
            warn(f"[Deezer] Failed to fetch favorite tracks: {e}")
            return []

    def _fetch_favorite_albums(self):
        info("   → Favorite albums")
        try:
            return list(self.client.get_user_albums(self.user_id))
        except Exception as e:
            warn(f"[Deezer] Failed to fetch albums: {e}")
            return []

    def _fetch_favorite_artists(self):
        info("   → Favorite artists")
        try:
            return list(self.client.get_user_artists(self.user_id))
        except Exception as e:
            warn(f"[Deezer] Failed to fetch artists: {e}")
            return []

    def _fetch_user_playlists(self):
        info("   → User playlists")
        playlists = []

        try:
            raw_playlists = self.user.get_playlists()
        except Exception as e:
            warn(f"[Deezer] Failed to fetch playlists: {e}")
            return playlists

        for pl in raw_playlists:
            try:
                tracks = list(pl.get_tracks())
            except Exception:
                tracks = []

            playlists.append(
                {
                    "id": pl.id,
                    "title": pl.title,
                    "creation_date": getattr(pl, "creation_date", 0),
                    "picture": pl.picture,
                    "tracks": tracks,
                }
            )

        return playlists

    def _fetch_playlist_by_id(self, playlist_id: str):
        info("   → Playlist")
        try:
            pl = self.client.get_playlist(playlist_id)
        except Exception as e:
            warn(f"[Deezer] Failed to fetch playlist {playlist_id}: {e}")
            return None

        try:
            tracks = list(pl.get_tracks())
        except Exception:
            tracks = []

        return {
            "id": getattr(pl, "id", playlist_id),
            "title": getattr(pl, "title", str(playlist_id)),
            "creation_date": getattr(pl, "creation_date", 0),
            "picture": getattr(pl, "picture", None),
            "tracks": tracks,
        }

    # -------------------------
    # Normalizers
    # -------------------------

    def _normalize_track(self, t):
        return {
            "id": t.id,
            "isrc": getattr(t, "isrc", None),
            "title": t.title,
            "duration": t.duration,
            "explicit": bool(t.explicit_lyrics),
            "version": "",
            "date_add": getattr(t, "time_add", 0),
            "artist": {
                "id": t.artist.id if t.artist else None,
                "name": t.artist.name if t.artist else None,
            },
            "album": {
                "id": t.album.id if t.album else None,
                "title": t.album.title if t.album else None,
                "cover": t.album.cover if t.album else None,
            },
        }

    def _normalize_album(self, a):
        return {
            "id": a.id,
            "title": a.title,
            "date_add": getattr(a, "time_add", 0),
            "release_date": a.release_date,
            "cover": a.cover,
            "artist": {
                "id": a.artist.id if a.artist else None,
                "name": a.artist.name if a.artist else None,
            },
            "nb_tracks": a.nb_tracks,
        }

    def _normalize_artist(self, a):
        return {
            "id": a.id,
            "name": a.name,
        }

    def _normalize_playlist(self, p):
        return {
            "id": p["id"],
            "title": p["title"],
            "creation_date": p["creation_date"],
            "cover": p["picture"],
            "tracks": [self._normalize_track(t) for t in p["tracks"]],
        }
