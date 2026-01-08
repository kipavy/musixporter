import argparse
from datetime import datetime
from musixporter.sources.factory import get_source, list_sources
from musixporter.converters.tidal_mapper import TidalMapper
from musixporter.formatters.monochrome import MonochromeJsonOutput
from musixporter.console import info, success, warn, error, console


def main():
    parser = argparse.ArgumentParser(
        description="Export music libraries to Monochrome/Tidal mapping"
    )

    available = list_sources()
    if not available:
        error(
            "No sources available. Make sure musixporter.sources modules exist."
        )
        return

    parser.add_argument(
        "source",
        choices=available,
        help="Source to fetch data from",
    )
    parser.add_argument(
        "--yt-headers",
        default=None,
        help="(YouTube) path to ytmusicapi headers_auth.json for authenticated access",
    )
    parser.add_argument(
        "--yt-playlist",
        default=None,
        help="(YouTube) public playlist id to fetch (unauthenticated)",
    )
    parser.add_argument(
        "--playlist-id",
        default=None,
        help="(Deezer) playlist id to fetch (unauthenticated if public)",
    )
    parser.add_argument(
        "-u",
        "--user",
        dest="user_id",
        default=None,
        help="User ID",
    )

    # REFACOR IN 1 PARSER PER SOURCE TO GET -u | --user per source

    args = parser.parse_args()

    if (
        args.source == "ytmusic"
        and not args.yt_headers
        and not args.yt_playlist
        and not args.user_id
    ):
        parser.error(
            "When --source ytmusic you must provide --yt-headers, --yt-playlist or --user"
        )

    info(f"=== Music Exporter (source={args.source}) ===")

    try:
        if args.source == "ytmusic":
            source = get_source(
                args.source,
                auth_headers_path=args.yt_headers,
                playlist_id=args.yt_playlist,
                user=args.user_id,
            )
        elif args.source == "deezer":
            source = get_source(
                args.source,
                user_id=args.user_id,
                playlist_id=args.playlist_id,
            )
        else:
            source = get_source(args.source)
    except KeyError as e:
        error(str(e))
        info("Available sources: " + ", ".join(list_sources()))
        return

    converter = TidalMapper()
    formatter = MonochromeJsonOutput()

    try:
        source.authenticate()
        data = source.fetch_data()

        info("\n--- Phase 2: Converting IDs to Tidal ---")
        tidal_data = converter.convert(data)

        now = datetime.now().strftime("%Y%m%dT%H%M%S")
        suffix_parts = []
        suffix = ("-" + "-".join(suffix_parts)) if suffix_parts else ""
        out_filename = f"monochrome_tidal_import-{now}{suffix}.json"

        formatter.save(tidal_data, out_filename)
        info(f"Saved output to {out_filename}")

    except Exception as e:
        error(f"\nFATAL ERROR: {e}")
        console.print_exception()


if __name__ == "__main__":
    main()
