"""Debug helper: show how a track is searched and scored on Tidal.

Examples:
  python -m musixporter.tools.tidal_search --title "S.A.T.O." --artist "Ozzy Osbourne"
  python -m musixporter.tools.tidal_search --missed missed_tidal-<date>.json
"""

from __future__ import annotations

import argparse
import json

from musixporter.models import Artist, Track
from musixporter.tidal import TidalClient, matching


def explain(client: TidalClient, track: Track) -> None:
    print(f"\n=== {track.title} — {track.artist_name} ===")
    if track.isrc:
        items = client.tracks_by_isrc(track.isrc)
        print(f"ISRC {track.isrc}: {len(items)} result(s)")
        show(track, items)
    for query in matching.track_queries(track):
        print(f"Query: {query!r}")
        show(track, client.search(query, "tracks"))
    print(f"(accepted from score {matching.TRACK_THRESHOLD})")


def show(track: Track, items: list[dict]) -> None:
    for item in sorted(items, key=lambda it: -matching.score_track(track, it)):
        artists = ", ".join(a.get("name") or "" for a in item.get("artists") or [])
        version = f" [{item['version']}]" if item.get("version") else ""
        print(
            f"  {matching.score_track(track, item):.2f}  id={item.get('id')}  "
            f"{item.get('title')!r}{version}  by {artists}  ({item.get('duration')}s)"
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--title")
    p.add_argument("--artist", default="")
    p.add_argument("--isrc")
    p.add_argument("--duration", type=int, default=0, help="seconds")
    p.add_argument("--missed", help="missed_tidal-*.json file written by an export")
    p.add_argument("--country", default="FR")
    args = p.parse_args()

    client = TidalClient(country_code=args.country)
    if args.missed:
        with open(args.missed, encoding="utf-8") as f:
            tracks = [
                Track(title=m["title"], artists=[Artist(m.get("artist") or "")],
                      isrc=m.get("isrc"), duration=m.get("duration") or 0)
                for m in json.load(f) if m.get("kind") == "track"
            ]
    elif args.title:
        tracks = [Track(title=args.title, artists=[Artist(args.artist)] if args.artist else [],
                        isrc=args.isrc, duration=args.duration)]
    else:
        p.error("provide --title or --missed")
    for track in tracks:
        explain(client, track)


if __name__ == "__main__":
    main()
