"""Monochrome library backup format (Settings > import library).

Field names follow Monochrome's own export (``js/db.js``): dates are epoch
milliseconds, covers are Tidal image UUIDs, user playlists are keyed by ``id``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from musixporter.models import Album, Artist, Library, Playlist, Track


def _ms(epoch_seconds: int, default_ms: int) -> int:
    return int(epoch_seconds) * 1000 if epoch_seconds else default_ms


class MonochromeFormatter:
    def to_dict(self, library: Library) -> dict:
        now = int(time.time() * 1000)
        return {
            "favorites_tracks": [self._track(t, now) for t in library.tracks],
            "favorites_albums": [self._album(a, now) for a in library.albums],
            "favorites_artists": [self._artist(a, now) for a in library.artists],
            "favorites_playlists": [],
            "user_playlists": [self._playlist(p, now) for p in library.playlists],
        }

    def save(self, library: Library, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(library), f, indent=2, ensure_ascii=False)

    @staticmethod
    def _artist_ref(a: Artist) -> dict:
        return {"id": a.id, "name": a.name}

    def _track(self, t: Track, now: int) -> dict:
        artists = [self._artist_ref(a) for a in t.artists]
        return {
            "id": t.id,
            "addedAt": _ms(t.date_add, now),
            "title": t.title,
            "duration": t.duration,
            "explicit": t.explicit,
            "artist": artists[0] if artists else None,
            "artists": artists,
            "album": {
                "id": t.album.id,
                "title": t.album.title,
                "cover": t.album.cover,
                "releaseDate": t.album.release_date,
            }
            if t.album
            else None,
            "isrc": t.isrc,
            "version": t.version,
            "streamStartDate": t.stream_start_date,
        }

    def _album(self, a: Album, now: int) -> dict:
        return {
            "id": a.id,
            "addedAt": _ms(a.date_add, now),
            "title": a.title,
            "cover": a.cover,
            "releaseDate": a.release_date,
            "explicit": a.explicit,
            "artist": self._artist_ref(a.artist) if a.artist else None,
            "type": "ALBUM",
            "numberOfTracks": a.nb_tracks,
        }

    @staticmethod
    def _artist(a: Artist, now: int) -> dict:
        return {
            "id": a.id,
            "addedAt": _ms(a.date_add, now),
            "name": a.name,
            "picture": a.picture,
        }

    def _playlist(self, p: Playlist, now: int) -> dict:
        tracks = [self._track(t, now) for t in p.tracks]
        covers: list[str] = []
        for t in p.tracks:
            if t.album and t.album.cover and t.album.cover not in covers:
                covers.append(t.album.cover)
        created = _ms(p.creation_date, now)
        return {
            # Stable id: importing the same playlist again updates it
            # instead of creating a duplicate.
            "id": f"musixporter-{p.id}" if p.id else f"musixporter-{created}-{p.title}",
            "name": p.title,
            "tracks": tracks,
            "cover": "",
            "description": p.description,
            "createdAt": created,
            "updatedAt": now,
            "numberOfTracks": len(tracks),
            "images": covers[:4],
        }
