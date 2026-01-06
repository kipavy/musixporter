import json
import time
import requests
import random
from pathlib import Path
from musixporter.interfaces import InputSource

try:
    import browser_cookie3

    AUTO_LOGIN_AVAILABLE = True
except ImportError:
    AUTO_LOGIN_AVAILABLE = False

ARL_CACHE_FILE = Path.home() / ".musixporter_deezer_arl.json"


def _read_arl_cache():
    try:
        if ARL_CACHE_FILE.exists():
            with ARL_CACHE_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("arl")
    except Exception:
        pass
    return None


def _write_arl_cache(arl):
    try:
        ARL_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with ARL_CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump({"arl": arl, "saved_at": int(time.time())}, f)
    except Exception:
        pass


class DeezerGatewaySource(InputSource):
    GW_URL = "https://www.deezer.com/ajax/gw-light.php"

    def __init__(self):
        self.session = requests.Session()
        # CRITICAL: These headers allow the request to pass Deezer's bot checks
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Origin": "https://www.deezer.com",
                "Referer": "https://www.deezer.com/",
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Content-Type": "application/json; charset=utf-8",
            }
        )
        self.arl = None
        self.token = "null"
        self.user_id = None
        self.loved_playlist_id = None

    def authenticate(self):
        print("\n[Deezer] Authenticating...")
        cached = None
        # 1. Auto-Login from browser cookies (if available)
        if AUTO_LOGIN_AVAILABLE:
            try:
                cj = browser_cookie3.load(domain_name="deezer.com")
                for cookie in cj:
                    if cookie.name == "arl":
                        self.arl = cookie.value
                        print("[Deezer] Found session in browser!")
                        break
            except Exception:
                pass

        # 2. Optionally offer cached ARL (disabled by default)
        if not self.arl:
            if ARL_CACHE_FILE.exists():
                use_cached = (
                    input(
                        f"A cached ARL was found at {ARL_CACHE_FILE}. Use it? [y/N]: "
                    )
                    .strip()
                    .lower()
                )
                if use_cached == "y":
                    cached = _read_arl_cache()
                    if cached:
                        self.arl = cached
                        print("[Deezer] Using cached ARL.")

        # 3. Manual input fallback
        if not self.arl:
            self._ask_and_maybe_save_arl()

        # Initial handshake; if cached ARL fails, fall back to asking the user once more
        try:
            self._refresh_token()
        except Exception:
            if cached:
                print("[Deezer] Cached ARL invalid, please provide a new one.")
                try:
                    ARL_CACHE_FILE.unlink()
                except Exception:
                    pass
                # reuse prompt/save helper
                self._ask_and_maybe_save_arl()
                self.session.cookies.set("arl", self.arl, domain=".deezer.com")
                self._refresh_token()
            else:
                raise

        print(f"[Deezer] Logged in as User ID: {self.user_id}")

    def _ask_and_maybe_save_arl(self):
        """Prompt user for ARL and optionally save it to cache file.

        Sets `self.arl` when a value is provided, raises if empty.
        """
        self.arl = input(
            "    Please paste the value of the 'arl' cookie: "
        ).strip()

        if not self.arl:
            raise Exception("No ARL provided.")

        # Ask whether to persist the provided ARL
        save_choice = (
            input(f"Save this ARL to {ARL_CACHE_FILE}? [y/N]: ").strip().lower()
        )
        if save_choice == "y":
            _write_arl_cache(self.arl)
            print(f"[Deezer] ARL cached to {ARL_CACHE_FILE}")
        # set cookie immediately
        self.session.cookies.set("arl", self.arl, domain=".deezer.com")

    def _get_cid(self):
        return str(random.randint(100000000, 999999999))

    def _refresh_token(self):
        # Reset token to null to force a new one
        self.token = "null"
        data = self._raw_call("deezer.getUserData", {})

        if not data or not data.get("USER"):
            print(f"DEBUG AUTH FAILURE: {data}")
            raise Exception("Invalid ARL or Session expired.")

        self.token = data["checkForm"]
        self.user_id = int(data["USER"]["USER_ID"])

        # Capture the loved tracks playlist ID
        if not self.loved_playlist_id:
            self.loved_playlist_id = data["USER"].get("LOVEDTRACKS_ID") or data[
                "USER"
            ].get("loved_tracks_playlist")

    def _raw_call(self, method, body_dict, check_token=True):
        """
        Sends requests using manual JSON serialization and corrected headers.
        """
        params = {
            "api_version": "1.0",
            "api_token": self.token,
            "method": method,
            "input": "3",
            "cid": self._get_cid(),
        }

        # Ensure all IDs in body are strings (Gateway preference)
        clean_body = {
            k: str(v) if isinstance(v, (int, float)) else v
            for k, v in body_dict.items()
        }

        payload_str = json.dumps(clean_body)

        try:
            r = self.session.post(self.GW_URL, params=params, data=payload_str)
            response_json = r.json()

            if "error" in response_json:
                error_list = response_json["error"]
                if isinstance(error_list, dict):
                    err_type = error_list.get("type") or error_list.get("code")

                    if check_token and (
                        err_type == "VALID_TOKEN_REQUIRED"
                        or "token" in str(error_list).lower()
                    ):
                        print(f"      [!] Token refresh required. Retrying...")
                        self._refresh_token()
                        params["api_token"] = self.token
                        params["cid"] = self._get_cid()
                        r = self.session.post(
                            self.GW_URL, params=params, data=payload_str
                        )
                        response_json = r.json()
                    else:
                        # Print generic error but return empty dict so script doesn't crash
                        # This happens if 'song.getListByPlaylist' is deprecated for a specific playlist type
                        print(f"      [API ERROR] {method}: {error_list}")
                        return {}

            return response_json.get("results", {})

        except Exception as e:
            print(f"      [NET ERROR] {method}: {e}")
            return {}

    # --- ROBUST FETCH LOGIC ---

    def _fetch_full_playlist(self, playlist_id, title="Unknown"):
        """
        Uses 'deezer.pagePlaylist' pagination.
        This is the most stable method as it mimics loading the UI page.
        """
        all_tracks = []
        start = 0
        step = 50  # Page size

        print(f"      -> Fetching '{title}' (ID: {playlist_id})...")

        while True:
            # We call pagePlaylist with 'start' to paginate the 'SONGS' list inside it
            body = {
                "playlist_id": playlist_id,
                "nb": step,
                "start": start,
                "tags": True,  # Ensure we get metadata
                "header": True,
            }

            data = self._raw_call("deezer.pagePlaylist", body)

            # Data location varies: sometimes results.SONGS.data, sometimes results.data
            items = []
            if "SONGS" in data and "data" in data["SONGS"]:
                items = data["SONGS"]["data"]
            elif "data" in data:
                items = data["data"]

            if not items:
                break

            all_tracks.extend(items)

            # Progress update
            if start % 100 == 0 and start > 0:
                print(f"         ...Loaded {len(all_tracks)} tracks...")

            if len(items) < step:
                break

            start += step
            if start > 20000:
                break  # Safety cap
            time.sleep(0.15)  # Polite throttle

        return all_tracks

    def fetch_data(self) -> dict:
        print("\n[Deezer] Fetching Library...")

        # 1. FAVORITE TRACKS
        fav_tracks = []
        if self.loved_playlist_id:
            # Use the pagePlaylist strategy which is now fixed with headers
            fav_tracks = self._fetch_full_playlist(
                self.loved_playlist_id, "Loved Tracks"
            )

        # Fallback if playlist ID method returned 0 (and we expected more)
        if len(fav_tracks) == 0:
            print(
                "   [!] Playlist strategy returned 0. Trying 'portal.getUserTracks' fallback..."
            )
            start = 0
            while True:
                data = self._raw_call(
                    "portal.getUserTracks",
                    {"user_id": self.user_id, "start": start, "nb": 50},
                )
                items = data.get("data", [])
                if not items:
                    break
                fav_tracks.extend(items)
                if len(items) < 50:
                    break
                start += 50

        print(f"   -> Total Favorite Tracks found: {len(fav_tracks)}")

        # 2. ALBUMS
        print("   -> Fetching Albums...")
        fav_albums = []
        albums_page = self._raw_call(
            "deezer.pageProfile", {"tab": "albums", "user_id": self.user_id}
        )
        if "TAB" in albums_page and "albums" in albums_page["TAB"]:
            fav_albums = albums_page["TAB"]["albums"].get("data", [])

        # 3. ARTISTS
        print("   -> Fetching Artists...")
        fav_artists = []
        artists_page = self._raw_call(
            "deezer.pageProfile", {"tab": "artists", "user_id": self.user_id}
        )
        if "TAB" in artists_page and "artists" in artists_page["TAB"]:
            fav_artists = artists_page["TAB"]["artists"].get("data", [])

        # 4. PLAYLISTS
        print("   -> Fetching User Playlists...")
        user_playlists_complete = []
        pl_page = self._raw_call(
            "deezer.pageProfile", {"tab": "playlists", "user_id": self.user_id}
        )
        raw_playlists = []
        if "TAB" in pl_page and "playlists" in pl_page["TAB"]:
            raw_playlists = pl_page["TAB"]["playlists"].get("data", [])

        for pl in raw_playlists:
            creator_id = pl.get("PARENT_USER_ID") or pl.get("CREATOR", {}).get(
                "USER_ID"
            )
            pl_id = pl.get("PLAYLIST_ID") or pl.get("id")
            title = pl.get("TITLE") or pl.get("title")

            if str(creator_id) == str(self.user_id) and str(pl_id) != str(
                self.loved_playlist_id
            ):
                full_tracks = self._fetch_full_playlist(pl_id, title)
                pl["FULL_TRACKS"] = full_tracks
                user_playlists_complete.append(pl)

        print("\n[Deezer] Normalizing Data...")
        return {
            "tracks": [self._normalize_track(t) for t in fav_tracks],
            "albums": [self._normalize_album(a) for a in fav_albums],
            "artists": [self._normalize_artist(a) for a in fav_artists],
            "user_playlists": [
                self._normalize_playlist(p) for p in user_playlists_complete
            ],
        }

    # --- NORMALIZERS ---
    def _find_val(self, d, keys, default=None):
        for k in keys:
            if k in d:
                return d[k]
            if k.lower() in d:
                return d[k.lower()]
        return default

    def _normalize_track(self, t):
        tid = self._find_val(t, ["SNG_ID", "ID", "id"])
        if not tid or int(tid) == 0:
            return {"id": 0}

        return {
            "id": int(tid),
            "title": self._find_val(
                t, ["SNG_TITLE", "TITLE", "title"], "Unknown"
            ),
            "duration": int(self._find_val(t, ["DURATION", "duration"], 0)),
            "explicit": bool(
                int(
                    self._find_val(t, ["EXPLICIT_LYRICS", "explicit_lyrics"], 0)
                )
            ),
            "version": self._find_val(t, ["VERSION", "title_version"], ""),
            "date_add": self._find_val(
                t, ["DATE_ADD", "time_add", "added_at"], 0
            ),
            "isrc": self._find_val(t, ["ISRC", "isrc", "SNG_ISRC"], None),
            "artist": {
                "id": self._find_val(t, ["ART_ID", "ARTIST_ID"])
                or self._find_val(t.get("ARTIST", {}), ["ART_ID", "id"]),
                "name": self._find_val(t, ["ART_NAME", "ARTIST_NAME"])
                or self._find_val(t.get("ARTIST", {}), ["ART_NAME", "name"]),
            },
            "album": {
                "id": self._find_val(t, ["ALB_ID", "ALBUM_ID"])
                or self._find_val(t.get("ALBUM", {}), ["ALB_ID", "id"]),
                "title": self._find_val(t, ["ALB_TITLE", "ALBUM_TITLE"])
                or self._find_val(t.get("ALBUM", {}), ["ALB_TITLE", "title"]),
                "cover": self._find_val(t, ["ALB_PICTURE", "ALBUM_PICTURE"])
                or self._find_val(t.get("ALBUM", {}), ["ALB_PICTURE", "cover"]),
            },
        }

    def _normalize_album(self, a):
        return {
            "id": self._find_val(a, ["ALB_ID", "ID", "id"]),
            "title": self._find_val(a, ["ALB_TITLE", "TITLE", "title"]),
            "date_add": self._find_val(a, ["DATE_ADD", "time_add"], 0),
            "release_date": self._find_val(
                a, ["PHYSICAL_RELEASE_DATE", "release_date"]
            ),
            "cover": self._find_val(
                a, ["ALB_PICTURE", "cover", "cover_medium"]
            ),
            "artist": {
                "id": self._find_val(a, ["ART_ID", "artist_id"]),
                "name": self._find_val(a, ["ART_NAME", "artist_name"]),
            },
            "nb_tracks": self._find_val(a, ["NUMBER_TRACK", "nb_tracks"], 0),
        }

    def _normalize_artist(self, a):
        return {
            "id": self._find_val(a, ["ART_ID", "id"]),
            "name": self._find_val(a, ["ART_NAME", "name"]),
        }

    def _normalize_playlist(self, p):
        raw_tracks = p.get("FULL_TRACKS", [])
        clean_tracks = [
            self._normalize_track(t)
            for t in raw_tracks
            if self._normalize_track(t)["id"] != 0
        ]
        return {
            "id": self._find_val(p, ["PLAYLIST_ID", "id"]),
            "title": self._find_val(p, ["TITLE", "title"]),
            "creation_date": self._find_val(
                p, ["DATE_ADD", "creation_date"], 0
            ),
            "cover": self._find_val(
                p, ["PLAYLIST_PICTURE", "picture", "cover"]
            ),
            "tracks": clean_tracks,
        }
