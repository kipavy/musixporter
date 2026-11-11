"""Shared console helpers (one rich Console for the whole app)."""

from rich.console import Console
from rich.theme import Theme

console = Console(
    theme=Theme(
        {"info": "cyan", "success": "green", "error": "bold red", "warn": "yellow"}
    )
)


def info(msg: str) -> None:
    console.print(msg, style="info", highlight=False)


def success(msg: str) -> None:
    console.print(msg, style="success", highlight=False)


def warn(msg: str) -> None:
    console.print(msg, style="warn", highlight=False)


def error(msg: str) -> None:
    console.print(msg, style="error", highlight=False)
