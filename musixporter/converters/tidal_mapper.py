import requests
import time
import json
import re
import base64
from musixporter.interfaces import IdConverter

# Optional rich for improved console output
try:
    from rich.console import Console
    from rich.progress import Progress, BarColumn, TimeElapsedColumn, TimeRemainingColumn, SpinnerColumn, TextColumn
    from rich.theme import Theme
    HAS_RICH = True
    console = Console(theme=Theme({"info": "cyan", "success": "green", "error": "bold red", "warn": "yellow"}))
except Exception:
    HAS_RICH = False
    console = None

class TidalMapper(IdConverter):
    API_KEYS = [
        {
            "name": "Fire TV",
            "id": "7m7Ap0JC9j1cOM3n",
            "secret": "vRAdA108tlvkJpTsGZS8rGZ7xTlbJ0qaZ2K9saEzsgY="
        },
        {
            "name": "Android Auto",
            "id": "zU4XHVVkc2tDPo4t",
            "secret": "VJKhDFqJPqvsPVNBV6ukXTJmwlvbttP7wlMlrc72se4="
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
            self.console.print("[Tidal] Generating Access Token...", style="info")
        else:
            print("[Tidal] Generating Access Token...")
        for key in self.API_KEYS:
            try:
                creds = f"{key['id']}:{key['secret']}"
                b64_creds = base64.b64encode(creds.encode()).decode()
                headers = {"Authorization": f"Basic {b64_creds}", "Content-Type": "application/x-www-form-urlencoded"}
                data = {"grant_type": "client_credentials"}
                
                r = self.session.post(self.AUTH_URL, data=data, headers=headers, timeout=5)
                resp = r.json()
                
                if r.status_code == 200 and "access_token" in resp:
                    self.bearer_token = resp["access_token"]
                    self.session.headers.update({"Authorization": f"Bearer {self.bearer_token}", "Accept": "application/json"})
                    if self.console:
                        self.console.print(f"[Tidal] Authenticated successfully using {key['name']}.", style="success")
                    else:
                        print(f"[Tidal] Authenticated successfully using {key['name']}.")
                    return
            except Exception: continue
        raise Exception("FATAL: Could not generate a Tidal Access Token.")

    def convert(self, data: dict) -> dict:
        self._authenticate()

        converted = {
            "tracks": [],
            "albums": [],
            "artists": data.get('artists', []),
            "user_playlists": [],
            "favorites_tracks": []
        }

        missed = []

        header = f"[Tidal] Starting conversion (Country: {self.country_code})..."
        if self.console:
            self.console.print()
            self.console.print(header, style="info")
        else:
            print(f"\n{header}")

        # 1. Tracks
        tracks_in = data.get('tracks', [])
        total = len(tracks_in)
        success = 0

        if self.console:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), "[progress.percentage]{task.percentage:>3.0f}%", TimeElapsedColumn(), TimeRemainingColumn(), console=self.console) as progress:
                task = progress.add_task(f"Mapping Tracks", total=total)
                for i, t in enumerate(tracks_in):
                    tidal_t = self._find_track(t)
                    if tidal_t:
                        converted['tracks'].append(tidal_t)
                        converted['favorites_tracks'].append(tidal_t)
                        success += 1
                    else:
                        missed.append({
                            'context': 'tracks',
                            'index': i + 1,
                            'title': t.get('title'),
                            'artist': self._get_safe_artist(t)[0],
                            'original': t,
                        })
                    progress.advance(task)
                    # update description occasionally
                    if (i + 1) % 10 == 0 or i + 1 == total:
                        progress.update(task, description=f"Mapping Tracks ({i+1}/{total}) Matches: {success}")
                    time.sleep(0.1)
        else:
            print(f"[Tidal] Mapping {total} Tracks...")
            for i, t in enumerate(tracks_in):
                tidal_t = self._find_track(t)
                if tidal_t:
                    converted['tracks'].append(tidal_t)
                    converted['favorites_tracks'].append(tidal_t)
                    success += 1
                if i % 10 == 0 and i > 0:
                    print(f"   ...Processed {i}/{total} (Matches: {success})...")
                time.sleep(0.1)

        # 2. Albums
        albums_in = data.get('albums', [])
        if self.console:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TimeElapsedColumn(), console=self.console) as progress:
                task_a = progress.add_task("Mapping Albums", total=len(albums_in))
                for i, a in enumerate(albums_in, start=1):
                    title = (a.get('title') or str(a.get('id') or 'album'))[:40]
                    tidal_a = self._find_album(a)
                    if tidal_a:
                        converted['albums'].append(tidal_a)
                    else:
                        missed.append({
                            'context': 'album',
                            'index': i,
                            'title': a.get('title'),
                            'artist': self._get_safe_artist(a)[0],
                            'original': a,
                        })
                    progress.advance(task_a)
                    # update description to show processed/total and album title
                    if (i % 1 == 0) or (i == len(albums_in)):
                        progress.update(task_a, description=f"Mapping Albums ({i}/{len(albums_in)}) {title}")
                    time.sleep(0.1)
        else:
            print(f"[Tidal] Mapping {len(albums_in)} Albums...")
            for i, a in enumerate(albums_in, start=1):
                tidal_a = self._find_album(a)
                if tidal_a: converted['albums'].append(tidal_a)
                # print a simple progress every 5 albums
                if i % 5 == 0 or i == len(albums_in):
                    print(f"   ...Processed {i}/{len(albums_in)} albums...")
                time.sleep(0.1)

        # 3. Playlists
        playlists_in = data.get('user_playlists', [])
        if self.console:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TimeElapsedColumn(), console=self.console) as progress:
                task_p = progress.add_task("Mapping Playlists", total=len(playlists_in))
                for idx, pl in enumerate(playlists_in, start=1):
                    tracks = pl.get('tracks', []) or []
                    track_count = len(tracks)
                    sub_desc = (pl.get('title') or str(pl.get('id') or 'playlist'))[:40]

                    if track_count == 0:
                        new_pl = pl.copy()
                        new_pl['tracks'] = []
                        converted['user_playlists'].append(new_pl)
                        progress.advance(task_p)
                        continue

                    subtask = progress.add_task(f"{sub_desc} 0/{track_count}", total=track_count)
                    new_pl_tracks = []
                    for i, t in enumerate(tracks, start=1):
                        tidal_t = self._find_track(t, silent=True)
                        if tidal_t:
                            new_pl_tracks.append(tidal_t)
                        else:
                            missed.append({
                                'context': 'playlist',
                                'playlist_index': idx,
                                'playlist_title': sub_desc,
                                'track_index': i,
                                'title': t.get('title'),
                                'artist': self._get_safe_artist(t)[0],
                                'original': t,
                            })
                        progress.advance(subtask)
                        if (i % 5 == 0) or (i == track_count):
                            progress.update(subtask, description=f"{sub_desc} {i}/{track_count}")

                    new_pl = pl.copy()
                    new_pl['tracks'] = new_pl_tracks
                    converted['user_playlists'].append(new_pl)
                    progress.remove_task(subtask)
                    progress.advance(task_p)
        else:
            print(f"[Tidal] Mapping {len(playlists_in)} User Playlists...")
            for pi, pl in enumerate(playlists_in, start=1):
                tracks = pl.get('tracks', []) or []
                new_pl_tracks = []
                for i, t in enumerate(tracks, start=1):
                    tidal_t = self._find_track(t, silent=True)
                    if tidal_t:
                        new_pl_tracks.append(tidal_t)
                    else:
                        missed.append({
                            'context': 'playlist',
                            'playlist_index': pi,
                            'playlist_title': pl.get('title'),
                            'track_index': i,
                            'title': t.get('title'),
                            'artist': self._get_safe_artist(t)[0],
                            'original': t,
                        })
                    if i % 100 == 0:
                        print(f"   Playlist {pi}/{len(playlists_in)}: processed {i}/{len(tracks)} tracks")
                new_pl = pl.copy()
                new_pl['tracks'] = new_pl_tracks
                converted['user_playlists'].append(new_pl)

        if missed:
            try:
                with open('missed_tidal.json', 'w', encoding='utf-8') as mf:
                    json.dump(missed, mf, indent=2, ensure_ascii=False)
                if self.console:
                    self.console.print(f"[Tidal] {len(missed)} items not matched — details saved to missed_tidal.json", style="warn")
                    for m in missed[:20]:
                        self.console.print(f" - {m.get('context')}: {m.get('title')} — {m.get('artist')}")
                else:
                    print(f"[Tidal] {len(missed)} items not matched — saved to missed_tidal.json")
            except Exception:
                if self.console:
                    self.console.print("[Tidal] Could not write missed_tidal.json", style="error")
                else:
                    print("[Tidal] Could not write missed_tidal.json")

        return converted

    def _clean_str(self, s):
        if not s: return ""
        s = re.sub(r'\s*[\(\[].*?[\)\]]', '', s) # Remove (feat) [Edit]
        return re.sub(r'[^a-zA-Z0-9 ]', '', s.lower()).strip()

    def _get_safe_artist(self, obj):
        """Robustly extracts Artist Name and ID from any dict structure."""
        # Try 'artist' dict
        if 'artist' in obj and isinstance(obj['artist'], dict):
            return obj['artist'].get('name', 'Unknown'), obj['artist'].get('id', 0)
        # Try 'artists' list
        if 'artists' in obj and isinstance(obj['artists'], list) and len(obj['artists']) > 0:
            return obj['artists'][0].get('name', 'Unknown'), obj['artists'][0].get('id', 0)
        # Fallback
        return "Unknown", 0

    def _find_track_by_isrc(self, isrc, source_track):
        """Try to find a track on Tidal using its ISRC code."""
        try:
            # Search Tidal by ISRC
            params = {'query': isrc, 'limit': 5, 'types': 'TRACKS', 'countryCode': self.country_code}
            
            r = self.session.get(f"{self.API_BASE}/search", params=params)
            results = r.json().get('tracks', {}).get('items', [])
            
            if not results:
                return None
            
            # Check if any result has matching ISRC
            for item in results:
                item_isrc = item.get('isrc')
                if item_isrc and item_isrc.upper() == isrc.upper():
                    return self._map_tidal_to_internal(item, source_track)
            
            return None
        except Exception:
            return None

    def _find_track(self, source_track, silent=False):
        try:
            # 1. TRY ISRC FIRST (if available)
            isrc = source_track.get('isrc')
            if isrc and isinstance(isrc, str) and isrc.strip():
                tidal_track = self._find_track_by_isrc(isrc.strip(), source_track)
                if tidal_track:
                    return tidal_track
            
            # 2. EXTRACT SOURCE METADATA
            art_name, art_id = self._get_safe_artist(source_track)
            
            if art_name == "Unknown":
                # Only fail if title is also missing
                if not source_track.get('title'): return None

            # Clean up for search
            search_art = art_name.split('(')[0].split('feat')[0].strip()
            clean_title = self._clean_str(source_track.get('title', ''))
            target_dur = source_track.get('duration', 0)
            
            # 3. SEARCH TIDAL BY ARTIST AND TITLE
            query = f"{search_art} {clean_title}"
            params = {'query': query, 'limit': 5, 'types': 'TRACKS', 'countryCode': self.country_code}
            
            r = self.session.get(f"{self.API_BASE}/search", params=params)
            results = r.json().get('tracks', {}).get('items', [])
            
            # Fallback: Search Title only
            if not results and len(clean_title) > 5:
                params['query'] = clean_title
                r = self.session.get(f"{self.API_BASE}/search", params=params)
                results = r.json().get('tracks', {}).get('items', [])

            if not results:
                if not silent:
                    if self.console:
                        self.console.print(f"[Miss] '{query}'", style="warn")
                    else:
                        print(f"      [Miss] '{query}'")
                return None
            
            # 4. MATCHING
            for item in results:
                # Duration check
                if target_dur > 0 and abs(item['duration'] - target_dur) > 15:
                    continue 
                
                # Title check
                found_title = self._clean_str(item['title'])
                if clean_title == found_title or clean_title in found_title or found_title in clean_title:
                    return self._map_tidal_to_internal(item, source_track)
            
            return None

        except Exception as e:
            if not silent:
                t_title = source_track.get('title', 'Unknown')
                if self.console:
                    self.console.print(f"[Error processing '{t_title}']: {e}", style="error")
                else:
                    print(f"      [Error processing '{t_title}']: {e}")
            return None

    def _find_album(self, source_alb):
        try:
            art_name, _ = self._get_safe_artist(source_alb)
            query = f"{art_name} {source_alb.get('title','')}"
            params = {'query': query, 'limit': 1, 'types': 'ALBUMS', 'countryCode': self.country_code}
            
            r = self.session.get(f"{self.API_BASE}/search", params=params)
            results = r.json().get('albums', {}).get('items', [])
            if results:
                item = results[0]
                # Safe mapping
                t_art_name, t_art_id = self._get_safe_artist(item)
                
                return {
                    "id": item['id'],
                    "title": item['title'],
                    "date_add": source_alb.get('date_add'),
                    "release_date": item.get('releaseDate'),
                    "cover": f"https://resources.tidal.com/images/{item['cover'].replace('-', '/')}/640x640.jpg" if item.get('cover') else "",
                    "artist": {"id": t_art_id, "name": t_art_name},
                    "nb_tracks": item.get('numberOfTracks'),
                    "type": "ALBUM"
                }
            return None
        except: return None

    def _map_tidal_to_internal(self, tidal_item, original_source):
        # Extract artist safely from Tidal item (handles artist vs artists)
        t_art_name, t_art_id = self._get_safe_artist(tidal_item)
        
        # Extract album cover safely
        cover_url = ""
        if 'album' in tidal_item and tidal_item['album'].get('cover'):
            cover_url = f"https://resources.tidal.com/images/{tidal_item['album']['cover'].replace('-', '/')}/640x640.jpg"

        return {
            "id": tidal_item['id'],
            "title": tidal_item['title'],
            "duration": tidal_item['duration'],
            "explicit": tidal_item.get('explicit', False),
            "version": tidal_item.get('version', ''),
            "date_add": original_source.get('date_add'),
            "artist": {
                "id": t_art_id, 
                "name": t_art_name
            },
            "album": {
                "id": tidal_item['album']['id'] if 'album' in tidal_item else 0, 
                "title": tidal_item['album']['title'] if 'album' in tidal_item else "Unknown", 
                "cover": cover_url
            }
        }