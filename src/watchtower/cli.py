from __future__ import annotations

from typing import Optional

import typer

from watchtower.config import Settings, load_settings
from watchtower.engine.bus import Bus
from watchtower.engine.db import connect
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.jobs import JobStore
from watchtower.engine.memory import ContextStore
from watchtower.engine.model_socket import ModelSocket
from watchtower.engine.runner import JobRunner, RunOutcome
from watchtower.engine.scheduler import Scheduler

app = typer.Typer(no_args_is_help=True, help="THE WATCHTOWER — local agentic ecosystem.")
EXIT = {"done": 0, "failed": 1, "paused": 3}


def build_socket(settings: Settings, budget: Budget, audit: AuditLog) -> ModelSocket:
    return ModelSocket(settings, budget, audit)


def _open():
    settings = load_settings()
    return settings, connect(settings.db_path)


def _runner(settings: Settings, conn) -> JobRunner:
    audit = AuditLog(conn)
    bus = Bus(audit)
    socket = build_socket(settings, Budget(conn), audit)
    return JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus)


def _report(outcome: RunOutcome, conn) -> None:
    if outcome.status == "done":
        used = Budget(conn).usage(outcome.job_id)
        typer.echo(outcome.answer or "")
        typer.echo(f"\n[job {outcome.job_id} · {used['used_tokens']} tokens · ${used['used_usd']:.4f}]")
    elif outcome.status == "paused":
        typer.echo(f"Job {outcome.job_id} paused: {outcome.reason}", err=True)
        typer.echo(f"Resume with: watchtower resume {outcome.job_id}", err=True)
    else:
        typer.echo(f"Job {outcome.job_id} failed: {outcome.reason}", err=True)
    raise typer.Exit(EXIT[outcome.status])


@app.command()
def run(
    prompt: str,
    tier: str = typer.Option("small", help="Model tier: small | work | review"),
    max_tokens: Optional[int] = typer.Option(None, min=1, help="Token budget for this job"),
):
    """Run a prompt as a checkpointed plan → answer job."""
    if not prompt.strip():
        typer.echo("Error: prompt must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = _open()
    if tier not in settings.tiers:
        typer.echo(f"Error: unknown tier {tier!r}; choose from {sorted(settings.tiers)}", err=True)
        raise typer.Exit(2)
    job = JobStore(conn).create(prompt)
    Budget(conn).open(job.id, settings.default_max_tokens if max_tokens is None else max_tokens,
                      settings.default_max_seconds, settings.default_max_usd)
    AuditLog(conn).append("owner", "job_created", {"prompt": job.prompt, "tier": tier}, job.id)
    runner = _runner(settings, conn)
    try:
        outcome = runner.start(job.id, tier)
    finally:
        runner.close()
    _report(outcome, conn)


@app.command()
def pause(job_id: str):
    """Ask a running job to pause after its current step."""
    _, conn = _open()
    jobs = JobStore(conn)
    job = jobs.get(job_id)
    if job is None or job.status != "running":
        state = "unknown" if job is None else job.status
        typer.echo(f"Error: job {job_id} is not running ({state})", err=True)
        raise typer.Exit(2)
    jobs.request_pause(job_id)
    AuditLog(conn).append("owner", "pause_requested", {}, job_id)
    typer.echo(f"Pause requested; job {job_id} will pause after its current step.")


@app.command()
def resume(
    job_id: str,
    force: bool = typer.Option(False, "--force", help="Also resume a job stuck 'running' after power loss"),
):
    """Resume a paused job from its last finished step."""
    settings, conn = _open()
    runner = _runner(settings, conn)
    try:
        outcome = runner.resume(job_id, force=force)
    except KeyError:
        typer.echo(f"Error: no job {job_id}", err=True)
        raise typer.Exit(2)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    finally:
        runner.close()
    _report(outcome, conn)


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
        typer.echo(f"#{e.seq} {e.ts[:19]} {e.actor:<13} {e.action:<14} {e.detail}")
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
