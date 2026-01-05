import json
from datetime import datetime
from musixporter.interfaces import OutputFormatter

class MonochromeJsonOutput(OutputFormatter):
    def _format_date(self, timestamp):
        try:
            ts = int(timestamp)
            if ts == 0: return datetime.now().isoformat()
            if ts > 10000000000: ts = ts / 1000
            return datetime.fromtimestamp(ts).isoformat()
        except: return str(timestamp)

    def _format_ms(self, timestamp):
        try: return int(timestamp) * 1000
        except: return 0

    def save(self, data: dict, filename: str):
        print(f"\n[Monochrome] Saving to {filename}...")
        
        out = {
            "favorites_tracks": [self._fmt_t(t) for t in data['tracks'] if t['id'] != 0],
            "favorites_albums": [],
            "favorites_artists": data['artists'],
            "favorites_playlists": [],
            "user_playlists": []
        }

        for a in data['albums']:
            if not a['id']: continue
            out["favorites_albums"].append({
                "id": int(a['id']),
                "addedAt": self._format_ms(a['date_add']),
                "title": a['title'],
                "cover": self._normalize_cover(a['cover']),
                "releaseDate": a['release_date'],
                "explicit": False,
                "artist": a['artist'],
                "type": "ALBUM",
                "numberOfTracks": int(a['nb_tracks'] or 0)
            })

        for pl in data['user_playlists']:
            out["user_playlists"].append({
                "cover": "",
                "createdAt": self._format_ms(pl['creation_date']),
                "id": str(pl['id']),
                "name": pl['title'],
                "tracks": [self._fmt_t(t) for t in pl['tracks']]
            })

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2)
        print("Done.")

    def _fmt_t(self, t):
        return {
            "id": int(t['id']),
            "addedAt": self._format_ms(t.get('date_add', 0)),
            "title": t['title'],
            "duration": t['duration'],
            "explicit": t['explicit'],
            "version": t['version'],
            "streamStartDate": self._format_date(t['date_add']),
            "artists": [t['artist']],
            "album": {
                "id": int(t['album']['id']) if t['album']['id'] else 0,
                "cover": self._normalize_cover(t['album']['cover'])
            }
        }

    def _normalize_cover(self, cover):
        """Normalize cover into the compact ID form.

        Example:
        https://resources.tidal.com/images/bddf1064/b2fb/4c6f/a2d5/fd54685b1b42/640x640.jpg
        -> bddf1064-b2fb-4c6f-a2d5-fd54685b1b42
        """
        if not cover:
            return cover
        try:
            if isinstance(cover, str) and cover.startswith('http'):
                from urllib.parse import urlparse
                p = urlparse(cover)
                path = p.path or ''
                if '/images/' in path:
                    rest = path.split('/images/', 1)[1]
                    parts = [p for p in rest.split('/') if p]
                    if len(parts) >= 1:
                        if '.' in parts[-1]:
                            parts = parts[:-1]
                        if parts:
                            return '-'.join(parts)
            if isinstance(cover, str) and '/' in cover and not cover.startswith('http'):
                parts = [p for p in cover.split('/') if p]
                if parts:
                    return '-'.join(parts)
        except Exception:
            pass
        return cover