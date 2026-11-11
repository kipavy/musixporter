"""Service-agnostic data model shared by sources, the Tidal mapper and formatters.

Sources produce a ``Library`` describing what the user has on the source
service; the mapper produces a new ``Library`` whose ids are Tidal ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

Id = Union[int, str]


@dataclass
class Artist:
    name: str
    id: Optional[Id] = None
    picture: Optional[str] = None
    date_add: int = 0  # epoch seconds, 0 = unknown


@dataclass
class Album:
    title: str
    artist: Optional[Artist] = None
    id: Optional[Id] = None
    cover: Optional[str] = None
    release_date: Optional[str] = None
    nb_tracks: Optional[int] = None
    explicit: bool = False
    date_add: int = 0


@dataclass
class Track:
    title: str
    artists: list[Artist] = field(default_factory=list)
    duration: int = 0  # seconds, 0 = unknown
    id: Optional[Id] = None
    isrc: Optional[str] = None
    album: Optional[Album] = None
    explicit: bool = False
    version: Optional[str] = None
    stream_start_date: Optional[str] = None
    date_add: int = 0

    @property
    def artist_name(self) -> str:
        return self.artists[0].name if self.artists else ""


@dataclass
class Playlist:
    title: str
    tracks: list[Track] = field(default_factory=list)
    id: Optional[Id] = None
    description: str = ""
    creation_date: int = 0


@dataclass
class Library:
    tracks: list[Track] = field(default_factory=list)
    albums: list[Album] = field(default_factory=list)
    artists: list[Artist] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.tracks or self.albums or self.artists or self.playlists)

    def merge(self, other: "Library") -> None:
        self.tracks.extend(other.tracks)
        self.albums.extend(other.albums)
        self.artists.extend(other.artists)
        self.playlists.extend(other.playlists)
