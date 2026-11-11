"""Deezer source, using the public (unauthenticated) Deezer API.

Only public data is reachable: a private profile or playlist has to be made
public (Deezer > Settings / playlist options) for the time of the export.
"""

from __future__ import annotations

import argparse
import re
import time
from collections import deque
from datetime import datetime
from typing import Any, Iterator, Optional

import requests

from musixporter.console import info, warn
from musixporter.models import Album, Artist, Library, Playlist, Track
from musixporter.sources.base import Source, SourceError

API_BASE = "https://api.deezer.com"
# Deezer quota: 50 requests per 5 seconds (kept a little under).
RATE_LIMIT_CALLS = 45
RATE_LIMIT_PERIOD = 5.0
QUOTA_ERROR_CODE = 4
PAGE_SIZE = 100


def parse_deezer_id(value: str, kind: str) -> str:
    """Accept a bare id or a Deezer URL (``.../playlist/123``, ``.../profile/123``)."""
    value = str(value).strip()
    if value.isdigit():
        return value
    m = re.search(rf"/{kind}/(\d+)", value)
    if not m:
        raise SourceError(f"'{value}' is not a Deezer {kind} id or URL")
    return m.group(1)


def _parse_date(value: Any) -> int:
    """Deezer gives either epoch seconds or 'YYYY-MM-DD HH:MM:SS'."""
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").timestamp())
    except ValueError:
        return 0


class DeezerClient:
    """Minimal rate-limited client for the public Deezer API."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self._calls: deque[float] = deque()

    def _throttle(self) -> None:
        now = time.monotonic()
        while self._calls and now - self._calls[0] >= RATE_LIMIT_PERIOD:
            self._calls.popleft()
        if len(self._calls) >= RATE_LIMIT_CALLS:
            time.sleep(RATE_LIMIT_PERIOD - (now - self._calls[0]))
        self._calls.append(time.monotonic())

    def get(self, url: str, **params: Any) -> dict:
        if not url.startswith("http"):
            url = f"{API_BASE}/{url.lstrip('/')}"
        for attempt in range(5):
            self._throttle()
            try:
                r = self.session.get(url, params=params or None, timeout=20)
                r.raise_for_status()
                data = r.json()
            except (requests.RequestException, ValueError) as e:
                if attempt == 4:
                    raise SourceError(f"Deezer request failed: {e}") from e
                time.sleep(1 + attempt)
                continue
            err = data.get("error") if isinstance(data, dict) else None
            if not err:
                return data
            if err.get("code") == QUOTA_ERROR_CODE and attempt < 4:
                time.sleep(RATE_LIMIT_PERIOD)
                continue
            raise SourceError(
                f"Deezer: {err.get('message', err)} ({url.replace(API_BASE, '')}): "
                "wrong id, or private data?"
            )
        raise SourceError("Deezer request failed")  # pragma: no cover

    def get_all(self, path: str) -> Iterator[dict]:
        """Iterate over every item of a paginated collection."""
        page = self.get(path, limit=PAGE_SIZE)
        while True:
            yield from page.get("data", [])
            nxt = page.get("next")
            if not nxt:
                return
            page = self.get(nxt)


class DeezerSource(Source):
    name = "deezer"
    help = "public Deezer profile and/or playlists"

    def __init__(
        self,
        user_id: Optional[str] = None,
        playlist_ids: Optional[list[str]] = None,
        client: Optional[DeezerClient] = None,
    ):
        if not user_id and not playlist_ids:
            raise SourceError("Deezer: provide --user and/or --playlist-id")
        self.user_id = parse_deezer_id(user_id, "profile") if user_id else None
        self.playlist_ids = [parse_deezer_id(p, "playlist") for p in playlist_ids or []]
        self.client = client or DeezerClient()

    # -- CLI ---------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-u", "--user", dest="user_id", metavar="ID",
            help="user id or profile URL: exports favorite tracks, albums, "
            "artists and playlists (they must be public)",
        )
        parser.add_argument(
            "-p", "--playlist-id", "--playlist", dest="playlist_ids",
            action="append", metavar="ID",
            help="public playlist id or URL (can be repeated)",
        )

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "DeezerSource":
        return cls(user_id=args.user_id, playlist_ids=args.playlist_ids)

    # -- Fetching ----------------------------------------------------------

    def fetch(self) -> Library:
        library = Library()
        if self.user_id:
            library.merge(self._fetch_user(self.user_id))
        for playlist_id in self.playlist_ids:
            meta = self.client.get(f"playlist/{playlist_id}")
            library.playlists.append(self._fetch_playlist(meta))
        return library

    def _fetch_user(self, user_id: str) -> Library:
        user = self.client.get(f"user/{user_id}")
        info(f"[Deezer] Profile: {user.get('name')} (id {user_id})")
        library = Library()

        playlists = self._safe_list(f"user/{user_id}/playlists", "playlists")
        loved = next((p for p in playlists if p.get("is_loved_track")), None)

        # Favorite tracks are read through the "loved tracks" playlist when it
        # exists: unlike /user/{id}/tracks it gives the ISRC of each track.
        if loved:
            library.tracks = self._fetch_playlist(loved, label="Favorite tracks").tracks
        else:
            raw = self._safe_list(f"user/{user_id}/tracks", "favorite tracks")
            library.tracks = [self._track(t) for t in raw]
            info(f"[Deezer] Favorite tracks: {len(library.tracks)}")

        library.albums = [
            self._album(a) for a in self._safe_list(f"user/{user_id}/albums", "albums")
        ]
        info(f"[Deezer] Favorite albums: {len(library.albums)}")
        library.artists = [
            Artist(name=a.get("name") or "", id=a.get("id"), date_add=_parse_date(a.get("time_add")))
            for a in self._safe_list(f"user/{user_id}/artists", "artists")
        ]
        info(f"[Deezer] Favorite artists: {len(library.artists)}")

        for meta in playlists:
            if meta is not loved:
                library.playlists.append(self._fetch_playlist(meta))
        return library

    def _safe_list(self, path: str, what: str) -> list[dict]:
        try:
            return list(self.client.get_all(path))
        except SourceError as e:
            warn(f"[Deezer] Could not fetch {what}: {e}")
            return []

    def _fetch_playlist(self, meta: dict, label: Optional[str] = None) -> Playlist:
        title = meta.get("title") or str(meta.get("id"))
        try:
            tracks = [self._track(t) for t in self.client.get_all(f"playlist/{meta['id']}/tracks")]
        except SourceError as e:
            warn(f"[Deezer] Could not fetch tracks of playlist '{title}': {e}")
            tracks = []
        info(f"[Deezer] {label or f'Playlist {title!r}'}: {len(tracks)} tracks")
        return Playlist(
            id=meta.get("id"),
            title=title,
            description=meta.get("description") or "",
            creation_date=_parse_date(meta.get("creation_date")),
            tracks=tracks,
        )

    # -- Normalization -----------------------------------------------------

    @staticmethod
    def _track(t: dict) -> Track:
        artist = t.get("artist") or {}
        album = t.get("album") or {}
        return Track(
            id=t.get("id"),
            title=t.get("title") or "",
            artists=[Artist(name=artist.get("name") or "", id=artist.get("id"))],
            duration=int(t.get("duration") or 0),
            isrc=t.get("isrc") or None,
            album=Album(title=album.get("title") or "", id=album.get("id")) if album else None,
            explicit=bool(t.get("explicit_lyrics")),
            date_add=_parse_date(t.get("time_add")),
        )

    @staticmethod
    def _album(a: dict) -> Album:
        artist = a.get("artist") or {}
        return Album(
            id=a.get("id"),
            title=a.get("title") or "",
            artist=Artist(name=artist.get("name") or "", id=artist.get("id")),
            release_date=a.get("release_date"),
            nb_tracks=a.get("nb_tracks"),
            date_add=_parse_date(a.get("time_add")),
        )
