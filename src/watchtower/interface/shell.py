"""What every CLI module shares: the Typer app, exit codes, opening the DB, and terminal-safe text (8d: split out
of cli.py so command groups can live in their own modules)."""
from __future__ import annotations

import sqlite3
import unicodedata

import typer

from watchtower.config import Settings, load_settings
from watchtower.engine.db import connect

app = typer.Typer(no_args_is_help=True, help="THE WATCHTOWER — local agentic ecosystem.")
EXIT = {"done": 0, "failed": 1, "paused": 3}


def clean(text: str) -> str:
    """Strip terminal control characters from untrusted text (model output, web content, app logs). 8a (D-M5):
    also Unicode format characters (bidi overrides, zero-width), which can disguise file names and commands."""
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))


def open_db() -> tuple[Settings, sqlite3.Connection]:
    try:
        settings = load_settings()
    except ValueError as e:  # e.g. a bad WATCHTOWER_WORK_MODEL: a clear message, not a traceback
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2) from None
    return settings, connect(settings.db_path)
