"""Command line interface.

``musixporter <source> [options]`` runs an export; with no argument at all
(e.g. double-clicking the executable) a short interactive wizard asks for
what is needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from musixporter import __version__
from musixporter.console import console, error, info, success, warn
from musixporter.formatters.monochrome import MonochromeFormatter
from musixporter.sources import SOURCES, SourceError
from musixporter.tidal import ConversionResult, TidalClient, TidalError, TidalMapper

MAX_MISSES_SHOWN = 20


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-o", "--output", type=Path, metavar="FILE",
        help="output file (default: monochrome_tidal_import-<date>.json)",
    )
    common.add_argument(
        "--country", default="FR", metavar="CC",
        help="Tidal catalog country code used for matching (default: FR)",
    )
    common.add_argument(
        "--workers", type=int, default=4, metavar="N",
        help="parallel Tidal lookups (default: 4)",
    )

    parser = argparse.ArgumentParser(
        prog="musixporter",
        description="Export a music library to a Monochrome (Tidal) backup file.",
        epilog="Run without any argument for an interactive mode.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="source", metavar="SOURCE", required=True)
    for name, cls in SOURCES.items():
        sp = sub.add_parser(name, parents=[common], help=cls.help, description=cls.help)
        cls.add_arguments(sp)
    return parser


def interactive_argv() -> list[str]:
    """Ask the questions needed to build a command line."""
    from rich.prompt import Prompt

    console.print(f"[bold]Musixporter {__version__}[/bold] — interactive mode\n")
    source = Prompt.ask("Source", choices=list(SOURCES), default="deezer")
    if source == "deezer":
        kind = Prompt.ask("Export a whole profile or one playlist?",
                          choices=["profile", "playlist"], default="profile")
        value = Prompt.ask(f"Deezer {kind} id or URL").strip()
        argv = [source, "--user" if kind == "profile" else "--playlist-id", value]
    else:
        kind = Prompt.ask("Export one playlist or all public playlists of a channel?",
                          choices=["playlist", "channel"], default="playlist")
        value = Prompt.ask(f"YouTube Music {kind} id or URL").strip()
        argv = [source, "--playlist" if kind == "playlist" else "--user", value]
    country = Prompt.ask("Tidal country code", default="FR").strip()
    return argv + ["--country", country]


def report(result: ConversionResult, missed_path: Path) -> None:
    lib = result.library
    success(
        f"Matched on Tidal: {len(lib.tracks)} favorite tracks, {len(lib.albums)} albums, "
        f"{len(lib.artists)} artists, {len(lib.playlists)} playlists "
        f"({sum(len(p.tracks) for p in lib.playlists)} tracks)"
    )
    if not result.missed:
        return
    with open(missed_path, "w", encoding="utf-8") as f:
        json.dump([m.to_dict() for m in result.missed], f, indent=2, ensure_ascii=False)
    unique = {(m.kind, m.title, m.artist): m for m in result.missed}
    warn(f"{len(result.missed)} items not found on Tidal ({len(unique)} unique), "
         f"details in {missed_path}")
    if result.errors:
        error(f"{result.errors} lookups failed because of Tidal/network errors: "
              "run the export again to retry them.")
    for m in list(unique.values())[:MAX_MISSES_SHOWN]:
        console.print(f" - {m.kind}: {m.title} — {m.artist}", highlight=False, markup=False)
    if len(unique) > MAX_MISSES_SHOWN:
        console.print(f" ... and {len(unique) - MAX_MISSES_SHOWN} more")


def run(args: argparse.Namespace) -> int:
    try:
        source = SOURCES[args.source].from_args(args)
        info(f"[1/3] Reading library from {args.source}")
        library = source.fetch()
    except SourceError as e:
        error(str(e))
        return 2
    if library.is_empty():
        error("Nothing to export: the source returned no data (is it public?).")
        return 1

    info(f"[2/3] Matching on Tidal (country {args.country.upper()})")
    mapper = TidalMapper(TidalClient(country_code=args.country), workers=args.workers)
    try:
        result = mapper.convert(library)
    except TidalError as e:
        error(str(e))
        return 3

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    output: Path = args.output or Path(f"monochrome_tidal_import-{stamp}.json")
    missed_path = output.with_name(f"missed_tidal-{stamp}.json")
    info("[3/3] Writing Monochrome file")
    MonochromeFormatter().save(result.library, output)
    report(result, missed_path)
    success(f"Saved to {output.resolve()}")
    console.print("Import this file from Monochrome's settings.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    interactive = not argv
    try:
        if interactive:
            argv = interactive_argv()
        code = run(build_parser().parse_args(argv))
    except KeyboardInterrupt:
        error("\nInterrupted.")
        code = 130
    if interactive:
        # keep the window open when launched by double-click
        try:
            input("\nPress Enter to quit...")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
