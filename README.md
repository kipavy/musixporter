## Musixporter

Export a **Deezer** or **YouTube Music** library (favorites and playlists) to a
JSON file that [Monochrome](https://monochrome.samidy.com/) can import.

Every track is looked up in the Tidal catalog (by ISRC when the source gives
one, otherwise by fuzzy artist/title/duration matching), since Monochrome
works with Tidal ids.

It is a local command-line tool: **no server, no account and no API key
needed**. It only needs internet access to reach Deezer / YouTube Music and
Tidal.

### Installation

Pick one:

- **Nothing to install** (needs [uv](https://docs.astral.sh/uv/)): replace
  `musixporter` in the commands below with

  ```sh
  uvx --refresh --from git+https://github.com/kipavy/musixporter.git musixporter
  ```

- **In a virtual environment**:

  ```sh
  uv venv
  uv pip install git+https://github.com/kipavy/musixporter.git
  ```

- **Standalone executable** (no Python needed), see
  [below](#standalone-executable).

### Usage

```sh
musixporter                 # interactive mode: answers a few questions
musixporter deezer --help   # options of a source
```

Deezer (the profile / playlists must be **public**):

```sh
# favorite tracks, albums, artists and all playlists of a user
musixporter deezer --user 65192821
# one or several playlists (ids or URLs)
musixporter deezer --playlist-id 908622995 --playlist-id https://www.deezer.com/playlist/1313621735
```

YouTube Music:

```sh
# a public or unlisted playlist (id or URL)
musixporter ytmusic --playlist PLjfeWyMu9MJi_1aaHr4ge5uGZ3d3vcN2M
# every public playlist of a channel
musixporter ytmusic --user UCYAWn2uTuEkb9w_FzM-nQhw
# your own liked songs and library playlists, with a ytmusicapi auth file
# (https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html)
musixporter ytmusic --headers browser.json
```

Common options:

| Option | Meaning |
| --- | --- |
| `-o, --output FILE` | output file (default `monochrome_tidal_import-<date>.json`) |
| `--country CC` | Tidal catalog country used for matching (default `FR`) |
| `--workers N` | parallel Tidal lookups (default 4) |

Two files are written in the current directory:

- `monochrome_tidal_import-<date>.json`: the file to import;
- `missed_tidal-<date>.json`: what could not be found on Tidal, if anything.

### Import into Monochrome

In Monochrome, open the settings and import the generated
`monochrome_tidal_import-<date>.json` file. Importing the same playlist again
updates it instead of duplicating it.

### Standalone executable

```sh
uv pip install -e ".[build]"
pyinstaller --onefile --name musixporter --paths . --collect-data ytmusicapi packaging/entry.py
```

The executable is created in `dist/` (`musixporter.exe` on Windows; build on
the OS you target). Double-clicking it starts the interactive mode; it also
accepts the same arguments as above from a terminal. Pushing a `v*` tag makes
the CI build Windows, Linux and macOS executables and attach them to the
GitHub release.

### Development

```
musixporter/
  cli.py              command line + interactive mode
  models.py           Track / Album / Artist / Playlist / Library
  sources/            where the library comes from (deezer.py, ytmusic.py)
  tidal/client.py     Tidal catalog client (auth, retries, search, ISRC lookup)
  tidal/matching.py   pure fuzzy-matching logic
  tidal/mapper.py     source Library -> Tidal Library (+ list of misses)
  formatters/         output formats (monochrome.py)
  tools/tidal_search.py   debug a match: python -m musixporter.tools.tidal_search --title ... --artist ...
```

```sh
uv sync --extra dev
uv run pytest
```

To add a source, subclass `musixporter.sources.base.Source` and register it in
`musixporter/sources/__init__.py`: its options appear on the CLI automatically.

The Tidal lookups use public client credentials (read-only catalog access).
Should they stop working, set `TIDAL_CLIENT_ID` / `TIDAL_CLIENT_SECRET`.
