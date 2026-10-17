"""knowledge add/search and beacon: the local knowledge store and the web research that feeds it (8d: split out
of cli.py)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from watchtower.beacon.beacon import Beacon
from watchtower.beacon.fetcher import Fetcher
from watchtower.beacon.glass import Glass, load_glass_rules
from watchtower.beacon.search import Search, SearchUnavailable
from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.knowledge import Knowledge
from watchtower.interface.shell import app, clean, open_db

MAX_KNOWLEDGE_BYTES = 5 * 1024 * 1024
knowledge_app = typer.Typer(help="Local knowledge store (full-text search with sources).")
app.add_typer(knowledge_app, name="knowledge")


@knowledge_app.command("add")
def knowledge_add(
    path: Path,
    source: Optional[str] = typer.Option(None, help="Where this came from (default: the file URI)"),
    title: Optional[str] = typer.Option(None),
    trusted: bool = typer.Option(False, "--trusted", help="Mark as owner-verified"),
):
    """Add a text file to the knowledge store."""
    if not path.is_file():
        typer.echo(f"Error: {path} is not a file", err=True)
        raise typer.Exit(2)
    if path.stat().st_size > MAX_KNOWLEDGE_BYTES:
        typer.echo("Error: file is larger than 5 MB", err=True)
        raise typer.Exit(2)
    _, conn = open_db()
    src = source or path.resolve().as_uri()
    try:
        doc_id = Knowledge(conn).add(path.read_text(errors="replace"), src, title or path.name, trusted)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2) from None
    AuditLog(conn).append("owner", "knowledge_added", {"doc_id": doc_id, "source": src, "trusted": trusted})
    typer.echo(f"Added document {doc_id} from {src}")


@knowledge_app.command("search")
def knowledge_search(query: str, limit: int = typer.Option(5, min=1, max=50)):
    """Search the knowledge store."""
    _, conn = open_db()
    hits = Knowledge(conn).search(query, limit)
    if not hits:
        typer.echo("No matches.")
        return
    for h in hits:
        typer.echo(clean(f"[{h.doc_id}] {h.title} — {h.source}{'' if h.trusted else ' (untrusted)'}"))
        typer.echo(f"    {clean(h.snippet)}")


def make_beacon(settings: Settings, conn) -> Beacon:
    return Beacon(Search(), Fetcher(), Glass(load_glass_rules("f1")), Knowledge(conn), AuditLog(conn))


@app.command()
def beacon(query: str, pages: int = typer.Option(3, min=1, max=10)):
    """Search the web and add pages that pass Glass 1 to the knowledge store."""
    if not query.strip():
        typer.echo("Error: query must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = open_db()
    audit = AuditLog(conn)
    before = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM audit_log").fetchone()[0]
    try:
        docs = make_beacon(settings, conn).research(query, None)
    except SearchUnavailable as e:
        typer.echo(clean(f"Beacon paused: {e}"), err=True)
        raise typer.Exit(3) from None
    for e in audit.since(before, actor="beacon"):
        if e.action in ("beacon_skip", "glass_reject"):
            why = e.detail.get("reason") or "; ".join(e.detail.get("reasons", []))
            typer.echo(clean(f"✗ {e.detail.get('url')} — {why}"))
        elif e.action == "glass_pass":
            typer.echo(clean(f"✓ {e.detail.get('url')}"))
    typer.echo(f"{len(docs)} page(s) added to knowledge (untrusted).")
