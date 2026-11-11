"""Available input sources.

To add a source: create a module with a ``Source`` subclass and list it here.
(An explicit registry rather than runtime discovery, so that it also works in
a frozen PyInstaller executable.)
"""

from musixporter.sources.base import Source, SourceError
from musixporter.sources.deezer import DeezerSource
from musixporter.sources.ytmusic import YouTubeMusicSource

SOURCES: dict[str, type[Source]] = {
    cls.name: cls for cls in (DeezerSource, YouTubeMusicSource)
}

__all__ = ["SOURCES", "Source", "SourceError"]
