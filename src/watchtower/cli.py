from __future__ import annotations

from typing import Optional

import typer

from watchtower.config import Settings, load_settings
from watchtower.engine.db import connect
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget, BudgetExceeded
from watchtower.engine.jobs import JobStore
from watchtower.engine.memory import ContextStore
from watchtower.engine.model_socket import CloudDisabled, ModelSocket, ModelUnavailable

app = typer.Typer(no_args_is_help=True, help="THE WATCHTOWER — local agentic ecosystem.")


def build_socket(settings: Settings, budget: Budget, audit: AuditLog) -> ModelSocket:
    return ModelSocket(settings, budget, audit)


def _open():
    settings = load_settings()
    return settings, connect(settings.db_path)


def _fail(jobs: JobStore, audit: AuditLog, job_id: str, reason: str) -> None:
    """Never leave a job in 'running': mark it failed and audit it, best effort."""
    try:
        jobs.set_status(job_id, "failed", reason)
        audit.append("engine", "job_failed", {"error": reason}, job_id)
    finally:
        typer.echo(f"Job {job_id} failed: {reason}", err=True)


@app.command()
def run(
    prompt: str,
    tier: str = typer.Option("small", help="Model tier: small | work | review"),
    max_tokens: Optional[int] = typer.Option(None, min=1, help="Token budget for this job"),
):
    """Send a prompt through the Ground Engine."""
    if not prompt.strip():
        typer.echo("Error: prompt must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = _open()
    jobs, audit, budget, memory = JobStore(conn), AuditLog(conn), Budget(conn), ContextStore(conn)

    job = jobs.create(prompt)
    budget.open(job.id, settings.default_max_tokens if max_tokens is None else max_tokens,
                settings.default_max_seconds, settings.default_max_usd)
    audit.append("owner", "job_created", {"prompt": job.prompt, "tier": tier}, job.id)
    jobs.set_status(job.id, "running")

    messages = [{"role": "user", "content": job.prompt}]
    try:
        reply = build_socket(settings, budget, audit).ask(tier, messages, job.id)
    except (ModelUnavailable, BudgetExceeded, CloudDisabled, ValueError) as e:
        _fail(jobs, audit, job.id, str(e))
        raise typer.Exit(1)
    except KeyboardInterrupt:
        _fail(jobs, audit, job.id, "interrupted by owner")
        raise typer.Exit(130)
    except Exception as e:
        _fail(jobs, audit, job.id, f"unexpected error: {type(e).__name__}: {str(e)[:200]}")
        raise typer.Exit(1)

    messages.append({"role": "assistant", "content": reply.text})
    memory.save("ground.echo", job.id, {"messages": messages})
    jobs.set_status(job.id, "done")
    audit.append("engine", "job_done", {"tokens": reply.prompt_tokens + reply.completion_tokens}, job.id)
    typer.echo(reply.text)
    typer.echo(f"\n[job {job.id} · {reply.model} · "
               f"{reply.prompt_tokens + reply.completion_tokens} tokens · ${reply.usd:.4f}]")


@app.command()
def status(limit: int = 20):
    """List recent jobs."""
    _, conn = _open()
    rows = JobStore(conn).list(limit)
    if not rows:
        typer.echo("No jobs yet.")
        return
    for j in rows:
        line = f"{j.id}  {j.status:<8} {j.created_at[:19]}  {j.prompt[:60]}"
        typer.echo(line + (f"  — {j.error}" if j.error else ""))


@app.command()
def logs(job_id: Optional[str] = typer.Argument(None), limit: int = 100):
    """Show the audit log (optionally for one job) and verify its hash chain."""
    _, conn = _open()
    audit = AuditLog(conn)
    for e in audit.entries(job_id=job_id, limit=limit):
        typer.echo(f"#{e.seq} {e.ts[:19]} {e.actor:<13} {e.action:<12} {e.detail}")
    typer.echo(f"chain: {'ok' if audit.verify() else 'BROKEN — audit log was tampered with'}")


@app.command()
def budget(job_id: str):
    """Show budget usage for a job."""
    _, conn = _open()
    try:
        u = Budget(conn).usage(job_id)
    except KeyError:
        typer.echo(f"Error: no budget for job {job_id}", err=True)
        raise typer.Exit(2)
    typer.echo(f"tokens: {u['used_tokens']} / {u['max_tokens']}")
    typer.echo(f"seconds: {u['used_seconds']:.1f} / {u['max_seconds']}")
    typer.echo(f"usd: ${u['used_usd']:.4f} / ${u['max_usd']:.4f}")
