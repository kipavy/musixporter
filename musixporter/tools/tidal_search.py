#!/usr/bin/env python3
"""Quick CLI to reproduce Tidal searches for debugging missed tracks.

Usage examples:
  python -m musixporter.tools.tidal_search --title "S.A.T.O." --artist "Ozzy Osbourne"
  python -m musixporter.tools.tidal_search --missed missed_tidal.json
"""
import argparse
import json
import difflib
from musixporter.converters.tidal_mapper import TidalMapper


def clean(s, tm: TidalMapper):
    return tm._clean_str(s or "")


def print_candidate(i, item, clean_title, tm: TidalMapper):
    title = item.get("title")
    cand = tm._clean_str(title)
    score = difflib.SequenceMatcher(None, clean_title, cand).ratio()
    dur = item.get("duration", 0)
    artists = []
    if "artists" in item and isinstance(item["artists"], list):
        for a in item["artists"]:
            if isinstance(a, dict):
                artists.append(a.get("name", ""))
            else:
                artists.append(str(a))
    elif "artist" in item and isinstance(item["artist"], dict):
        artists.append(item["artist"].get("name", ""))

    print(f"[{i}] id={item.get('id')} title={title!r} artists={artists} dur={dur} score={score:.2f}")


def search_one(tm: TidalMapper, source_track: dict):
    print("\n=== Searching for: {} — {} ===".format(source_track.get('title'), tm._get_safe_artist(source_track)[0]))

    # Approach ISRC
    isrc = source_track.get("isrc")
    if isrc:
        print("Approach: ISRC ->", isrc)
        r = tm._approach_isrc(source_track)
        print("  ISRC result:", r and r.get('id'))

    # Approach artist/title
    print("Approach: Artist+Title (fuzzy)")
    res = tm._approach_artist_title(source_track, silent=True)
    if res:
        clean_title = clean(source_track.get('title') or '', tm)
        cand = tm._clean_str(res.get('title') or '')
        score = difflib.SequenceMatcher(None, clean_title, cand).ratio()
        print(f"  Best fuzzy match: {res.get('id')} {res.get('title')!r} (score={score:.2f})")
    else:
        print("  No fuzzy match accepted")

    # Raw queries and top candidates
    title = source_track.get('title') or ''
    artist = tm._get_safe_artist(source_track)[0]
    cleaned = clean(title, tm)
    queries = [f"{cleaned} {tm._clean_str(artist)}", cleaned]

    for q in queries:
        print('\nQuery:', q)
        data = tm._search_tidal(q, types='TRACKS', limit=8)
        items = data.get('tracks', {}).get('items', [])
        if not items:
            print('  No results')
            continue
        for i, it in enumerate(items, start=1):
            print_candidate(i, it, cleaned, tm)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--title', help='Track title')
    p.add_argument('--artist', help='Artist name')
    p.add_argument('--isrc', help='ISRC code')
    p.add_argument('--duration', type=int, help='Duration in seconds')
    p.add_argument('--missed', help='Path to missed_tidal.json to iterate')
    p.add_argument('--country', help='Country code override (default FR)')
    args = p.parse_args()

    tm = TidalMapper()
    if args.country:
        tm.country_code = args.country
    tm._authenticate()

    if args.missed:
        with open(args.missed, 'r', encoding='utf-8') as f:
            missed = json.load(f)
        for m in missed:
            orig = m.get('original') or {}
            search_one(tm, orig)
        return

    if not args.title:
        print('Provide --title or --missed')
        return

    src = {
        'title': args.title,
        'duration': args.duration or 0,
        'isrc': args.isrc,
    }
    if args.artist:
        src['artist'] = {'name': args.artist}

    search_one(tm, src)


if __name__ == '__main__':
    main()
