from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog

MAX_OUTPUT = 20_000
_JOB_ID = re.compile(r"[A-Za-z0-9_-]+")


class SandboxUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Sandbox:
    """Runs agent code in a locked-down Docker container. Only the job's own workspace
    (~/.watchtower/workspaces/<job>) is mounted — never the owner's files."""

    def __init__(self, settings: Settings, audit: AuditLog, run: Callable = subprocess.run):
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
        inspect = self._run(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=15)
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
            "-v", f"{workspace}:/work:rw", "-w", "/work",
            self._s.sandbox_image, *command,
        ]
        self._audit.append("sandbox", "sandbox_run", {"command": command[:20]}, job_id)
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=timeout)
            result = SandboxResult(proc.returncode, (proc.stdout or "")[-MAX_OUTPUT:],
                                   (proc.stderr or "")[-MAX_OUTPUT:], False)
        except subprocess.TimeoutExpired:
            self._kill(name)
            result = SandboxResult(124, "", f"timed out after {timeout}s", True)
        self._audit.append("sandbox", "sandbox_result",
                           {"exit_code": result.exit_code, "timed_out": result.timed_out}, job_id)
        return result

    def _kill(self, name: str) -> None:
        try:
            self._run(["docker", "kill", name], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
