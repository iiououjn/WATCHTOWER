"""The `watchtower` command: jobs (ask, run, research, approve, pause, resume), status, logs, budget and doctor.
Deploy and knowledge commands register themselves from their own modules (8d: cli.py split, audit E-A1)."""
from __future__ import annotations

from typing import Optional

import click
import typer

from watchtower.config import Settings
from watchtower.engine.bus import Bus
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.jobs import JobStore
from watchtower.engine.model_socket import ModelSocket
from watchtower.engine.runner import JobRunner, RunOutcome, owner_alive
from watchtower.engine.sandbox import Sandbox
from watchtower.engine.scheduler import Scheduler
from watchtower.evidence import no_host_run
from watchtower.interface import checks
from watchtower.interface.shell import EXIT, app, clean, open_db


def build_socket(settings: Settings, budget: Budget, audit: AuditLog) -> ModelSocket:
    return ModelSocket(settings, budget, audit)


def make_sandbox(settings: Settings, conn) -> Sandbox:
    return Sandbox(settings, AuditLog(conn))


def _check_guardrails(settings: Settings) -> None:
    from watchtower.guardrails import GuardrailsError, load_guardrails
    try:
        load_guardrails(settings.home)
    except GuardrailsError as e:
        typer.echo(f"Error: {e} — fix or delete {settings.home / 'guardrails.yaml'}", err=True)
        raise typer.Exit(2) from None


def _runner(settings: Settings, conn) -> JobRunner:
    _check_guardrails(settings)
    audit = AuditLog(conn)
    bus = Bus(audit)
    socket = build_socket(settings, Budget(conn), audit)
    return JobRunner(settings, conn, socket, Scheduler(settings, bus), bus,
                     sandbox=make_sandbox(settings, conn))


def _report(outcome: RunOutcome, conn) -> None:
    if outcome.status == "done":
        used = Budget(conn).usage(outcome.job_id)
        typer.echo(clean(outcome.answer or ""))
        typer.echo(f"\n[job {outcome.job_id} · {used['used_tokens']} tokens · ${used['used_usd']:.4f}]")
    elif outcome.status == "paused":
        pending = Approvals(conn).pending_for(outcome.job_id)
        if pending:
            what = "App for job {} — awaiting your sign-off" if pending.kind == "signoff" else \
                "Spec for job {} — awaiting your approval"
            typer.echo("\n" + what.format(outcome.job_id) + ":\n")
            typer.echo(clean(no_host_run(pending.summary)))  # 8a: a summary stored before 8a
            typer.echo(f"\nApprove with: watchtower approve {outcome.job_id}   (or add --reject)", err=True)
        else:
            typer.echo(clean(f"Job {outcome.job_id} paused: {outcome.reason}"), err=True)
            typer.echo(f"Resume with: watchtower resume {outcome.job_id}", err=True)
    else:
        typer.echo(clean(f"Job {outcome.job_id} failed: {outcome.reason}"), err=True)
    raise typer.Exit(EXIT[outcome.status])


@app.command()
def ask(
    prompt: str,
    tier: str = typer.Option("small", help="Model tier: small | work"),
    max_tokens: Optional[int] = typer.Option(None, min=1, help="Token budget for this job"),
):
    """Quick question to one model (checkpointed plan → answer); no floors involved."""
    if not prompt.strip():
        typer.echo("Error: prompt must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = open_db()
    if tier not in settings.tiers:
        typer.echo(f"Error: unknown tier {tier!r}; choose from {sorted(settings.tiers)}", err=True)
        raise typer.Exit(2)
    _check_guardrails(settings)
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
    """Ask a running job to pause after its current step or dev attempt."""
    _, conn = open_db()
    jobs = JobStore(conn)
    job = jobs.get(job_id)
    if job is None or job.status != "running":
        state = "unknown" if job is None else job.status
        typer.echo(f"Error: job {job_id} is not running ({state})", err=True)
        raise typer.Exit(2)
    jobs.request_pause(job_id)
    AuditLog(conn).append("owner", "pause_requested", {}, job_id)
    typer.echo(f"Pause requested; job {job_id} will pause after its current step or dev attempt.")


@app.command()
def resume(
    job_id: str,
    force: bool = typer.Option(False, "--force", help="Kept for old scripts; a dead job's free lock is enough"),
):
    """Resume a paused job from its last finished step."""
    settings, conn = open_db()
    runner = _runner(settings, conn)
    try:
        outcome = runner.resume(job_id, force=force)
    except KeyError:
        typer.echo(f"Error: no job {job_id}", err=True)
        raise typer.Exit(2) from None
    except ValueError as e:
        typer.echo(clean(f"Error: {e}"), err=True)
        raise typer.Exit(2) from None
    finally:
        runner.close()
    _report(outcome, conn)


@app.command()
def status(limit: int = 20):
    """List recent jobs."""
    settings, conn = open_db()
    rows = JobStore(conn).list(limit)
    if not rows:
        typer.echo("No jobs yet.")
        return
    for j in rows:
        line = f"{j.id}  {j.status:<8} {j.created_at[:19]}  {j.prompt[:60]}"
        if j.status == "running" and not owner_alive(settings.home, j.id):  # 8b: its process died
            line += "  (process gone; resume it)"
        typer.echo(clean(line + (f"  — {j.error}" if j.error else "")))  # gate reasons, app logs (8a)


@app.command()
def logs(job_id: Optional[str] = typer.Argument(None), limit: int = 100):
    """Show the audit log (optionally for one job) and verify its hash chain."""
    _, conn = open_db()
    audit = AuditLog(conn)
    for e in audit.entries(job_id=job_id, limit=limit):
        typer.echo(clean(f"#{e.seq} {e.ts[:19]} {e.actor:<13} {e.action:<14} {e.detail}"))
    typer.echo(f"chain: {'ok' if audit.verify() else 'BROKEN — audit log was tampered with'}")


@app.command()
def budget(job_id: str):
    """Show budget usage for a job."""
    _, conn = open_db()
    try:
        u = Budget(conn).usage(job_id)
    except KeyError:
        typer.echo(f"Error: no budget for job {job_id}", err=True)
        raise typer.Exit(2) from None
    typer.echo(f"tokens: {u['used_tokens']} / {u['max_tokens']}")
    typer.echo(f"seconds: {u['used_seconds']:.1f} / {u['max_seconds']}")
    typer.echo(f"usd: ${u['used_usd']:.4f} / ${u['max_usd']:.4f}")


@app.command()
def doctor():
    """Check that the tower's engine parts are healthy."""
    settings, conn = open_db()
    found = checks.doctor_checks(settings, AuditLog(conn))
    for name, ok, detail in found:
        typer.echo(f"{'✓' if ok else '✗'} {name:<12} {detail}")
    raise typer.Exit(0 if all(ok for _, ok, _ in found) else 1)


@app.command()
def run(
    idea: str,
    yes: bool = typer.Option(False, "--yes",
                             help="Skip CPO questions and auto-approve the spec; you still sign off the app"),
    offline: bool = typer.Option(False, "--offline", help="Do not search the web"),
    research: bool = typer.Option(False, "--research", help="Floor 1 researches the web first"),
    max_tokens: Optional[int] = typer.Option(None, min=1, help="Token budget for this job"),
):
    """Run an idea through the whole tower: CPO spec → floors 1-5 → CEO → your sign-off."""
    _tower_job(idea, True, yes, offline, research, max_tokens)


@app.command("research")
def research_cmd(
    topic: str,
    yes: bool = typer.Option(False, "--yes", help="Skip CPO questions and auto-approve the spec"),
    offline: bool = typer.Option(False, "--offline", help="Do not search the web"),
    max_tokens: Optional[int] = typer.Option(None, min=1, help="Token budget for this job"),
):
    """Floor 1 only: CPO spec → research brief with sources → gate."""
    _tower_job(topic, False, yes, offline, False, max_tokens)


def _tower_job(goal: str, app: bool, yes: bool, offline: bool, research: bool, max_tokens: Optional[int]) -> None:
    if not goal.strip():
        typer.echo("Error: goal must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = open_db()
    _check_guardrails(settings)
    if app:  # an app job needs the sandbox: say so now, before any model work is spent
        typer.echo("Checking Docker…", err=True)
        ok, detail = checks.docker_status(settings, AuditLog(conn))
        if not ok:
            typer.echo(f"Error: {detail}", err=True)
            raise typer.Exit(2)
    job = JobStore(conn).create(goal, pipeline="app" if app else "tower")
    Budget(conn).open(job.id, settings.tower_max_tokens if max_tokens is None else max_tokens,
                      settings.default_max_seconds, settings.default_max_usd)
    AuditLog(conn).append("owner", "job_created", {"prompt": job.prompt, "pipeline": job.pipeline}, job.id)
    runner = _runner(settings, conn)
    try:
        answers = []
        if not yes:
            try:
                questions = runner.cpo_questions(job.id)
            except Exception as e:  # questions are optional; the spec step still runs
                typer.echo(clean(f"CPO could not ask questions ({type(e).__name__}: {e}); "
                                  "continuing without questions."), err=True)
                questions = []
            try:
                for q in questions:
                    answers.append({"q": q, "a": typer.prompt(f"CPO asks: {clean(q)}", default="",
                                                              show_default=False)})
            except (KeyboardInterrupt, click.exceptions.Abort):
                runner.release(job.id)
                JobStore(conn).set_status(job.id, "failed", "cancelled by owner during CPO questions")
                typer.echo(f"\nJob {job.id} cancelled.", err=True)
                raise typer.Exit(130) from None
        outcome = runner.start(job.id, extra={"answers": answers, "auto_approve": yes, "offline": offline,
                                                    "research": research})
    finally:
        runner.close()
    _report(outcome, conn)


@app.command()
def approve(job_id: str,
            reject: bool = typer.Option(False, "--reject", help="Reject instead (the spec, or the finished app)")):
    """Approve (or reject) what a job is waiting on — its spec or the finished app's sign-off — then resume it."""
    settings, conn = open_db()
    approvals = Approvals(conn)
    pending = approvals.pending_for(job_id)
    if pending is None:
        typer.echo(f"Error: job {job_id} has no pending approval", err=True)
        raise typer.Exit(2)
    job = JobStore(conn).get(job_id)
    if job is None or job.status != "paused":
        state = "unknown" if job is None else job.status
        typer.echo(f"Error: job {job_id} is {state}; approve it once it has paused for approval", err=True)
        raise typer.Exit(2)
    approvals.decide(pending.id, not reject)
    AuditLog(conn).append("owner", "approval_decided", {"approval_id": pending.id, "approved": not reject}, job_id)
    if reject:
        reason = f"{'app' if pending.kind == 'signoff' else 'spec'} rejected by owner"
        JobStore(conn).set_status(job_id, "failed", reason)
        typer.echo(f"Job {job_id} failed: {reason}", err=True)
        raise typer.Exit(1)
    runner = _runner(settings, conn)
    try:
        outcome = runner.resume(job_id)
    except (KeyError, ValueError) as e:
        typer.echo(clean(f"Error: {e}"), err=True)
        typer.echo(f"Approval recorded. Resume with: watchtower resume {job_id}", err=True)
        raise typer.Exit(2) from None
    finally:
        runner.close()
    _report(outcome, conn)


from watchtower.interface import dashboard_cmds, deploy_cmds, knowledge_cmds  # noqa: E402,F401 — register commands
