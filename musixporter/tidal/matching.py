"""Pure fuzzy-matching logic between a source item and Tidal candidates.

No network here: everything is deterministic and unit-tested.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Optional

from musixporter.models import Album, Track

TRACK_THRESHOLD = 0.75
ALBUM_THRESHOLD = 0.75
ARTIST_THRESHOLD = 0.85
#: below these, a candidate is rejected whatever its total score
MIN_TITLE_SCORE = 0.6
MIN_ARTIST_SCORE = 0.5

_BRACKETS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_FEAT = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)
#: words that denote a different recording when only one side has them
_VARIANTS = (
    "live", "remix", "karaoke", "instrumental", "acoustic", "cover", "demo",
    "sped up", "slowed", "nightcore", "8d", "tribute",
)
#: suffixes YouTube adds to auto-generated / label channels
_CHANNEL_NOISE = re.compile(r"\s*(?:-\s*topic|vevo|official)\s*$", re.IGNORECASE)


@lru_cache(maxsize=20_000)
def normalize(text: Optional[str], keep_brackets: bool = False) -> str:
    """Lowercase, strip accents/punctuation and (by default) bracketed parts.

    Letters of every script are kept, so non-latin titles stay comparable.
    """
    if not text:
        return ""
    s = text
    if not keep_brackets:
        s = _FEAT.sub("", _BRACKETS.sub("", s))
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = re.sub(r"[^\w\s]|_", " " if keep_brackets else "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s and not keep_brackets:
        # e.g. "(Everything I Do)": nothing left outside the brackets
        return normalize(text, keep_brackets=True)
    return s


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _variant_tags(text: str) -> set[str]:
    words = f" {normalize(text, keep_brackets=True)} "
    return {v for v in _VARIANTS if f" {v} " in words}


def title_candidates(track: Track) -> list[tuple[str, Optional[str]]]:
    """(title, artist override) pairs to try for a source track.

    YouTube videos are often titled "Artist - Title", with the uploader as
    "artist": that form is tried as well.
    """
    out: list[tuple[str, Optional[str]]] = [(track.title, None)]
    if " - " in track.title:
        left, right = track.title.split(" - ", 1)
        out.append((right, left))
    return out


def artist_score(source_artists: Iterable[str], candidate_artists: Iterable[str]) -> float:
    """Best similarity between any source artist and any candidate artist."""
    best = 0.0
    cands = [normalize(c) for c in candidate_artists]
    for raw in source_artists:
        src = normalize(_CHANNEL_NOISE.sub("", raw))
        if not src:
            continue
        for cand in cands:
            if not cand:
                continue
            a, b = src.replace(" ", ""), cand.replace(" ", "")
            if min(len(a), len(b)) >= 3 and (
                f" {src} " in f" {cand} " or f" {cand} " in f" {src} "  # "A & B" vs "A"
                or a.startswith(b) or b.startswith(a)  # "Queen" vs "QueenVEVO"
            ):
                score = 1.0
            else:
                score = similarity(src, cand)
            best = max(best, score)
    return best


def _names(item: dict) -> list[str]:
    names = [a.get("name") or "" for a in item.get("artists") or []]
    if not names and isinstance(item.get("artist"), dict):
        names = [item["artist"].get("name") or ""]
    return names


def score_track(source: Track, candidate: dict) -> float:
    """Score in [0, ~1.1] of a Tidal track against a source track (0 = rejected)."""
    raw_title = candidate.get("title") or ""
    cand_titles = [normalize(raw_title)]
    if " - " in raw_title:  # Tidal sometimes has "Album - Title (Remaster)"
        cand_titles.append(normalize(raw_title.split(" - ", 1)[1]))
    cand_full = f"{candidate.get('title') or ''} {candidate.get('version') or ''}"
    cand_artists = _names(candidate)
    source_artists = [a.name for a in source.artists if a.name]

    best = 0.0
    for title, artist_override in title_candidates(source):
        t = max(similarity(normalize(title), c) for c in cand_titles)
        if t < MIN_TITLE_SCORE:
            continue
        artists = source_artists + ([artist_override] if artist_override else [])
        if artists:
            a = artist_score(artists, cand_artists)
            if a < MIN_ARTIST_SCORE:
                continue
        else:
            a = 0.5  # unknown source artist: neutral
        best = max(best, 0.6 * t + 0.3 * a)
    if not best:
        return 0.0

    duration = candidate.get("duration") or 0
    if source.duration and duration:
        delta = abs(duration - source.duration)
        if delta <= 3:
            best += 0.1
        elif delta <= 10:
            best += 0.05
        elif delta > 60:
            best -= 0.1

    # "live", "remix"... on one side only means another recording. An unwanted
    # variant is heavily penalized; a missing one only slightly (the studio
    # version is an acceptable fallback for a live one, not the reverse).
    source_tags, cand_tags = _variant_tags(source.title), _variant_tags(cand_full)
    if cand_tags - source_tags:
        best -= 0.15
    elif source_tags - cand_tags:
        best -= 0.05
    elif normalize(source.title, keep_brackets=True) == normalize(cand_full, keep_brackets=True):
        best += 0.02  # same version label, e.g. "(Remastered 2015)"
    return max(best, 0.0)


def best_track(source: Track, candidates: Iterable[dict]) -> tuple[Optional[dict], float]:
    best_item, best_score = None, 0.0
    for item in candidates:
        score = score_track(source, item)
        if score > best_score:
            best_item, best_score = item, score
    return best_item, best_score


def score_album(source: Album, candidate: dict) -> float:
    t = similarity(normalize(source.title), normalize(candidate.get("title")))
    if t < MIN_TITLE_SCORE:
        return 0.0
    if source.artist and source.artist.name:
        a = artist_score([source.artist.name], _names(candidate))
        if a < MIN_ARTIST_SCORE:
            return 0.0
    else:
        a = 0.5
    score = 0.6 * t + 0.4 * a
    if normalize(source.title, keep_brackets=True) == normalize(
        candidate.get("title"), keep_brackets=True
    ):
        score += 0.02  # same edition ("Deluxe", "Remastered"...)
    return score


def score_artist(name: str, candidate: dict) -> float:
    return similarity(normalize(name), normalize(candidate.get("name")))


def track_queries(track: Track) -> list[str]:
    """Search queries for a track, most specific first, without duplicates."""
    queries = [
        f"{track.artist_name} {track.title}",
        f"{normalize(track.artist_name)} {normalize(track.title)}",
    ]
    if " - " in track.title:
        queries.append(track.title)  # "Artist - Title" uploads
    seen: set[str] = set()
    out = []
    for q in (q.strip() for q in queries):
        if q and q.casefold() not in seen:
            seen.add(q.casefold())
            out.append(q)
    return out
