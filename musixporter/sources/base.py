"""Base class for input sources."""

from __future__ import annotations

import abc
import argparse

from musixporter.models import Library


class SourceError(Exception):
    """A source could not be read (bad id, network failure, private data...)."""


class Source(abc.ABC):
    """A service a library can be exported from.

    Each source declares its own CLI options, so the CLI stays source-agnostic.
    """

    #: sub-command name on the CLI
    name: str
    #: one-line description shown in ``--help``
    help: str

    @classmethod
    @abc.abstractmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Register this source's options on its sub-parser."""

    @classmethod
    @abc.abstractmethod
    def from_args(cls, args: argparse.Namespace) -> "Source":
        """Build the source from parsed options (raise ``SourceError`` if unusable)."""

    @abc.abstractmethod
    def fetch(self) -> Library:
        """Read the library from the service."""
