"""Offline end-to-end tests: fake HTTP for Deezer, fake Tidal client."""

import json

import pytest

from musixporter import cli
from musixporter.formatters.monochrome import MonochromeFormatter
from musixporter.models import Album, Artist, Library, Playlist, Track
from musixporter.sources.base import SourceError
from musixporter.sources.deezer import DeezerClient, DeezerSource, parse_deezer_id
from musixporter.sources.ytmusic import YouTubeMusicSource, parse_playlist_id
from musixporter.tidal import TidalError, TidalMapper


def tidal_item(id, title, artist, duration=200, isrc=None):
    return {"id": id, "title": title, "duration": duration, "isrc": isrc, "explicit": False,
            "version": None, "streamStartDate": "2020-01-01T00:00:00.000+0000",
            "artists": [{"id": 7, "name": artist}],
            "album": {"id": 70, "title": "Album", "cover": "aaaa-bbbb", "releaseDate": "2020-01-01"}}


class FakeTidal:
    country_code = "FR"

    def __init__(self, fail=False):
        self.fail = fail
        self.catalog = [
            tidal_item(1, "Hey Jude", "The Beatles", 426, "GBUM71505902"),
            tidal_item(2, "Bohemian Rhapsody", "Queen", 355, "GBUM71029604"),
        ]

    def authenticate(self, force=False):
        pass

    def tracks_by_isrc(self, isrc):
        if self.fail:
            raise TidalError("boom")
        return [t for t in self.catalog if t["isrc"] == isrc]

    def search(self, query, kind="tracks", limit=10):
        if self.fail:
            raise TidalError("boom")
        q = query.lower()
        if kind == "tracks":
            return [t for t in self.catalog if t["title"].lower() in q]
        if kind == "albums":
            return [{"id": 70, "title": "Album", "artists": [{"id": 7, "name": "Queen"}],
                     "cover": "aaaa-bbbb", "numberOfTracks": 10}] if "album" in q else []
        return [{"id": 7, "name": "Queen", "picture": "pic-uuid"}] if "queen" in q else []


def sample_library():
    hey = Track(title="Hey Jude (Remastered 2015)", artists=[Artist("The Beatles")],
                duration=429, isrc="GBUM71505902", date_add=1700000000)
    queen = Track(title="Bohemian Rhapsody", artists=[Artist("Queen")], duration=354)
    unknown = Track(title="Nope", artists=[Artist("Nobody")])
    return Library(
        tracks=[hey, unknown],
        albums=[Album(title="Album", artist=Artist("Queen")), Album(title="Zzz", artist=Artist("Q"))],
        artists=[Artist("Queen"), Artist("Unknown Band")],
        playlists=[Playlist(id=5, title="Mix", tracks=[hey, queen, queen, unknown])],
    )


def test_mapper_maps_by_isrc_and_fuzzy_and_reports_misses():
    result = TidalMapper(FakeTidal(), workers=2).convert(sample_library())
    lib = result.library
    assert [t.id for t in lib.tracks] == [1]
    assert lib.tracks[0].date_add == 1700000000
    assert [t.id for t in lib.playlists[0].tracks] == [1, 2]  # duplicate removed
    assert [a.id for a in lib.albums] == [70]
    assert [(a.id, a.picture) for a in lib.artists] == [(7, "pic-uuid")]
    assert sorted((m.kind, m.title, m.context) for m in result.missed) == [
        ("album", "Zzz", "favorites"), ("artist", "Unknown Band", "favorites"),
        ("track", "Nope", "Mix"), ("track", "Nope", "favorites"),
    ]
    assert result.errors == 0


def test_mapper_surfaces_tidal_errors_instead_of_hiding_them():
    result = TidalMapper(FakeTidal(fail=True), workers=1).convert(sample_library())
    assert result.errors > 0
    assert all(m.reason.startswith("error: boom") for m in result.missed)
    assert result.library.tracks == []


def test_monochrome_format():
    result = TidalMapper(FakeTidal()).convert(sample_library())
    out = MonochromeFormatter().to_dict(result.library)
    assert set(out) == {"favorites_tracks", "favorites_albums", "favorites_artists",
                        "favorites_playlists", "user_playlists"}
    t = out["favorites_tracks"][0]
    assert t["id"] == 1 and t["addedAt"] == 1700000000000
    assert t["artists"] == [{"id": 7, "name": "The Beatles"}]
    assert t["album"]["cover"] == "aaaa-bbbb"
    pl = out["user_playlists"][0]
    assert pl["id"] == "musixporter-5" and pl["name"] == "Mix"
    assert pl["numberOfTracks"] == len(pl["tracks"]) == 2
    assert pl["images"] == ["aaaa-bbbb"]
    assert isinstance(pl["createdAt"], int)
    assert out["favorites_artists"] == [
        {"id": 7, "addedAt": out["favorites_artists"][0]["addedAt"], "name": "Queen", "picture": "pic-uuid"}]
    json.dumps(out)


# -- Deezer ------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeDeezerSession:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, params=None, timeout=None):
        path = url.replace("https://api.deezer.com/", "")
        return FakeResponse(self.routes.get(path, {"error": {"code": 800, "message": "no data"}}))


def dz_track(id, title, isrc=None):
    return {"id": id, "title": title, "duration": 100, "isrc": isrc, "explicit_lyrics": True,
            "time_add": 1600000000, "artist": {"id": 1, "name": "Art"},
            "album": {"id": 2, "title": "Alb"}}


def deezer_source(**kwargs):
    routes = {
        "user/42": {"id": 42, "name": "Jean"},
        "user/42/playlists": {"data": [
            {"id": 100, "title": "Loved", "is_loved_track": True},
            {"id": 101, "title": "Road trip", "creation_date": "2020-05-03 10:13:44"}]},
        "playlist/100/tracks": {"data": [dz_track(1, "A", "ISRC1")],
                                "next": "https://api.deezer.com/page2"},
        "page2": {"data": [dz_track(2, "B", "ISRC2")]},
        "playlist/101/tracks": {"data": [dz_track(3, "C")]},
        "playlist/101": {"id": 101, "title": "Road trip"},
        "user/42/albums": {"data": [{"id": 9, "title": "Alb", "artist": {"id": 1, "name": "Art"}}]},
        "user/42/artists": {"data": [{"id": 1, "name": "Art"}]},
    }
    return DeezerSource(client=DeezerClient(session=FakeDeezerSession(routes)), **kwargs)


def test_deezer_user_export_uses_loved_playlist_for_isrc_and_paginates():
    lib = deezer_source(user_id="https://www.deezer.com/fr/profile/42").fetch()
    assert [(t.title, t.isrc) for t in lib.tracks] == [("A", "ISRC1"), ("B", "ISRC2")]
    assert lib.tracks[0].explicit and lib.tracks[0].date_add == 1600000000
    assert [p.title for p in lib.playlists] == ["Road trip"]  # loved playlist not duplicated
    assert lib.playlists[0].creation_date > 0
    assert len(lib.albums) == 1 and len(lib.artists) == 1


def test_deezer_single_playlist_and_errors():
    lib = deezer_source(playlist_ids=["101"]).fetch()
    assert [t.title for t in lib.playlists[0].tracks] == ["C"]
    with pytest.raises(SourceError):
        deezer_source(user_id="7").fetch()  # unknown user: explicit error, not an empty export
    with pytest.raises(SourceError):
        DeezerSource()
    assert parse_deezer_id("https://www.deezer.com/fr/playlist/908622995?x=1", "playlist") == "908622995"
    with pytest.raises(SourceError):
        parse_deezer_id("abc", "playlist")


# -- YouTube Music -----------------------------------------------------------

class FakeYT:
    def get_playlist(self, playlist_id, limit=None):
        return {"title": f"PL {playlist_id}", "tracks": [
            {"videoId": "v1", "title": "Song", "artists": [{"name": "Art", "id": "c"}],
             "album": {"name": "Alb", "id": "a"}, "duration": "3:05", "isExplicit": True},
            {"videoId": "v2", "title": "Other", "artists": None, "album": None,
             "duration_seconds": 61},
            None]}

    def get_user(self, channel_id):
        return {"playlists": {"results": [{"playlistId": "P1", "title": "one"},
                                         {"playlistId": "P2", "title": "two"}]}}


def test_ytmusic_source():
    src = YouTubeMusicSource(
        playlist_ids=["https://music.youtube.com/playlist?list=P1"], user="UCx", client=FakeYT())
    lib = src.fetch()
    assert [p.id for p in lib.playlists] == ["P1", "P2"]  # P1 not fetched twice
    t1, t2 = lib.playlists[0].tracks
    assert (t1.title, t1.artist_name, t1.duration, t1.explicit, t1.album.title) == (
        "Song", "Art", 185, True, "Alb")
    assert (t2.artist_name, t2.duration, t2.album) == ("", 61, None)
    assert parse_playlist_id("PLabc") == "PLabc"
    with pytest.raises(SourceError):
        YouTubeMusicSource()


# -- CLI ---------------------------------------------------------------------

def test_cli_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.SOURCES["deezer"], "from_args",
                        classmethod(lambda cls, args: deezer_source(playlist_ids=args.playlist_ids)))
    monkeypatch.setattr(cli, "TidalClient", lambda country_code: FakeTidal())
    out = tmp_path / "out.json"
    assert cli.main(["deezer", "--playlist-id", "101", "-o", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["user_playlists"][0]["name"] == "Road trip"
    missed = list(tmp_path.glob("missed_tidal-*.json"))
    assert len(missed) == 1 and json.loads(missed[0].read_text())[0]["title"] == "C"


def test_cli_legacy_flags_and_bad_usage(capsys):
    args = cli.build_parser().parse_args(["ytmusic", "--yt-playlist", "X", "--yt-headers", "h.json"])
    assert args.playlist_ids == ["X"] and args.auth_headers_path == "h.json"
    args = cli.build_parser().parse_args(["deezer", "--user", "1", "--country", "us"])
    assert args.user_id == "1" and args.country == "us"
    assert cli.main(["deezer"]) == 2  # no id given
