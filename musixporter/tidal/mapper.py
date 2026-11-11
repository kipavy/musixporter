"""Map a source ``Library`` to Tidal ids."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable, Hashable, Iterable, Optional, TypeVar

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
)

from musixporter.console import console
from musixporter.models import Album, Artist, Library, Playlist, Track
from musixporter.tidal import matching
from musixporter.tidal.client import TidalClient, TidalError

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class Miss:
    """A source item that could not be found on Tidal."""

    kind: str  # "track", "album" or "artist"
    title: str
    artist: str = ""
    context: str = ""  # "favorites" or the playlist title
    isrc: Optional[str] = None
    duration: int = 0
    best_score: float = 0.0
    reason: str = "no match"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConversionResult:
    library: Library
    missed: list[Miss] = field(default_factory=list)
    errors: int = 0


@dataclass
class _Outcome:
    item: Optional[object] = None
    score: float = 0.0
    error: Optional[str] = None


def tidal_track(item: dict) -> Track:
    album = item.get("album") or {}
    return Track(
        id=item["id"],
        title=item.get("title") or "",
        artists=[
            Artist(name=a.get("name") or "", id=a.get("id"))
            for a in item.get("artists") or ([item["artist"]] if item.get("artist") else [])
        ],
        duration=item.get("duration") or 0,
        isrc=item.get("isrc"),
        explicit=bool(item.get("explicit")),
        version=item.get("version"),
        stream_start_date=item.get("streamStartDate"),
        album=Album(
            id=album.get("id"),
            title=album.get("title") or "",
            cover=album.get("cover"),
            release_date=album.get("releaseDate"),
        )
        if album
        else None,
    )


def tidal_album(item: dict) -> Album:
    artists = item.get("artists") or ([item["artist"]] if item.get("artist") else [])
    return Album(
        id=item["id"],
        title=item.get("title") or "",
        artist=Artist(name=artists[0].get("name") or "", id=artists[0].get("id"))
        if artists
        else None,
        cover=item.get("cover"),
        release_date=item.get("releaseDate"),
        nb_tracks=item.get("numberOfTracks"),
        explicit=bool(item.get("explicit")),
    )


class TidalMapper:
    def __init__(self, client: Optional[TidalClient] = None, workers: int = 4):
        self.client = client or TidalClient()
        self.workers = max(1, workers)

    # -- Per-item resolution (each makes 1 to 3 Tidal requests) -------------

    def find_track(self, track: Track) -> _Outcome:
        try:
            if track.isrc:
                # Same ISRC = same recording: pick the release closest to the source.
                items = self.client.tracks_by_isrc(track.isrc)
                if items:
                    best, _ = matching.best_track(track, items)
                    return _Outcome(best or items[0], 1.0)
            best_item, best_score = None, 0.0
            for query in matching.track_queries(track):
                item, score = matching.best_track(track, self.client.search(query, "tracks"))
                if score > best_score:
                    best_item, best_score = item, score
                if best_score >= 0.95:
                    break
            if best_item and best_score >= matching.TRACK_THRESHOLD:
                return _Outcome(best_item, best_score)
            return _Outcome(None, best_score)
        except TidalError as e:
            return _Outcome(error=str(e))

    def find_album(self, album: Album) -> _Outcome:
        artist = album.artist.name if album.artist else ""
        try:
            items = self.client.search(f"{artist} {album.title}".strip(), "albums")
        except TidalError as e:
            return _Outcome(error=str(e))
        scored = [(matching.score_album(album, it), it) for it in items]
        score, item = max(scored, key=lambda s: s[0], default=(0.0, None))
        return _Outcome(item if score >= matching.ALBUM_THRESHOLD else None, score)

    def find_artist(self, artist: Artist) -> _Outcome:
        try:
            items = self.client.search(artist.name, "artists", limit=5)
        except TidalError as e:
            return _Outcome(error=str(e))
        scored = [(matching.score_artist(artist.name, it), it) for it in items]
        score, item = max(scored, key=lambda s: s[0], default=(0.0, None))
        return _Outcome(item if score >= matching.ARTIST_THRESHOLD else None, score)

    # -- Orchestration -----------------------------------------------------

    @staticmethod
    def _track_key(t: Track) -> Hashable:
        return ("isrc", t.isrc.upper()) if t.isrc else (t.title, t.artist_name, t.duration)

    def _resolve_all(
        self, label: str, items: Iterable[T], key: Callable[[T], Hashable],
        find: Callable[[T], _Outcome],
    ) -> dict[Hashable, _Outcome]:
        """Resolve unique items concurrently, with a progress bar."""
        unique: dict[Hashable, T] = {}
        for it in items:
            unique.setdefault(key(it), it)
        if not unique:
            return {}
        results: dict[Hashable, _Outcome] = {}
        with Progress(
            TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(),
            TimeRemainingColumn(), console=console,
        ) as progress, ThreadPoolExecutor(self.workers) as pool:
            task = progress.add_task(label, total=len(unique))

            def run(pair):
                k, it = pair
                outcome = find(it)
                progress.advance(task)
                return k, outcome

            for k, outcome in pool.map(run, unique.items()):
                results[k] = outcome
        return results

    def convert(self, source: Library) -> ConversionResult:
        self.client.authenticate()  # fail early (and loudly) if Tidal is unreachable
        result = ConversionResult(Library())
        out = result.library

        all_tracks = list(source.tracks)
        for pl in source.playlists:
            all_tracks.extend(pl.tracks)
        tracks = self._resolve_all("Matching tracks ", all_tracks, self._track_key, self.find_track)
        albums = self._resolve_all(
            "Matching albums ", source.albums,
            lambda a: (a.title, a.artist.name if a.artist else ""), self.find_album,
        )
        artists = self._resolve_all(
            "Matching artists", source.artists, lambda a: a.name, self.find_artist
        )
        result.errors = sum(1 for group in (tracks, albums, artists) for o in group.values() if o.error)

        def miss(kind: str, outcome: _Outcome, title: str, artist: str, context: str, **extra) -> None:
            result.missed.append(Miss(
                kind=kind, title=title, artist=artist, context=context,
                best_score=round(outcome.score, 2),
                reason=f"error: {outcome.error}" if outcome.error else "no match", **extra,
            ))

        def map_tracks(src_tracks: list[Track], context: str) -> list[Track]:
            mapped, seen = [], set()
            for t in src_tracks:
                outcome = tracks[self._track_key(t)]
                if outcome.item is None:
                    miss("track", outcome, t.title, t.artist_name, context,
                         isrc=t.isrc, duration=t.duration)
                    continue
                if outcome.item["id"] in seen:
                    continue  # duplicate inside the same list
                seen.add(outcome.item["id"])
                tt = tidal_track(outcome.item)
                tt.date_add = t.date_add
                mapped.append(tt)
            return mapped

        out.tracks = map_tracks(source.tracks, "favorites")

        seen_ids: set = set()
        for a in source.albums:
            artist = a.artist.name if a.artist else ""
            outcome = albums[(a.title, artist)]
            if outcome.item is None:
                miss("album", outcome, a.title, artist, "favorites")
            elif outcome.item["id"] not in seen_ids:
                seen_ids.add(outcome.item["id"])
                ta = tidal_album(outcome.item)
                ta.date_add = a.date_add
                out.albums.append(ta)

        seen_ids = set()
        for a in source.artists:
            outcome = artists[a.name]
            if outcome.item is None:
                miss("artist", outcome, a.name, a.name, "favorites")
            elif outcome.item["id"] not in seen_ids:
                seen_ids.add(outcome.item["id"])
                out.artists.append(Artist(
                    id=outcome.item["id"], name=outcome.item.get("name") or a.name,
                    picture=outcome.item.get("picture"), date_add=a.date_add,
                ))

        for pl in source.playlists:
            out.playlists.append(Playlist(
                id=pl.id, title=pl.title, description=pl.description,
                creation_date=pl.creation_date, tracks=map_tracks(pl.tracks, pl.title),
            ))
        return result
