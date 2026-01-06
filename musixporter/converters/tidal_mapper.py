import requests
import time
import json
import re
import difflib
import unicodedata
import base64
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

    AUTH_URL = "https://auth.tidal.com/v1/oauth2/token"
    API_BASE = "https://api.tidal.com/v1"

    def __init__(self):
        self.session = requests.Session()
        self.country_code = "FR"
        self.bearer_token = None
        self.console = console

    def _authenticate(self):
        if self.console:
            self.console.print(
                "[Tidal] Generating Access Token...", style="info"
            )
        else:
            print("[Tidal] Generating Access Token...")
        for key in self.API_KEYS:
            try:
                creds = f"{key['id']}:{key['secret']}"
                b64_creds = base64.b64encode(creds.encode()).decode()
                headers = {
                    "Authorization": f"Basic {b64_creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                }
                data = {"grant_type": "client_credentials"}

                r = self.session.post(
                    self.AUTH_URL, data=data, headers=headers, timeout=5
                )
                resp = r.json()

                if r.status_code == 200 and "access_token" in resp:
                    self.bearer_token = resp["access_token"]
                    self.session.headers.update(
                        {
                            "Authorization": f"Bearer {self.bearer_token}",
                            "Accept": "application/json",
                        }
                    )
                    if self.console:
                        self.console.print(
                            f"[Tidal] Authenticated successfully using {key['name']}.",
                            style="success",
                        )
                    else:
                        print(
                            f"[Tidal] Authenticated successfully using {key['name']}."
                        )
                    return
            except Exception:
                continue
        raise Exception("FATAL: Could not generate a Tidal Access Token.")

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

        header = (
            f"[Tidal] Starting conversion (Country: {self.country_code})..."
        )
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
                    # update description occasionally
                    if (i + 1) % 10 == 0 or i + 1 == total:
                        progress.update(
                            task,
                            description=f"Mapping Tracks ({i+1}/{total}) Matches: {success}",
                        )
                    time.sleep(0.1)
        else:
            print(f"[Tidal] Mapping {total} Tracks...")
            for i, t in enumerate(tracks_in):
                tidal_t = self._find_track(t)
                if tidal_t:
                    converted["tracks"].append(tidal_t)
                    converted["favorites_tracks"].append(tidal_t)
                    success += 1
                if i % 10 == 0 and i > 0:
                    print(
                        f"   ...Processed {i}/{total} (Matches: {success})..."
                    )
                time.sleep(0.1)

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
                task_a = progress.add_task(
                    "Mapping Albums", total=len(albums_in)
                )
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
                    # update description to show processed/total and album title
                    if (i % 1 == 0) or (i == len(albums_in)):
                        progress.update(
                            task_a,
                            description=f"Mapping Albums ({i}/{len(albums_in)}) {title}",
                        )
                    time.sleep(0.1)
        else:
            print(f"[Tidal] Mapping {len(albums_in)} Albums...")
            for i, a in enumerate(albums_in, start=1):
                tidal_a = self._find_album(a)
                if tidal_a:
                    converted["albums"].append(tidal_a)
                # print a simple progress every 5 albums
                if i % 5 == 0 or i == len(albums_in):
                    print(f"   ...Processed {i}/{len(albums_in)} albums...")
                time.sleep(0.1)

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
                    sub_desc = (
                        pl.get("title") or str(pl.get("id") or "playlist")
                    )[:40]

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
                                subtask,
                                description=f"{sub_desc} {i}/{track_count}",
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

        if missed:
            try:
                with open("missed_tidal.json", "w", encoding="utf-8") as mf:
                    json.dump(missed, mf, indent=2, ensure_ascii=False)
                if self.console:
                    self.console.print(
                        f"[Tidal] {len(missed)} items not matched — details saved to missed_tidal.json",
                        style="warn",
                    )
                    for m in missed[:20]:
                        self.console.print(
                            f" - {m.get('context')}: {m.get('title')} — {m.get('artist')}"
                        )
                else:
                    print(
                        f"[Tidal] {len(missed)} items not matched — saved to missed_tidal.json"
                    )
            except Exception:
                if self.console:
                    self.console.print(
                        "[Tidal] Could not write missed_tidal.json",
                        style="error",
                    )
                else:
                    print("[Tidal] Could not write missed_tidal.json")

        return converted

    def _clean_str(self, s):
        if not s:
            return ""
        # Remove parenthetical parts like (feat ...) or [Edit]
        s = re.sub(r"\s*[\(\[].*?[\)\]]", "", s)
        # Normalize unicode (remove diacritics) while preserving letters
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        # Remove any remaining non-alphanumeric characters and lowercase
        return re.sub(r"[^a-zA-Z0-9 ]", "", s).lower().strip()

    def _get_safe_artist(self, obj):
        """Robustly extracts Artist Name and ID from any dict structure."""
        # Try 'artist' dict
        if "artist" in obj and isinstance(obj["artist"], dict):
            return obj["artist"].get("name", "Unknown"), obj["artist"].get(
                "id", 0
            )
        # Try 'artists' list
        if (
            "artists" in obj
            and isinstance(obj["artists"], list)
            and len(obj["artists"]) > 0
        ):
            return obj["artists"][0].get("name", "Unknown"), obj["artists"][
                0
            ].get("id", 0)
        # Fallback
        return "Unknown", 0

    def _search_tidal(self, query, types="TRACKS", limit=5):
        """Perform a Tidal search request and return parsed JSON or empty dict on error."""
        params = {
            "query": query,
            "limit": limit,
            "types": types,
            "countryCode": self.country_code,
        }
        try:
            r = self.session.get(
                f"{self.API_BASE}/search", params=params, timeout=5
            )
            return r.json()
        except Exception:
            return {}

    def _find_track_by_isrc(self, isrc):
        try:
            params = {
                "isrc": isrc,
                "countryCode": self.country_code,
            }
            r = self.session.get(
                f"{self.API_BASE}/tracks/isrc:{isrc}", params=params, timeout=5
            )
            if r.status_code == 200:
                item = r.json()
                return self._map_tidal_to_internal(item)
            return None
        except Exception:
            return None

    def _approach_isrc(self, source_track):
        """Approach 1: lookup by ISRC (fast exact match)."""
        isrc = source_track.get("isrc")
        if not isrc:
            return None
        return self._find_track_by_isrc(isrc)

    def _approach_artist_title(self, source_track, silent=False):
        """Approach 2: build multiple queries (track, track+artist, track+album)
        and pick the best fuzzy match among Tidal search results.
        """
        title = source_track.get("title")
        if not title:
            return None

        # Prepare cleaned names
        clean_title = self._clean_str(title)
        target_dur = source_track.get("duration", 0)

        # Album name (try common keys)
        album = source_track.get("album") or {}
        album_name = ""
        if isinstance(album, dict):
            album_name = album.get("title") or album.get("name") or ""
        elif isinstance(album, str):
            album_name = album
        album_name = self._clean_str(album_name)

        # Artists list
        artists = []
        if "artists" in source_track and isinstance(source_track["artists"], list):
            for a in source_track["artists"]:
                if isinstance(a, dict):
                    artists.append(a.get("name", ""))
                else:
                    artists.append(str(a))
        elif "artist" in source_track and isinstance(source_track["artist"], dict):
            artists.append(source_track["artist"].get("name", ""))

        # Build candidate queries (raw title, apostrophe-preserving, track+album, track+artist, track+artist+album)
        queries = []
        raw_title = source_track.get("title", "")
        if raw_title:
            queries.append(raw_title)
            # also try a variant that preserves apostrophes but removes parentheticals
            raw_ap = raw_title.replace("’", "'")
            raw_ap = re.sub(r"\s*[\(\[].*?[\)\]]", "", raw_ap).strip()
            if raw_ap and raw_ap != raw_title:
                queries.append(raw_ap)
        if album_name:
            queries.append(f"{clean_title} {album_name}")
        for artist in reversed(artists):
            a_clean = self._clean_str(artist)
            if a_clean:
                queries.append(f"{clean_title} {a_clean}")
                if album_name:
                    queries.append(f"{clean_title} {a_clean} {album_name}")

        if clean_title not in queries:
            queries.append(clean_title)

        best_score = 0.0
        best_item = None

        for q in queries:
            data = self._search_tidal(q, types="TRACKS", limit=5)
            results = data.get("tracks", {}).get("items", [])
            for item in results:
                cand_title = self._clean_str(item.get("title", ""))
                # fuzzy similarity
                score = difflib.SequenceMatcher(None, clean_title, cand_title).ratio()

                # duration penalty/bonus
                dur = item.get("duration", 0)
                dur_score = 0
                if target_dur > 0 and dur > 0:
                    if abs(dur - target_dur) <= 3:
                        dur_score = 1
                    elif abs(dur - target_dur) <= 10:
                        dur_score = 0
                    else:
                        dur_score = -0.2

                combined = score + dur_score
                if combined > best_score:
                    best_score = combined
                    best_item = item

            # quick accept if very high match
            if best_score >= 0.90:
                break

        # threshold to accept
        if best_item and best_score >= 0.8:
            return self._map_tidal_to_internal(best_item, source_track)

        # nothing acceptable
        if not silent and self.console:
            self.console.print(f"[Miss] '{clean_title}' (best={best_score:.2f})", style="warn")
        elif not silent:
            print(f"      [Miss] '{clean_title}' (best={best_score:.2f})")
        return None

    def _find_track(self, source_track, silent=False):
        """Sequence multiple search approaches and return the first match."""
        try:
            # Approach 1: ISRC exact match
            tidal_t = self._approach_isrc(source_track)
            if tidal_t:
                return tidal_t

            # Approach 2: artist + title (+duration)
            tidal_t = self._approach_artist_title(source_track, silent=silent)
            if tidal_t:
                return tidal_t

            return None

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
            params = {
                "query": query,
                "limit": 1,
                "types": "ALBUMS",
                "countryCode": self.country_code,
            }

            data = self._search_tidal(query, types="ALBUMS", limit=1)
            results = data.get("albums", {}).get("items", [])
            if results:
                item = results[0]
                # Safe mapping
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

    def _map_tidal_to_internal(self, tidal_item, original_source={}):
        # Extract artist safely from Tidal item (handles artist vs artists)
        t_art_name, t_art_id = self._get_safe_artist(tidal_item)

        # Extract album cover safely
        cover_url = ""
        if "album" in tidal_item and tidal_item["album"].get("cover"):
            cover_url = f"https://resources.tidal.com/images/{tidal_item['album']['cover'].replace('-', '/')}/640x640.jpg"

        return {
            "id": tidal_item["id"],
            "title": tidal_item["title"],
            "duration": tidal_item["duration"],
            "explicit": tidal_item.get("explicit", False),
            "version": tidal_item.get("version", ""),
            "date_add": original_source.get("date_add"),
            "artist": {"id": t_art_id, "name": t_art_name},
            "album": {
                "id": tidal_item["album"]["id"] if "album" in tidal_item else 0,
                "title": (
                    tidal_item["album"]["title"]
                    if "album" in tidal_item
                    else "Unknown"
                ),
                "cover": cover_url,
            },
        }
