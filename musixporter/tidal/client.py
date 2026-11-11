"""Small Tidal catalog client (search + ISRC lookup), no user account needed.

It uses the OAuth *client credentials* flow, which only grants read access to
the public catalog. The default credentials are those of a public Tidal client;
override them with ``TIDAL_CLIENT_ID`` / ``TIDAL_CLIENT_SECRET`` if they ever
get revoked.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional

import requests

AUTH_URL = "https://auth.tidal.com/v1/oauth2/token"
API_BASE = "https://api.tidal.com/v1"

DEFAULT_CLIENT_ID = "7m7Ap0JC9j1cOM3n"
DEFAULT_CLIENT_SECRET = "vRAdA108tlvkJpTsGZS8rGZ7xTlbJ0qaZ2K9saEzsgY="

MAX_ATTEMPTS = 5


class TidalError(Exception):
    """Tidal could not be reached or refused the request."""


class TidalClient:
    def __init__(
        self,
        country_code: str = "FR",
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        self.country_code = country_code.upper()
        self.client_id = client_id or os.environ.get("TIDAL_CLIENT_ID") or DEFAULT_CLIENT_ID
        self.client_secret = (
            client_secret or os.environ.get("TIDAL_CLIENT_SECRET") or DEFAULT_CLIENT_SECRET
        )
        self.session = session or requests.Session()
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._auth_lock = threading.Lock()

    # -- Auth --------------------------------------------------------------

    def authenticate(self, force: bool = False) -> None:
        with self._auth_lock:
            if not force and self._token and time.time() < self._token_expiry:
                return
            try:
                r = self.session.post(
                    AUTH_URL,
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                    timeout=15,
                )
                data = r.json()
            except (requests.RequestException, ValueError) as e:
                raise TidalError(f"Tidal authentication failed: {e}") from e
            if r.status_code != 200 or "access_token" not in data:
                detail = data.get("error_description") or data.get("error") or r.status_code
                raise TidalError(f"Tidal authentication refused: {detail}")
            self._token = data["access_token"]
            self._token_expiry = time.time() + int(data.get("expires_in", 3600)) - 60

    # -- Requests ----------------------------------------------------------

    def get(self, path: str, **params: Any) -> dict:
        params.setdefault("countryCode", self.country_code)
        last_error = "unknown error"
        for attempt in range(MAX_ATTEMPTS):
            self.authenticate()
            try:
                r = self.session.get(
                    f"{API_BASE}/{path.lstrip('/')}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=15,
                )
            except requests.RequestException as e:
                last_error = str(e)
                time.sleep(1 + attempt)
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError as e:
                    raise TidalError(f"Tidal returned invalid JSON for {path}") from e
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code == 401:
                self.authenticate(force=True)
            elif r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After") or 2 * (attempt + 1)))
            elif r.status_code >= 500:
                time.sleep(1 + attempt)
            else:
                break
        raise TidalError(f"Tidal request '{path}' failed ({last_error})")

    # -- Catalog -----------------------------------------------------------

    def search(self, query: str, kind: str = "tracks", limit: int = 10) -> list[dict]:
        """Search the catalog. ``kind`` is 'tracks', 'albums' or 'artists'."""
        data = self.get("search", query=query, types=kind.upper(), limit=limit)
        return (data.get(kind) or {}).get("items") or []

    def tracks_by_isrc(self, isrc: str) -> list[dict]:
        """Every catalog track carrying this ISRC (same recording, various albums)."""
        return self.get("tracks", isrc=isrc, limit=20).get("items") or []
