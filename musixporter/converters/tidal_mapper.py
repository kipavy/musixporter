import json
import re
import difflib
import unicodedata
import time
from functools import lru_cache
from minim import tidal
from musixporter.interfaces import IdConverter

# Optional rich for improved console output
try:
    from rich.console import Console
    from rich.progress import (
        Progress,
        BarColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
        SpinnerColumn,
        TextColumn,
    )
    from rich.theme import Theme

    HAS_RICH = True
    console = Console(
        theme=Theme(
            {
                "info": "cyan",
                "success": "green",
                "error": "bold red",
                "warn": "yellow",
            }
        )
    )
except Exception:
    HAS_RICH = False
    console = None


class TidalMapper(IdConverter):
    API_KEYS = [
        {
            "name": "Fire TV",
            "id": "7m7Ap0JC9j1cOM3n",
            "secret": "vRAdA108tlvkJpTsGZS8rGZ7xTlbJ0qaZ2K9saEzsgY=",
        }
    ]

    def __init__(self):
        self.country_code = "FR"
        self.client: tidal.PrivateAPI | None = None
        self.console = console

        # caches (speed)
        self._search_cache = {}
        self._track_cache = {}

    # ----------------------------
    # Auth
    # ----------------------------

    def _authenticate(self):
        if self.client is not None:
            return

        if self.console:
            self.console.print("[Tidal] Generating Access Token...", style="info")
        else:
            print("[Tidal] Generating Access Token...")

        for key in self.API_KEYS:
            try:
                client = tidal.PrivateAPI(
                    client_id=key["id"],
                    client_secret=key["secret"],
                )
                self.client = client

            except Exception as e:
                if self.console:
                    self.console.print(
                        f"[Tidal] Authentication failed with key '{key['name']}': {e}",
                        style="error",
                    )
                else:
                    print(
                        f"[Tidal] Authentication failed with key '{key['name']}': {e}"
                    )
                continue

    # ----------------------------
    # Utilities
    # ----------------------------

    @lru_cache(maxsize=10_000)
    def _clean_str(self, s):
        if not s:
            return ""
        s = re.sub(r"\s*[\(\[].*?[\)\]]", "", s)
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        return re.sub(r"[^a-zA-Z0-9 ]", "", s).lower().strip()

    def _get_safe_artist(self, obj):
        if isinstance(obj.get("artist"), dict):
            return obj["artist"].get("name", "Unknown"), obj["artist"].get("id", 0)
        if isinstance(obj.get("artists"), list) and obj["artists"]:
            return obj["artists"][0].get("name", "Unknown"), obj["artists"][0].get("id", 0)
        return "Unknown", 0

    # ----------------------------
    # Network (cached)
    # ----------------------------

    def _search_tidal(self, query, type="track", limit=5):
        self._authenticate()

        key = (query, type, limit, self.country_code)
        if key in self._search_cache:
            return self._search_cache[key]

        try:
            result = self.client.search(
                query,
                country_code=self.country_code,
                type=type,
                limit=limit,
            )
            items = result.get("items", []) if isinstance(result, dict) else []

            if type == "track":
                data = {"tracks": {"items": items}}
            elif type == "album":
                data = {"albums": {"items": items}}
            elif type == "artist":
                data = {"artists": {"items": items}}
            else:
                data = result if isinstance(result, dict) else {}

            self._search_cache[key] = data
            return data
        except Exception:
            return {}

    # ----------------------------
    # Matching strategies
    # ----------------------------

    def _find_track_by_isrc(self, isrc):
        if not isrc:
            return None

        try:
            data = self._search_tidal(isrc, type="track", limit=5)
            for item in data.get("tracks", {}).get("items", []) or []:
                if (item.get("isrc") or "").upper() == str(isrc).upper():
                    return self._map_tidal_to_internal(item)
        except Exception:
            return None
        return None

    def _approach_isrc(self, source_track):
        return self._find_track_by_isrc(source_track.get("isrc"))

    def _approach_artist_title(self, source_track, silent=False):
        title = source_track.get("title")
        if not title:
            return None

        clean_title = self._clean_str(title)
        artist = self._get_safe_artist(source_track)[0]
        clean_artist = self._clean_str(artist)
        target_dur = source_track.get("duration", 0)

        queries = [
            f"{artist} {title}",
            f"{clean_artist} {clean_title}",
        ]

        best_score = 0.0
        best_item = None

        for q in queries[:5]:
            results = (
                self._search_tidal(q)
                .get("tracks", {})
                .get("items", [])
            )

            for item in results:
                cand_title = self._clean_str(item.get("title", ""))

                if abs(len(cand_title) - len(clean_title)) > 10:
                    continue
                if cand_title[:1] != clean_title[:1]:
                    continue

                t_score = difflib.SequenceMatcher(
                    None, clean_title, cand_title
                ).ratio()

                cand_artist = self._clean_str(self._get_safe_artist(item)[0])
                a_score = difflib.SequenceMatcher(
                    None, clean_artist, cand_artist
                ).ratio()

                d_score = 0
                dur = item.get("duration", 0)
                if target_dur and dur and abs(dur - target_dur) <= 3:
                    d_score = 0.1

                score = (t_score * 0.8) + (a_score * 0.2) + d_score

                if score > best_score:
                    best_score = score
                    best_item = item

            if best_score >= 0.9:
                break

        if best_item and best_score >= 0.8:
            return self._map_tidal_to_internal(best_item, source_track)

        if not silent and self.console:
            self.console.print(f"[Miss] '{clean_title}' (best={best_score:.2f})", style="warn")
        elif not silent:
            print(f"      [Miss] '{clean_title}' (best={best_score:.2f})")

        return None

    def _find_track(self, source_track, silent=False):
        key = (
            source_track.get("title"),
            self._get_safe_artist(source_track)[0],
            source_track.get("duration"),
        )
        if key in self._track_cache:
            return self._track_cache[key]

        try:
            track = self._approach_isrc(source_track)
            if not track:
                track = self._approach_artist_title(source_track, silent)
            
            self._track_cache[key] = track
            return track
        except Exception as e:
            if not silent:
                t_title = source_track.get("title", "Unknown")
                if self.console:
                    self.console.print(
                        f"[Error processing '{t_title}']: {e}", style="error"
                    )
                else:
                    print(f"      [Error processing '{t_title}']: {e}")
            return None

    def _find_album(self, source_album):
        try:
            art_name, _ = self._get_safe_artist(source_album)
            query = f"{art_name} {source_album.get('title','')}"
            
            data = self._search_tidal(query, type="album", limit=1)
            results = data.get("albums", {}).get("items", [])
            if results:
                item = results[0]
                t_art_name, t_art_id = self._get_safe_artist(item)
                return {
                    "id": item["id"],
                    "title": item["title"],
                    "date_add": source_album.get("date_add"),
                    "release_date": item.get("releaseDate"),
                    "cover": (
                        f"https://resources.tidal.com/images/{item['cover'].replace('-', '/')}/640x640.jpg"
                        if item.get("cover")
                        else ""
                    ),
                    "artist": {"id": t_art_id, "name": t_art_name},
                    "nb_tracks": item.get("numberOfTracks"),
                    "type": "ALBUM",
                }
            return None
        except:
            return None

    # ----------------------------
    # Mapping
    # ----------------------------

    def _map_tidal_to_internal(self, tidal_item, original_source={}):
        artist_name, artist_id = self._get_safe_artist(tidal_item)
        cover = ""
        if tidal_item.get("album", {}).get("cover"):
            cover = (
                "https://resources.tidal.com/images/"
                f"{tidal_item['album']['cover'].replace('-', '/')}/640x640.jpg"
            )

        return {
            "id": tidal_item["id"],
            "title": tidal_item["title"],
            "duration": tidal_item["duration"],
            "explicit": tidal_item.get("explicit", False),
            "version": tidal_item.get("version", ""),
            "date_add": original_source.get("date_add"),
            "artist": {"id": artist_id, "name": artist_name},
            "album": {
                "id": tidal_item["album"]["id"] if "album" in tidal_item else 0,
                "title": tidal_item["album"]["title"]
                if "album" in tidal_item
                else "Unknown",
                "cover": cover,
            },
        }

    # ----------------------------
    # Public API
    # ----------------------------

    def convert(self, data: dict) -> dict:
        self._authenticate()

        converted = {
            "tracks": [],
            "albums": [],
            "artists": data.get("artists", []),
            "user_playlists": [],
            "favorites_tracks": [],
        }

        missed = []

        header = f"[Tidal] Starting conversion (Country: {self.country_code})..."
        if self.console:
            self.console.print()
            self.console.print(header, style="info")
        else:
            print(f"\n{header}")

        # 1. Tracks
        tracks_in = data.get("tracks", [])
        total = len(tracks_in)
        success = 0

        if self.console:
            with Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.0f}%",
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self.console,
            ) as progress:
                task = progress.add_task(f"Mapping Tracks", total=total)
                for i, t in enumerate(tracks_in):
                    tidal_t = self._find_track(t)
                    if tidal_t:
                        converted["tracks"].append(tidal_t)
                        converted["favorites_tracks"].append(tidal_t)
                        success += 1
                    else:
                        missed.append(
                            {
                                "context": "tracks",
                                "index": i + 1,
                                "title": t.get("title"),
                                "artist": self._get_safe_artist(t)[0],
                                "original": t,
                            }
                        )
                    progress.advance(task)
                    if (i + 1) % 10 == 0 or i + 1 == total:
                        progress.update(
                            task,
                            description=f"Mapping Tracks ({i+1}/{total}) Matches: {success}",
                        )
                    if i % 10 == 0:
                        time.sleep(0.01)
        else:
            print(f"[Tidal] Mapping {total} Tracks...")
            for i, t in enumerate(tracks_in):
                tidal_t = self._find_track(t)
                if tidal_t:
                    converted["tracks"].append(tidal_t)
                    converted["favorites_tracks"].append(tidal_t)
                    success += 1
                if i % 10 == 0 and i > 0:
                    print(f"   ...Processed {i}/{total} (Matches: {success})...")

        # 2. Albums
        albums_in = data.get("albums", [])
        if self.console:
            with Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                console=self.console,
            ) as progress:
                task_a = progress.add_task("Mapping Albums", total=len(albums_in))
                for i, a in enumerate(albums_in, start=1):
                    title = (a.get("title") or str(a.get("id") or "album"))[:40]
                    tidal_a = self._find_album(a)
                    if tidal_a:
                        converted["albums"].append(tidal_a)
                    else:
                        missed.append(
                            {
                                "context": "album",
                                "index": i,
                                "title": a.get("title"),
                                "artist": self._get_safe_artist(a)[0],
                                "original": a,
                            }
                        )
                    progress.advance(task_a)
                    if (i % 1 == 0) or (i == len(albums_in)):
                        progress.update(
                            task_a,
                            description=f"Mapping Albums ({i}/{len(albums_in)}) {title}",
                        )
                    time.sleep(0.05)
        else:
            print(f"[Tidal] Mapping {len(albums_in)} Albums...")
            for i, a in enumerate(albums_in, start=1):
                tidal_a = self._find_album(a)
                if tidal_a:
                    converted["albums"].append(tidal_a)
                if i % 5 == 0 or i == len(albums_in):
                    print(f"   ...Processed {i}/{len(albums_in)} albums...")

        # 3. Playlists
        playlists_in = data.get("user_playlists", [])
        if self.console:
            with Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                console=self.console,
            ) as progress:
                task_p = progress.add_task(
                    "Mapping Playlists", total=len(playlists_in)
                )
                for idx, pl in enumerate(playlists_in, start=1):
                    tracks = pl.get("tracks", []) or []
                    track_count = len(tracks)
                    sub_desc = (pl.get("title") or str(pl.get("id") or "playlist"))[:40]

                    if track_count == 0:
                        new_pl = pl.copy()
                        new_pl["tracks"] = []
                        converted["user_playlists"].append(new_pl)
                        progress.advance(task_p)
                        continue

                    subtask = progress.add_task(
                        f"{sub_desc} 0/{track_count}", total=track_count
                    )
                    new_pl_tracks = []
                    for i, t in enumerate(tracks, start=1):
                        tidal_t = self._find_track(t, silent=True)
                        if tidal_t:
                            new_pl_tracks.append(tidal_t)
                        else:
                            missed.append(
                                {
                                    "context": "playlist",
                                    "playlist_index": idx,
                                    "playlist_title": sub_desc,
                                    "track_index": i,
                                    "title": t.get("title"),
                                    "artist": self._get_safe_artist(t)[0],
                                    "original": t,
                                }
                            )
                        progress.advance(subtask)
                        if (i % 5 == 0) or (i == track_count):
                            progress.update(
                                subtask, description=f"{sub_desc} {i}/{track_count}"
                            )

                    new_pl = pl.copy()
                    new_pl["tracks"] = new_pl_tracks
                    converted["user_playlists"].append(new_pl)
                    progress.remove_task(subtask)
                    progress.advance(task_p)
        else:
            print(f"[Tidal] Mapping {len(playlists_in)} User Playlists...")
            for pi, pl in enumerate(playlists_in, start=1):
                tracks = pl.get("tracks", []) or []
                new_pl_tracks = []
                for i, t in enumerate(tracks, start=1):
                    tidal_t = self._find_track(t, silent=True)
                    if tidal_t:
                        new_pl_tracks.append(tidal_t)
                    else:
                        missed.append(
                            {
                                "context": "playlist",
                                "playlist_index": pi,
                                "playlist_title": pl.get("title"),
                                "track_index": i,
                                "title": t.get("title"),
                                "artist": self._get_safe_artist(t)[0],
                                "original": t,
                            }
                        )
                    if i % 100 == 0:
                        print(
                            f"   Playlist {pi}/{len(playlists_in)}: processed {i}/{len(tracks)} tracks"
                        )
                new_pl = pl.copy()
                new_pl["tracks"] = new_pl_tracks
                converted["user_playlists"].append(new_pl)

        # REPORTING
        if missed:
            # 1. Save full detailed log to file (includes duplicates if real)
            try:
                with open("missed_tidal.json", "w", encoding="utf-8") as mf:
                    json.dump(missed, mf, indent=2, ensure_ascii=False)
                file_msg = "details saved to missed_tidal.json"
            except Exception:
                file_msg = "could not write missed_tidal.json"

            # 2. Print unique items to console to avoid spam
            unique_missed = {}
            for m in missed:
                key = (m.get("title"), m.get("artist"), m.get("context"))
                if key not in unique_missed:
                    unique_missed[key] = m

            msg = f"[Tidal] {len(missed)} items not matched ({len(unique_missed)} unique) — {file_msg}"

            if self.console:
                self.console.print(msg, style="warn")
                # Show only unique items
                for m in list(unique_missed.values())[:20]:
                    ctx = m.get('context')
                    pl_info = ""
                    if ctx == "playlist":
                        pl_info = f" ({m.get('playlist_title', '')})"
                    
                    self.console.print(
                        f" - {ctx}{pl_info}: {m.get('title')} — {m.get('artist')}"
                    )
                if len(unique_missed) > 20:
                    self.console.print(f" ... and {len(unique_missed) - 20} more unique items.")
            else:
                print(msg)

        return converted