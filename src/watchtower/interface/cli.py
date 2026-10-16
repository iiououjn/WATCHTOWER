from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import click
import typer
import yaml

from watchtower.config import Settings, load_settings
from watchtower.beacon.beacon import Beacon
from watchtower.beacon.fetcher import Fetcher
from watchtower.beacon.glass import Glass, load_glass_rules
from watchtower.beacon.search import Search, SearchUnavailable
from watchtower.engine.bus import Bus
from watchtower.engine.db import connect
from watchtower.floors.f4_qa_deploy.deploy import DeployError, Deployer
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.budget import Budget
from watchtower.engine.jobs import JobStore
from watchtower.engine.knowledge import Knowledge
from watchtower.engine.memory import ContextStore
from watchtower.engine.model_socket import ModelSocket
from watchtower.engine.runner import JobRunner, RunOutcome
from watchtower.engine.sandbox import Sandbox
from watchtower.engine.scheduler import Scheduler
from watchtower.engine.system import free_ram_pct

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _clean(text: str) -> str:
    """Strip terminal control characters from untrusted text (model output, web content)."""
    return _CONTROL.sub("", text)


app = typer.Typer(no_args_is_help=True, help="THE WATCHTOWER — local agentic ecosystem.")
EXIT = {"done": 0, "failed": 1, "paused": 3}


def build_socket(settings: Settings, budget: Budget, audit: AuditLog) -> ModelSocket:
    return ModelSocket(settings, budget, audit)


def _open():
    try:
        settings = load_settings()
    except ValueError as e:  # e.g. a bad WATCHTOWER_WORK_MODEL: a clear message, not a traceback
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    return settings, connect(settings.db_path)


def make_sandbox(settings: Settings, conn) -> Sandbox:
    return Sandbox(settings, AuditLog(conn))


def _check_guardrails(settings: Settings) -> None:
    from watchtower.guardrails import GuardrailsError, load_guardrails
    try:
        load_guardrails(settings.home)
    except GuardrailsError as e:
        typer.echo(f"Error: {e} — fix or delete {settings.home / 'guardrails.yaml'}", err=True)
        raise typer.Exit(2)


def _runner(settings: Settings, conn) -> JobRunner:
    _check_guardrails(settings)
    audit = AuditLog(conn)
    bus = Bus(audit)
    socket = build_socket(settings, Budget(conn), audit)
    return JobRunner(settings, conn, socket, Scheduler(settings, ContextStore(conn), bus), bus,
                     sandbox=make_sandbox(settings, conn))


def _report(outcome: RunOutcome, conn) -> None:
    if outcome.status == "done":
        used = Budget(conn).usage(outcome.job_id)
        typer.echo(_clean(outcome.answer or ""))
        typer.echo(f"\n[job {outcome.job_id} · {used['used_tokens']} tokens · ${used['used_usd']:.4f}]")
    elif outcome.status == "paused":
        pending = Approvals(conn).pending_for(outcome.job_id)
        if pending:
            what = "App for job {} — awaiting your sign-off" if pending.kind == "signoff" else \
                "Spec for job {} — awaiting your approval"
            typer.echo("\n" + what.format(outcome.job_id) + ":\n")
            typer.echo(_clean(pending.summary))
            typer.echo(f"\nApprove with: watchtower approve {outcome.job_id}   (or add --reject)", err=True)
        else:
            typer.echo(_clean(f"Job {outcome.job_id} paused: {outcome.reason}"), err=True)
            typer.echo(f"Resume with: watchtower resume {outcome.job_id}", err=True)
    else:
        typer.echo(f"Job {outcome.job_id} failed: {outcome.reason}", err=True)
    raise typer.Exit(EXIT[outcome.status])


@app.command()
def ask(
    prompt: str,
    tier: str = typer.Option("small", help="Model tier: small | work | review"),
    max_tokens: Optional[int] = typer.Option(None, min=1, help="Token budget for this job"),
):
    """Quick question to one model (checkpointed plan → answer); no floors involved."""
    if not prompt.strip():
        typer.echo("Error: prompt must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = _open()
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


MAX_KNOWLEDGE_BYTES = 5 * 1024 * 1024
knowledge_app = typer.Typer(help="Local knowledge store (full-text search with sources).")
app.add_typer(knowledge_app, name="knowledge")


def ollama_status(settings: Settings) -> tuple[bool, str]:
    import httpx

    try:
        version = httpx.get(f"{settings.ollama_url}/api/version", timeout=3).json()["version"]
        names = {m["name"] for m in httpx.get(f"{settings.ollama_url}/api/tags", timeout=3).json()["models"]}
    except Exception:
        return False, "not reachable — open the Ollama app"
    missing = sorted({m.removeprefix("ollama/") for m in settings.tiers.values()} - names)
    if missing:
        return True, f"{version} · missing models: {', '.join(missing)} (ollama pull <name>)"
    return True, f"{version} · all tier models present"


def docker_status(settings: Settings, audit: AuditLog) -> tuple[bool, str]:
    problem = Sandbox(settings, audit).check()
    return (problem is None), (problem or f"ready ({settings.sandbox_image})")


def guardrails_status(settings: Settings) -> tuple[bool, str]:
    from watchtower.guardrails import GuardrailsError, load_guardrails
    try:
        g = load_guardrails(settings.home)
    except GuardrailsError as e:
        return False, str(e)
    owner = (settings.home / "guardrails.yaml").is_file()
    return True, f"{len(g.rules)} rules, {g.max_send_backs} send-backs ({'your copy' if owner else 'defaults'})"


def glass_status() -> tuple[bool, str]:
    """Every floor's glass rules file loads (a typo there would otherwise surface mid-job)."""
    from watchtower.beacon import glass as glass_mod
    for n in range(1, 6):
        try:
            glass_mod.load_glass_rules(f"f{n}", glass_mod.GLASS_DIR)
        except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
            return False, f"f{n}.yaml: {str(e)[:120]} (in {glass_mod.GLASS_DIR})"
    return True, "Glass 1–5 rules load"


def bandit_status() -> tuple[bool, str]:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return True, f"{version('bandit')} (offline security scanner)"
    except PackageNotFoundError:
        return False, "not installed; run: uv sync"


@app.command()
def doctor():
    """Check that the tower's engine parts are healthy."""
    settings, conn = _open()
    audit = AuditLog(conn)
    ram = free_ram_pct()
    checks = [
        ("Ollama", *ollama_status(settings)),
        ("Docker", *docker_status(settings, audit)),
        ("RAM", ram is None or ram >= settings.min_free_ram_pct,
         "unknown" if ram is None else f"{ram}% free (need {settings.min_free_ram_pct}%)"),
        ("Audit chain", audit.verify(), "ok" if audit.verify() else "BROKEN"),
        ("Bandit", *bandit_status()),
        ("Guardrails", *guardrails_status(settings)),
        ("Glass", *glass_status()),
    ]
    for name, ok, detail in checks:
        typer.echo(f"{'✓' if ok else '✗'} {name:<12} {detail}")
    raise typer.Exit(0 if all(ok for _, ok, _ in checks) else 1)


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
    _, conn = _open()
    src = source or path.resolve().as_uri()
    try:
        doc_id = Knowledge(conn).add(path.read_text(errors="replace"), src, title or path.name, trusted)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    AuditLog(conn).append("owner", "knowledge_added", {"doc_id": doc_id, "source": src, "trusted": trusted})
    typer.echo(f"Added document {doc_id} from {src}")


@knowledge_app.command("search")
def knowledge_search(query: str, limit: int = typer.Option(5, min=1, max=50)):
    """Search the knowledge store."""
    _, conn = _open()
    hits = Knowledge(conn).search(query, limit)
    if not hits:
        typer.echo("No matches.")
        return
    for h in hits:
        typer.echo(_clean(f"[{h.doc_id}] {h.title} — {h.source}{'' if h.trusted else ' (untrusted)'}"))
        typer.echo(f"    {_clean(h.snippet)}")


@app.command()
def run(
    idea: str,
    yes: bool = typer.Option(False, "--yes", help="Skip CPO questions and auto-approve the spec; you still sign off the app"),
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
    settings, conn = _open()
    _check_guardrails(settings)
    if app:  # an app job needs the sandbox: say so now, before any model work is spent
        typer.echo("Checking Docker…", err=True)
        ok, detail = docker_status(settings, AuditLog(conn))
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
                typer.echo(f"CPO could not ask questions ({type(e).__name__}: {e}); "
                           "continuing without questions.", err=True)
                questions = []
            try:
                for q in questions:
                    answers.append({"q": q, "a": typer.prompt(f"CPO asks: {_clean(q)}", default="",
                                                              show_default=False)})
            except (KeyboardInterrupt, click.exceptions.Abort):
                runner.release(job.id)
                JobStore(conn).set_status(job.id, "failed", "cancelled by owner during CPO questions")
                typer.echo(f"\nJob {job.id} cancelled.", err=True)
                raise typer.Exit(130)
        outcome = runner.start(job.id, extra={"answers": answers, "auto_approve": yes, "offline": offline,
                                                    "research": research})
    finally:
        runner.close()
    _report(outcome, conn)


@app.command()
def approve(job_id: str, reject: bool = typer.Option(False, "--reject", help="Reject instead (the spec, or the finished app)")):
    """Approve (or reject) what a job is waiting on — its spec or the finished app's sign-off — then resume it."""
    settings, conn = _open()
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
        typer.echo(f"Error: {e}", err=True)
        typer.echo(f"Approval recorded. Resume with: watchtower resume {job_id}", err=True)
        raise typer.Exit(2)
    finally:
        runner.close()
    _report(outcome, conn)


def make_beacon(settings: Settings, conn) -> Beacon:
    return Beacon(Search(), Fetcher(), Glass(load_glass_rules("f1")), Knowledge(conn), AuditLog(conn))


@app.command()
def beacon(query: str, pages: int = typer.Option(3, min=1, max=10)):
    """Search the web and add pages that pass Glass 1 to the knowledge store."""
    if not query.strip():
        typer.echo("Error: query must not be empty", err=True)
        raise typer.Exit(2)
    settings, conn = _open()
    audit = AuditLog(conn)
    before = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM audit_log").fetchone()[0]
    try:
        docs = make_beacon(settings, conn).research(query, None)
    except SearchUnavailable as e:
        typer.echo(f"Beacon paused: {e}", err=True)
        raise typer.Exit(3)
    for e in audit.since(before, actor="beacon"):
        if e.action in ("beacon_skip", "glass_reject"):
            why = e.detail.get("reason") or "; ".join(e.detail.get("reasons", []))
            typer.echo(_clean(f"✗ {e.detail.get('url')} — {why}"))
        elif e.action == "glass_pass":
            typer.echo(_clean(f"✓ {e.detail.get('url')}"))
    typer.echo(f"{len(docs)} page(s) added to knowledge (untrusted).")


def make_deployer(settings: Settings, conn) -> Deployer:
    return Deployer(settings, conn, AuditLog(conn))


def _deploy_call(fn, *args):
    try:
        return fn(*args)
    except DeployError as e:
        typer.echo(_clean(f"Deploy failed: {e}"), err=True)
        raise typer.Exit(1)


@app.command()
def deploy(job_id: str, name: str = typer.Option("app", "--name", help="Deployment name (slot)")):
    """Deploy a finished app job to local Docker: no internet for the app, reachable only on this Mac."""
    settings, conn = _open()
    job = JobStore(conn).get(job_id)
    if job is None or job.pipeline != "app" or job.status != "done":
        state = "unknown" if job is None else f"a {job.pipeline} job that is {job.status}"
        typer.echo(f"Error: job {job_id} is {state}; only finished app jobs (watchtower run) can be deployed", err=True)
        raise typer.Exit(2)
    d = _deploy_call(make_deployer(settings, conn).deploy, job_id, name)
    typer.echo(f"Deployed job {job_id} as '{d.name}' (deployment {d.id}): http://127.0.0.1:{d.port}\n"
               "Isolated: the app has no internet, is reachable only from this Mac, and its pages may only "
               "talk to the app itself (strict CSP). Links you click can still open other sites.\n"
               f"Stop it: watchtower undeploy {d.name}    Previous version: watchtower rollback {d.name}")


@app.command()
def rollback(name: str):
    """Go back to the previous deployment of NAME."""
    settings, conn = _open()
    d = _deploy_call(make_deployer(settings, conn).rollback, name)
    typer.echo(f"'{d.name}' rolled back to deployment {d.id} (job {d.job_id}): http://127.0.0.1:{d.port}")


@app.command()
def undeploy(name: str):
    """Stop and remove the running deployment NAME (images are kept for rollback)."""
    settings, conn = _open()
    _deploy_call(make_deployer(settings, conn).undeploy, name)
    typer.echo(f"'{name}' stopped.")


@app.command()
def deployments(limit: int = typer.Option(20, min=1, max=200)):
    """List deployments, newest first."""
    settings, conn = _open()
    for d in make_deployer(settings, conn).list(limit):
        typer.echo(f"{d.id:>4}  {d.name:<12} job {d.job_id}  127.0.0.1:{d.port}  {d.status:<11} {d.created_at}")
