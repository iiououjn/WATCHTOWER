from __future__ import annotations

import re
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog

MAX_OUTPUT = 20_000
_JOB_ID = re.compile(r"[A-Za-z0-9_-]+")


def capped_run(argv: list[str], *, timeout: float | None = None, limit: int = 4 * MAX_OUTPUT,
               **_ignored) -> subprocess.CompletedProcess:
    """subprocess.run(capture_output=True, text=True) that never holds more than `limit` bytes of either stream:
    one reader thread per pipe keeps only the tail. 8a (audit D-M2): AI code can print gigabytes inside its time
    limit; capture_output buffered all of it in the tower's memory. Broken UTF-8 is replaced, never raised."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tails = (bytearray(), bytearray())

    def drain(stream, tail: bytearray) -> None:
        while chunk := stream.read1(65536):
            tail.extend(chunk)
            del tail[:-limit]

    pipes = zip((proc.stdout, proc.stderr), tails)
    readers = [threading.Thread(target=drain, args=pair, daemon=True) for pair in pipes]
    for reader in readers:
        reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        for reader in readers:
            reader.join(5)
        proc.stdout.close()
        proc.stderr.close()
    out, err = (bytes(tail).decode("utf-8", errors="replace") for tail in tails)
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


class SandboxUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Sandbox:
    """Runs agent code in a locked-down Docker container. The job's workspace is mounted READ-ONLY and
    copied into a 64 MB in-memory scratch dir, so executed code can never change, plant or fill files on
    the host — only the checked Workspace writer does that. The owner's files are never mounted."""

    def __init__(self, settings: Settings, audit: AuditLog, run: Callable = capped_run):
        self._s = settings
        self._audit = audit
        self._run = run

    def workspace(self, job_id: str) -> Path:
        if not _JOB_ID.fullmatch(job_id or ""):
            raise ValueError(f"invalid job id {job_id!r}")
        path = self._s.home / "workspaces" / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def check(self) -> str | None:
        """Return what is wrong with Docker, or None if the sandbox is ready."""
        image = self._s.sandbox_image
        try:
            info = self._run(["docker", "info", "--format", "{{.ServerVersion}}"],
                             capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return "Docker is not installed or not responding; install/start Docker Desktop, then resume"
        if info.returncode != 0:
            return "Docker is not running; start Docker Desktop, then resume"
        try:
            inspect = self._run(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return "Docker is not responding; restart Docker Desktop, then resume"
        if inspect.returncode != 0:
            return f"sandbox image {image} is missing; run: docker pull {image}"
        return None

    def run(self, job_id: str, command: list[str], timeout: float = 60.0) -> SandboxResult:
        if not command:
            raise ValueError("command must not be empty")
        workspace = self.workspace(job_id)
        problem = self.check()
        if problem:
            raise SandboxUnavailable(problem)
        name = f"wt-{job_id}-{uuid.uuid4().hex[:8]}"
        argv = [
            "docker", "run", "--rm", "--name", name, "--pull", "never",
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=64m",
            "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "1000:1000",
            "-v", f"{workspace}:/src:ro", "--tmpfs", "/work:rw,size=64m,uid=1000,gid=1000", "-w", "/work",
            self._s.sandbox_image,
            # hard limit inside the container, so it dies even if the host-side kill misses it
            "timeout", "-s", "KILL", str(max(1, int(timeout))),
            "sh", "-c", 'cp -a /src/. /work/ && exec "$@"', "sh", *command,
        ]
        self._audit.append("sandbox", "sandbox_run", {"program": command[0], "argc": len(command)}, job_id)
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=timeout)
            if proc.returncode == 125 and (proc.stderr or "").lstrip().startswith("docker:"):
                problem = proc.stderr.strip().splitlines()[0]
                self._audit.append("sandbox", "sandbox_unavailable", {"error": problem[:200]}, job_id)
                raise SandboxUnavailable(f"{problem}; fix Docker, then resume")
            result = SandboxResult(proc.returncode, (proc.stdout or "")[-MAX_OUTPUT:],
                                   (proc.stderr or "")[-MAX_OUTPUT:], False)
        except subprocess.TimeoutExpired:
            self._kill(name)
            result = SandboxResult(124, "", f"timed out after {timeout}s", True)
        self._audit.append("sandbox", "sandbox_result",
                           {"exit_code": result.exit_code, "timed_out": result.timed_out}, job_id)
        return result

    def _kill(self, name: str) -> None:
        """Stop a timed-out container; if kill misses it (not registered yet), force-remove it."""
        for argv in (["docker", "kill", name], ["docker", "rm", "-f", name]):
            try:
                if self._run(argv, capture_output=True, text=True, timeout=15).returncode == 0:
                    return
            except (OSError, subprocess.SubprocessError):
                pass
