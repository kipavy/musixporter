import json
from datetime import datetime
from music_exporter.interfaces import OutputFormatter

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
                "cover": a['cover'],
                "releaseDate": a['release_date'],
                "explicit": False,
                "artist": a['artist'],
                "type": "ALBUM",
                "numberOfTracks": int(a['nb_tracks'] or 0)
            })

        for pl in data['user_playlists']:
            out["user_playlists"].append({
                "cover": pl['cover'],
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
            "title": t['title'],
            "duration": t['duration'],
            "explicit": t['explicit'],
            "version": t['version'],
            "streamStartDate": self._format_date(t['date_add']),
            "artists": [t['artist']],
            "album": {
                "id": int(t['album']['id']) if t['album']['id'] else 0,
                "cover": t['album']['cover']
            }
        }