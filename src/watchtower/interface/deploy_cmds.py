"""deploy, rollback, undeploy and deployments: finished apps on local Docker (8d: split out of cli.py)."""
from __future__ import annotations

import typer

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.jobs import JobStore
from watchtower.floors.f4_qa_deploy.deploy import DeployError, Deployer
from watchtower.interface.shell import app, clean, open_db


def make_deployer(settings: Settings, conn) -> Deployer:
    return Deployer(settings, conn, AuditLog(conn))


def _deploy_call(fn, *args):
    try:
        return fn(*args)
    except DeployError as e:
        typer.echo(clean(f"Deploy failed: {e}"), err=True)
        raise typer.Exit(1) from None


@app.command()
def deploy(job_id: str, name: str = typer.Option("app", "--name", help="Deployment name (slot)")):
    """Deploy a finished app job to local Docker: no internet for the app, reachable only on this Mac."""
    settings, conn = open_db()
    job = JobStore(conn).get(job_id)
    if job is None or job.pipeline != "app" or job.status != "done":
        state = "unknown" if job is None else f"a {job.pipeline} job that is {job.status}"
        typer.echo(f"Error: job {job_id} is {state}; only finished app jobs (watchtower run) can be deployed",
                   err=True)
        raise typer.Exit(2)
    d = _deploy_call(make_deployer(settings, conn).deploy, job_id, name)
    typer.echo(f"Deployed job {job_id} as '{d.name}' (deployment {d.id}): http://127.0.0.1:{d.port}\n"
               "Isolated: the app has no internet, is reachable only from this Mac, and its pages may only "
               "talk to the app itself (strict CSP). Links you click can still open other sites.\n"
               f"Stop it: watchtower undeploy {d.name}    Previous version: watchtower rollback {d.name}")


@app.command()
def rollback(name: str):
    """Go back to the previous deployment of NAME."""
    settings, conn = open_db()
    d = _deploy_call(make_deployer(settings, conn).rollback, name)
    typer.echo(f"'{d.name}' rolled back to deployment {d.id} (job {d.job_id}): http://127.0.0.1:{d.port}")


@app.command()
def undeploy(name: str):
    """Stop and remove the running deployment NAME (images are kept for rollback)."""
    settings, conn = open_db()
    _deploy_call(make_deployer(settings, conn).undeploy, name)
    typer.echo(f"'{name}' stopped.")


@app.command()
def deployments(limit: int = typer.Option(20, min=1, max=200)):
    """List deployments, newest first."""
    settings, conn = open_db()
    for d in make_deployer(settings, conn).list(limit):
        typer.echo(f"{d.id:>4}  {d.name:<12} job {d.job_id}  127.0.0.1:{d.port}  {d.status:<11} {d.created_at}")
