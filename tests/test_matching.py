from musixporter.models import Album, Artist, Track
from musixporter.tidal import matching as m


def cand(title, artist, duration=0, version=None, **extra):
    return {"id": 1, "title": title, "artists": [{"id": 9, "name": artist}],
            "duration": duration, "version": version, **extra}


def track(title, artist="", duration=0):
    return Track(title=title, artists=[Artist(artist)] if artist else [], duration=duration)


def test_normalize_strips_brackets_accents_and_punctuation():
    assert m.normalize("Hey Jude (Remastered 2015)") == "hey jude"
    assert m.normalize("Déjà Vu [Live]") == "deja vu"
    assert m.normalize("Stan feat. Dido") == "stan"
    assert m.normalize("S.A.T.O.") == "sato"


def test_normalize_keeps_non_latin_and_fully_bracketed_titles():
    assert m.normalize("Край") != ""
    assert m.normalize("Край") != m.normalize("夜に駆ける")
    assert m.normalize("(Everything I Do)") == "everything i do"


def test_exact_match_is_accepted():
    s = track("Bohemian Rhapsody", "Queen", 355)
    assert m.score_track(s, cand("Bohemian Rhapsody", "Queen", 355)) >= m.TRACK_THRESHOLD


def test_same_title_by_another_artist_is_rejected():
    s = track("Bohemian Rhapsody", "Queen", 355)
    assert m.score_track(s, cand("Bohemian Rhapsody", "Hit Tunes Karaoke", 355)) == 0


def test_different_title_is_rejected():
    s = track("Kashmir", "Led Zeppelin")
    assert m.score_track(s, cand("Black Dog (Remaster)", "Led Zeppelin")) == 0


def test_unwanted_variant_loses_against_plain_version():
    s = track("Ramble On", "Led Zeppelin", 275)
    plain = m.score_track(s, cand("Ramble On", "Led Zeppelin", 274))
    live = m.score_track(s, cand("Ramble On (Live: O2 Arena)", "Led Zeppelin", 345))
    karaoke = m.score_track(s, cand("Ramble On", "Led Zeppelin", 274, version="Karaoke Version"))
    assert plain > live and plain > karaoke
    assert live < m.TRACK_THRESHOLD


def test_studio_version_is_an_acceptable_fallback_for_live():
    s = track("Learn To Be Still (Live)", "The Eagles")
    studio = m.score_track(s, cand("Learn To Be Still", "Eagles"))
    live = m.score_track(s, cand("Learn To Be Still (Live)", "Eagles"))
    assert m.TRACK_THRESHOLD <= studio < live


def test_youtube_style_title_and_channel_names():
    s = track("Queen - Bohemian Rhapsody (Official Video Remastered)", "Queen Official", 359)
    assert m.score_track(s, cand("Bohemian Rhapsody", "Queen", 355)) >= m.TRACK_THRESHOLD
    assert m.artist_score(["Daft Punk - Topic"], ["Daft Punk"]) == 1.0
    assert m.artist_score(["QueenVEVO"], ["Queen"]) == 1.0


def test_album_prefixed_candidate_title():
    s = track("Ramble On (Remaster)", "Led Zeppelin", 275)
    c = cand("Led Zeppelin II - Ramble On (Remaster)", "Led Zeppelin", 274)
    assert m.score_track(s, c) >= m.TRACK_THRESHOLD


def test_unknown_artist_needs_a_strong_title_and_duration():
    s = track("Bohemian Rhapsody", duration=355)
    assert m.score_track(s, cand("Bohemian Rhapsody", "Queen", 355)) >= m.TRACK_THRESHOLD
    assert m.score_track(s, cand("Bohemian Rhapsody", "Queen", 200)) < m.TRACK_THRESHOLD


def test_best_track_picks_highest_score():
    s = track("Hey Jude (Remastered 2015)", "The Beatles", 429)
    items = [cand("Hey Jude", "The Beatles", 238) | {"id": 1},
             cand("Hey Jude", "The Beatles", 426, version="Remastered 2015") | {"id": 2}]
    item, score = m.best_track(s, items)
    assert item["id"] == 2 and score >= m.TRACK_THRESHOLD


def test_score_album():
    a = Album(title="Discovery", artist=Artist("Daft Punk"))
    assert m.score_album(a, cand("Discovery", "Daft Punk")) >= m.ALBUM_THRESHOLD
    assert m.score_album(a, cand("Discovery", "Electric Light Orchestra")) == 0
    assert m.score_album(a, cand("Homework", "Daft Punk")) == 0


def test_track_queries_are_deduplicated():
    assert m.track_queries(track("hello", "adele")) == ["adele hello"]
    assert "A - B" in m.track_queries(track("A - B", "Uploader"))
