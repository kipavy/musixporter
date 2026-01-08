"""Source factory: dynamically discover available InputSource implementations.

Discovery strategy:
- Import all modules in the `musixporter.sources` package (skips subpackages).
- For each module, find classes that subclass `InputSource` and register them
  under the module name (e.g., `deezer`, `youtube_music`).

This keeps `main.py` source-agnostic: adding a new file in `musixporter/sources`
exposes the source automatically.
"""

import pkgutil
import importlib
import inspect
from typing import Dict, Type

from musixporter.interfaces import InputSource


def _iter_source_modules(package_name: str):
    pkg = importlib.import_module(package_name)
    if not hasattr(pkg, "__path__"):
        return
    for finder, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg:
            continue
        yield f"{package_name}.{name}", name


def discover_sources(
    package_name: str = "musixporter.sources",
) -> Dict[str, Type[InputSource]]:
    sources: Dict[str, Type[InputSource]] = {}
    for full_mod, short_name in _iter_source_modules(package_name):
        try:
            mod = importlib.import_module(full_mod)
        except Exception as e:
            print(f"Warning: failed to import source module {full_mod}: {e}")
            continue

        for _, obj in inspect.getmembers(mod, inspect.isclass):
            try:
                if issubclass(obj, InputSource) and obj is not InputSource:
                    key = getattr(obj, "SOURCE_KEY", short_name)
                    sources[key] = obj
            except Exception:
                continue

    return sources


_SOURCES = discover_sources()


def list_sources():
    return list(_SOURCES.keys())


def get_source(key: str, **kwargs) -> InputSource:
    cls = _SOURCES.get(key)
    if not cls:
        raise KeyError(
            f"Unknown source '{key}'. Available: {', '.join(list_sources())}"
        )
    return cls(**kwargs)
