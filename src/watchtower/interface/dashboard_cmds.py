"""`watchtower dashboard`: the read-only lighthouse page on this Mac (9a)."""
from __future__ import annotations

import typer

from watchtower.config import load_settings
from watchtower.dashboard.server import make_server
from watchtower.interface.shell import app, clean


@app.command()
def dashboard(port: int = typer.Option(8765, "--port", min=0, max=65535, help="Port on 127.0.0.1 only")):
    """Show the tower live in your browser: floors, jobs, approvals, budgets, audit. Read only; approve in the CLI."""
    settings = load_settings()
    if not settings.db_path.is_file():
        typer.echo(f"Error: no tower database at {settings.db_path}; run a job first", err=True)
        raise typer.Exit(2)
    try:
        server = make_server(settings.db_path, port)
    except OSError as e:
        typer.echo(clean(f"Error: {e}"), err=True)
        raise typer.Exit(2) from None
    typer.echo(f"Dashboard (read only): http://127.0.0.1:{server.server_address[1]}   Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
