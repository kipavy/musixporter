"""YouTube Music source (public playlists / channels, or an authenticated library)."""

from __future__ import annotations

import argparse
import re
from typing import Any, Optional

from musixporter.console import info, warn
from musixporter.models import Album, Artist, Library, Playlist, Track
from musixporter.sources.base import Source, SourceError


def parse_playlist_id(value: str) -> str:
    """Accept a bare playlist id or a YouTube (Music) URL containing ``list=``."""
    m = re.search(r"[?&]list=([\w-]+)", value)
    return m.group(1) if m else value.strip()


def parse_channel_id(value: str) -> str:
    """Accept a bare channel id or a ``.../channel/UC...`` URL."""
    m = re.search(r"/channel/([\w-]+)", value)
    return m.group(1) if m else value.strip()


def _parse_duration(text: Optional[str]) -> int:
    """'3:45' or '1:02:30' -> seconds."""
    seconds = 0
    try:
        for part in (text or "").split(":"):
            seconds = seconds * 60 + int(part)
    except ValueError:
        return 0
    return seconds


class YouTubeMusicSource(Source):
    name = "ytmusic"
    help = "YouTube Music playlists, channel, or authenticated library"

    def __init__(
        self,
        playlist_ids: Optional[list[str]] = None,
        user: Optional[str] = None,
        auth_headers_path: Optional[str] = None,
        client: Any = None,
    ):
        if not (playlist_ids or user or auth_headers_path):
            raise SourceError(
                "YouTube Music: provide --playlist, --user and/or --headers"
            )
        self.playlist_ids = [parse_playlist_id(p) for p in playlist_ids or []]
        self.user = parse_channel_id(user) if user else None
        self.auth_headers_path = auth_headers_path
        self._client = client

    # -- CLI ---------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-p", "--playlist", "--yt-playlist", dest="playlist_ids",
            action="append", metavar="ID",
            help="public/unlisted playlist id or URL (can be repeated)",
        )
        parser.add_argument(
            "-u", "--user", dest="user", metavar="CHANNEL_ID",
            help="channel id (UC...) or URL: exports its public playlists",
        )
        parser.add_argument(
            "--headers", "--yt-headers", dest="auth_headers_path", metavar="FILE",
            help="ytmusicapi browser.json auth file: also exports your liked "
            "songs and library playlists",
        )

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "YouTubeMusicSource":
        return cls(
            playlist_ids=args.playlist_ids,
            user=args.user,
            auth_headers_path=args.auth_headers_path,
        )

    # -- Fetching ----------------------------------------------------------

    @property
    def client(self):
        if self._client is None:
            from ytmusicapi import YTMusic

            try:
                self._client = YTMusic(self.auth_headers_path)
            except Exception as e:
                raise SourceError(f"YouTube Music: could not initialize client: {e}") from e
        return self._client

    def fetch(self) -> Library:
        library = Library()
        seen: set[str] = set()

        def add_playlist(playlist_id: Optional[str], title: Optional[str] = None) -> None:
            if not playlist_id or playlist_id in seen:
                return
            seen.add(playlist_id)
            playlist = self._fetch_playlist(playlist_id, title)
            if playlist:
                library.playlists.append(playlist)

        for playlist_id in self.playlist_ids:
            add_playlist(playlist_id)

        if self.user:
            for meta in self._list_user_playlists(self.user):
                add_playlist(meta.get("playlistId"), meta.get("title"))

        if self.auth_headers_path:
            try:
                liked = self.client.get_liked_songs(limit=None).get("tracks", [])
                library.tracks = self._tracks(liked)
                info(f"[YouTube] Liked songs: {len(library.tracks)}")
            except Exception as e:
                warn(f"[YouTube] Could not fetch liked songs: {e}")
            seen.update({"LM", "SE"})  # liked songs / episodes pseudo-playlists
            try:
                metas = self.client.get_library_playlists(limit=None)
            except Exception as e:
                warn(f"[YouTube] Could not fetch library playlists: {e}")
                metas = []
            for meta in metas:
                add_playlist(meta.get("playlistId"), meta.get("title"))

        return library

    def _list_user_playlists(self, channel_id: str) -> list[dict]:
        try:
            section = self.client.get_user(channel_id).get("playlists") or {}
            playlists = list(section.get("results") or [])
            if section.get("params"):  # more than the first page
                playlists = list(
                    self.client.get_user_playlists(channel_id, section["params"])
                ) or playlists
        except Exception as e:
            raise SourceError(f"YouTube Music: could not read channel {channel_id}: {e}") from e
        info(f"[YouTube] Channel {channel_id}: {len(playlists)} public playlists")
        return playlists

    def _fetch_playlist(self, playlist_id: str, title: Optional[str] = None) -> Optional[Playlist]:
        try:
            data = self.client.get_playlist(playlist_id, limit=None)
        except Exception as e:
            reason = str(e).splitlines()[0][:120] if str(e) else type(e).__name__
            warn(f"[YouTube] Could not fetch playlist {title or playlist_id} "
                 f"(missing or private?): {reason}")
            return None
        playlist = Playlist(
            id=playlist_id,
            title=data.get("title") or title or playlist_id,
            description=data.get("description") or "",
            tracks=self._tracks(data.get("tracks") or []),
        )
        info(f"[YouTube] Playlist {playlist.title!r}: {len(playlist.tracks)} tracks")
        return playlist

    # -- Normalization -----------------------------------------------------

    @classmethod
    def _tracks(cls, items: list[dict]) -> list[Track]:
        return [cls._track(it) for it in items if it and it.get("title")]

    @staticmethod
    def _track(it: dict) -> Track:
        album = it.get("album") or {}
        duration = it.get("duration_seconds") or _parse_duration(
            it.get("duration") or it.get("length")
        )
        return Track(
            id=it.get("videoId"),
            title=it.get("title") or "",
            artists=[
                Artist(name=a["name"], id=a.get("id"))
                for a in it.get("artists") or []
                if a.get("name")
            ],
            duration=int(duration or 0),
            album=Album(title=album["name"], id=album.get("id")) if album.get("name") else None,
            explicit=bool(it.get("isExplicit")),
        )
