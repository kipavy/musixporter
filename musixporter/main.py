import argparse
from musixporter.sources.factory import get_source, list_sources
from musixporter.converters.tidal_mapper import TidalMapper
from musixporter.formatters.monochrome import MonochromeJsonOutput


def main():
    parser = argparse.ArgumentParser(
        description="Export music libraries to Monochrome/Tidal mapping"
    )

    available = list_sources()
    if not available:
        print(
            "No sources available. Make sure musixporter.sources modules exist."
        )
        return

    parser.add_argument(
        "--source",
        choices=available,
        default="deezer",
        help="Source to fetch data from",
    )
    parser.add_argument(
        "--yt-headers",
        default=None,
        help="(YouTube) path to ytmusicapi headers_auth.json for authenticated access",
    )
    args = parser.parse_args()

    print(f"=== Music Exporter (source={args.source}) ===")

    try:
        source = get_source(args.source)
    except KeyError as e:
        print(e)
        print("Available sources:", ", ".join(list_sources()))
        return

    converter = TidalMapper()
    formatter = MonochromeJsonOutput()

    try:
        # 2. Get Data from source
        source.authenticate()
        data = source.fetch_data()

        # 3. Convert IDs (Search on Tidal)
        print("\n--- Phase 2: Converting IDs to Tidal ---")
        tidal_data = converter.convert(data)

        # 4. Save to Monochrome Format
        formatter.save(tidal_data, "monochrome_tidal_import.json")

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
