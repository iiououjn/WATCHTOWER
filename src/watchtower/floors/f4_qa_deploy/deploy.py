from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchtower.config import Settings
from watchtower.engine.db import now
from watchtower.floors.f4_qa_deploy.deploy_scripts import EDGE, FORWARD
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.governor.audit import AuditLog
from watchtower.floors.f4_qa_deploy.releases import Releases

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,29}")
_JOB = re.compile(r"[A-Za-z0-9_-]+")
_ENTRY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_/]*\.py")
PORTS = range(8100, 8200)
KEEP_IMAGES = 3

DOCKERFILE = """\
FROM {image}
COPY --chown=1000:1000 app/ /app/
COPY forward.py /opt/wt/forward.py
WORKDIR /app
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1
CMD {cmd}
"""


class DeployError(Exception):
    pass


@dataclass(frozen=True)
class Deployment:
    id: int
    name: str
    job_id: str
    image: str
    port: int
    status: str
    created_at: str
    ended_at: str | None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # never let the app steer the host to another URL


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def http_ok(port: int, wait: float = 15.0) -> bool:
    """True once GET / on the local port answers 2xx/3xx. Redirects are never followed, no proxies used."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            with _OPENER.open(f"http://127.0.0.1:{port}/", timeout=2) as r:
                if 200 <= r.status < 400:
                    return True
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class Deployer:
    """Deploys a released app to local Docker: built offline from exactly the QA'd files, run on an internal
    network (no internet), reachable only through a fixed proxy on 127.0.0.1. A failed health check restores
    the previous deployment of the same name."""

    def __init__(self, settings: Settings, conn: sqlite3.Connection, audit: AuditLog,
                 run: Callable = subprocess.run, health: Callable[[int], bool] = http_ok,
                 port_free: Callable[[int], bool] = port_free):
        self._s, self._conn, self._audit = settings, conn, audit
        self._run, self._health, self._port_free = run, health, port_free
        self._releases = Releases(conn)

    def deploy(self, job_id: str, name: str = "app") -> Deployment:
        if not _NAME.fullmatch(name or ""):
            raise DeployError("name must be 1-30 lowercase letters, digits or '-'")
        if not _JOB.fullmatch(job_id or ""):
            raise DeployError(f"invalid job id {job_id!r}")
        release = self._releases.get(job_id)
        if release is None:
            raise DeployError(f"job {job_id} has no release: only apps that passed QA can be deployed")
        if not Approvals(self._conn).signed_off(job_id):  # 8a (D-M1): e.g. released by --yes before 8a
            raise DeployError(f"job {job_id} has no owner sign-off; read the app, then approve it before deploying")
        root = self._s.home / "workspaces" / job_id
        problems = self._releases.verify(job_id, root)
        if problems:
            raise DeployError("workspace differs from what passed QA: " + "; ".join(problems[:5]))
        if not _ENTRY.fullmatch(release.entry) or ".." in release.entry.split("/"):
            raise DeployError(f"unsafe entry {release.entry!r}")
        previous = self._active(name)
        port = previous.port if previous else self._pick_port(name)
        dep_id = self._conn.execute(
            "INSERT INTO deployments(name, job_id, image, port, status, created_at) VALUES (?,?,?,?,?,?)",
            (name, job_id, "", port, "building", now())).lastrowid
        image = f"wt-app-{name}:{dep_id}"
        self._conn.execute("UPDATE deployments SET image=? WHERE id=?", (image, dep_id))
        self._audit.append("owner", "deploy_started", {"name": name, "image": image, "port": port}, job_id)
        try:  # a failed build never touched the running deployment: leave it alone
            self._build(release, root, image)
        except BaseException as e:
            self._end(dep_id, "failed")
            if isinstance(e, OSError):
                raise DeployError(f"could not prepare the build: {type(e).__name__}") from e
            raise
        try:
            self._start(name, image, port)
        except DeployError as e:
            self._end(dep_id, "failed")
            raise DeployError(f"{e}{self._restore(name, previous)}") from e
        if not self._health(port):
            self._end(dep_id, "failed")
            self._audit.append("system", "deploy_unhealthy", {"name": name, "image": image}, job_id)
            raise DeployError(f"health check failed (no HTTP 200 on GET /){self._restore(name, previous)}")
        if previous:
            self._end(previous.id, "replaced")
        self._conn.execute("UPDATE deployments SET status='active' WHERE id=?", (dep_id,))
        self._audit.append("system", "deploy_active", {"name": name, "image": image, "port": port}, job_id)
        self._prune(name)
        return self._get(dep_id)

    def rollback(self, name: str) -> Deployment:
        current = self._active(name)
        rows = [] if current is None else self._conn.execute(
            "SELECT id FROM deployments WHERE name=? AND status='replaced' AND id<? ORDER BY id DESC",
            (name, current.id)).fetchall()
        target = next((self._get(r["id"]) for r in rows if self._image_exists(self._get(r["id"]).image)), None)
        if target is None:  # checked before anything is stopped
            raise DeployError(f"nothing to roll back to for {name!r}")
        try:
            self._start(name, target.image, current.port)
            healthy, why = self._health(current.port), "failed its health check"
        except DeployError as e:
            healthy, why = False, f"did not start ({e})"
        if not healthy:
            raise DeployError(f"deployment {target.id} {why}{self._restore(name, current)}")
        self._end(current.id, "rolled_back")
        self._conn.execute("UPDATE deployments SET status='active', port=?, ended_at=NULL WHERE id=?",
                           (current.port, target.id))
        self._audit.append("owner", "deploy_rolled_back", {"name": name, "to": target.id}, target.job_id)
        return self._get(target.id)

    def undeploy(self, name: str) -> None:
        current = self._active(name)
        if current is None:
            raise DeployError(f"nothing is deployed as {name!r}")
        self._stop(name, strict=True)  # only report "stopped" once Docker really removed it
        self._docker(["docker", "network", "rm", f"wt-dep-{name}"], quiet=True)
        self._end(current.id, "stopped")
        self._audit.append("owner", "deploy_stopped", {"name": name}, current.job_id)

    def list(self, limit: int = 20) -> list[Deployment]:
        rows = self._conn.execute("SELECT * FROM deployments ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [Deployment(**dict(r)) for r in rows]

    # -- docker steps -------------------------------------------------------------------------------------

    def _build(self, release, root: Path, image: str) -> None:
        with tempfile.TemporaryDirectory(prefix="wt-deploy-") as tmp:
            ctx = Path(tmp)
            for rel, digest in release.manifest.items():
                dest = ctx / "app" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / rel, dest, follow_symlinks=False)
                if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:  # changed between verify and copy
                    raise DeployError(f"{rel} changed during deploy")
            (ctx / "forward.py").write_text(FORWARD)
            cmd = json.dumps(["python", "/opt/wt/forward.py", "9000", "127.0.0.1", "8000", release.entry])
            (ctx / "Dockerfile").write_text(DOCKERFILE.format(image=self._s.sandbox_image, cmd=cmd))
            self._docker(["docker", "build", "-q", "--pull=false", "--network", "none", "-t", image, str(ctx)],
                         timeout=300)

    def _start(self, name: str, image: str, port: int) -> None:
        net, app, edge = f"wt-dep-{name}", f"wt-dep-{name}-app", f"wt-dep-{name}-edge"
        self._stop(name)
        created = self._docker(["docker", "network", "create", "--internal", net], quiet=True)
        if created.returncode != 0 and "already exists" not in (created.stderr or ""):
            raise DeployError(_first_line(created.stderr))
        locked = ["--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "1000:1000",
                  "--pids-limit", "64", "--restart", "unless-stopped", "--label", f"watchtower.deploy={name}"]
        self._docker(["docker", "run", "-d", "--name", app, "--pull", "never", "--network", net,
                      "--network-alias", "app", "--tmpfs", "/tmp:rw,size=64m", "--memory", "256m", "--cpus", "1",
                      *locked, image])
        self._docker(["docker", "run", "-d", "--name", edge, "--pull", "never", "--memory", "64m",
                      "-p", f"127.0.0.1:{port}:8000", *locked, self._s.sandbox_image,
                      "python", "-c", EDGE, "8000", "app", "9000"])
        self._docker(["docker", "network", "connect", net, edge])

    def _stop(self, name: str, strict: bool = False) -> None:
        argv = ["docker", "rm", "-f", f"wt-dep-{name}-app", f"wt-dep-{name}-edge"]
        if not strict:
            self._docker(argv, quiet=True)
            return
        try:
            self._docker(argv)
        except DeployError as e:
            if "No such container" not in str(e):
                raise

    def _image_exists(self, image: str) -> bool:
        return bool(image) and self._docker(["docker", "image", "inspect", image], quiet=True).returncode == 0

    def _restore(self, name: str, previous: Deployment | None) -> str:
        """After a failed deploy: bring the previous deployment back, or leave nothing running."""
        self._stop(name)
        if previous is None:
            self._docker(["docker", "network", "rm", f"wt-dep-{name}"], quiet=True)
            return "; nothing to roll back to, app stopped"
        try:
            self._start(name, previous.image, previous.port)
        except DeployError as e:
            self._stop(name)  # no half-started containers left to restart forever
            self._docker(["docker", "network", "rm", f"wt-dep-{name}"], quiet=True)
            self._end(previous.id, "failed")
            return f"; restoring deployment {previous.id} also failed: {e}"
        if not self._health(previous.port):
            return f"; restored deployment {previous.id} is not answering yet: check http://127.0.0.1:{previous.port}"
        return f"; rolled back to deployment {previous.id}"

    def _prune(self, name: str) -> None:
        """Failed images go at once; keep the newest KEEP_IMAGES that rollback can still use."""
        rows = self._conn.execute("SELECT image, status FROM deployments WHERE name=? AND status!='active' "
                                  "ORDER BY id DESC", (name,)).fetchall()
        kept = 0
        for row in rows:
            if row["status"] in ("replaced", "rolled_back", "stopped") and kept < KEEP_IMAGES:
                kept += 1
            elif row["image"]:
                self._docker(["docker", "rmi", row["image"]], quiet=True)

    def _docker(self, argv: list[str], quiet: bool = False, timeout: float = 60) -> subprocess.CompletedProcess:
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as e:
            if quiet:  # best-effort cleanup must never hide the real error
                return subprocess.CompletedProcess(argv, 1, "", str(e))
            raise DeployError(f"Docker is not responding ({type(e).__name__}); start Docker Desktop") from e
        if proc.returncode != 0 and not quiet:
            raise DeployError(_first_line(proc.stderr))
        return proc

    # -- records ------------------------------------------------------------------------------------------

    def _pick_port(self, name: str) -> int:
        row = self._conn.execute("SELECT port FROM deployments WHERE name=? ORDER BY id DESC LIMIT 1",
                                 (name,)).fetchone()
        taken = {r["port"] for r in self._conn.execute(
            "SELECT port FROM deployments WHERE status='active' AND name!=?", (name,))}
        candidates = ([row["port"]] if row else []) + list(PORTS)
        for port in candidates:
            if port not in taken and self._port_free(port):
                return port
        raise DeployError(f"no free port in {PORTS.start}-{PORTS.stop - 1}")

    def _active(self, name: str) -> Deployment | None:
        row = self._conn.execute("SELECT id FROM deployments WHERE name=? AND status='active' ORDER BY id DESC LIMIT 1",
                                 (name,)).fetchone()
        return self._get(row["id"]) if row else None

    def _get(self, dep_id: int) -> Deployment:
        return Deployment(**dict(self._conn.execute("SELECT * FROM deployments WHERE id=?", (dep_id,)).fetchone()))

    def _end(self, dep_id: int, status: str) -> None:
        self._conn.execute("UPDATE deployments SET status=?, ended_at=? WHERE id=?", (status, now(), dep_id))


def _first_line(text: str | None) -> str:
    lines = (text or "").strip().splitlines()
    return (lines[0] if lines else "docker failed")[:300]
