import argparse
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
        error("No sources available. Make sure musixporter.sources modules exist.")
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
    args = parser.parse_args()

    if (
        args.source == "ytmusic"
        and not args.yt_headers
        and not args.yt_playlist
    ):
        parser.error(
            "When --source ytmusic you must provide --yt-headers or --yt-playlist"
        )

    info(f"=== Music Exporter (source={args.source}) ===")

    try:
        if args.source == "ytmusic":
            source = get_source(
                args.source,
                auth_headers_path=args.yt_headers,
                playlist_id=args.yt_playlist,
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

        formatter.save(tidal_data, "monochrome_tidal_import.json")

    except Exception as e:
        error(f"\nFATAL ERROR: {e}")
        console.print_exception()


if __name__ == "__main__":
    main()
