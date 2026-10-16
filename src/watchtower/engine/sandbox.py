from __future__ import annotations

import json
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
LOG_BAD = "(app log missing or duplicated)"
_JOB_ID = re.compile(r"[A-Za-z0-9_-]+")


def capped_run(argv: list[str], *, timeout: float | None = None, limit: int = 4 * MAX_OUTPUT,
               **_ignored) -> subprocess.CompletedProcess:
    """subprocess.run(capture_output=True, text=True) that never holds more than `limit` bytes of either stream:
    one reader thread per pipe keeps only the tail. 8a (audit D-M2): AI code can print gigabytes inside its time
    limit; capture_output buffered all of it in the tower's memory. Broken UTF-8 is replaced, never raised.
    `.truncated` says whether any byte was dropped (review r2)."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tails = (bytearray(), bytearray())
    dropped = []

    def drain(stream, tail: bytearray) -> None:
        while chunk := stream.read1(65536):
            tail.extend(chunk)
            if len(tail) > limit:
                dropped.append(True)
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
    done = subprocess.CompletedProcess(argv, proc.returncode, out, err)
    done.truncated = bool(dropped)
    return done


class SandboxUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool = False  # review r2: output was cut to its tail; a result tag in it proves nothing


APP_UID, HARNESS_UID = 1001, 1000
# Review r3: one shared uid let the app ptrace the harness (or PID 1) and rewrite its result in memory. The
# container now starts as uid 0 with only SETUID/SETGID; drop() leaves uid 0 for good (all three ids, no groups,
# so the kernel clears every capability and marks the process non-dumpable).
_DROP = """\
def drop(uid):
    os.setgroups([])
    os.setresgid(uid, uid, uid)
    os.setresuid(uid, uid, uid)
"""

# Runs first in every container (as uid 0). It copies the workspace as the app uid, then drops any command to
# the app uid, except a tower harness: the harness starts the app itself (start() in EMIT), then drops to its own.
LAUNCH = "import os, sys\n" + f"APP_UID = {APP_UID}\n" + _DROP + """\
if os.fork() == 0:
    drop(APP_UID)
    os.execvp("cp", ["cp", "-a", "/src/.", "/work/"])
if os.wait()[1]:
    sys.exit(1)
if sys.argv[1] == "harness":
    os.environ["WT_SPLIT"] = "1"
else:
    drop(APP_UID)
os.execvp(sys.argv[2], sys.argv[2:])
"""

# Prepended to every in-sandbox harness (8a review r1). emit() writes each tower line on a fresh line in one
# write; js() writes "_" as _ inside the JSON, so no value (app log, page text, route path) can contain a tag:
# every tag in the output is either the harness's own or a forgery. fit() caps a variable-size line (review r2):
# "_" grows 6x, and an honest run cut off by MAX_OUTPUT now fails. start() runs the app under APP_UID and drops
# the harness to HARNESS_UID (review r3) when the sandbox says so (WT_SPLIT); without root that raises, so the
# harness fails instead of sharing its uid. Host tests run without WT_SPLIT. stop() may not reach an app of
# another uid: it dies with the container when the harness exits.
EMIT = "import json, os, subprocess, sys\n" + f"APP_UID, HARNESS_UID = {APP_UID}, {HARNESS_UID}\n" + _DROP + """\
def start(entry, port, log):
    split = os.environ.get("WT_SPLIT") == "1"
    ids = {"user": APP_UID, "group": APP_UID, "extra_groups": []} if split else {}
    env = {k: v for k, v in os.environ.items() if k != "WT_SPLIT"}
    p = subprocess.Popen([sys.executable, entry], env={**env, "PORT": port}, stdout=log,
                         stderr=subprocess.STDOUT, start_new_session=True, **ids)
    if split:
        drop(HARNESS_UID)
    return p
def stop(p):
    try:
        os.killpg(p.pid, 9)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
def js(value):
    return json.dumps(value, ensure_ascii=False).replace("_", "\\\\u005f")
def fit(value, cap, key=None):
    text = js(value)
    while len(text) > cap:
        part = value[key] if key else value
        if len(part) <= 1:
            return text
        keep = len(part) * 3 // 4
        part = part[len(part) - keep:] if isinstance(part, str) else part[:keep]
        value = {**value, key: part} if key else part
        text = js(value)
    return text
def emit(tag, text):
    sys.stdout.flush()
    sys.stdout.write("\\n" + tag + " " + text + "\\n")
    sys.stdout.flush()
"""


def tagged(output: str, tag: str) -> str | None:
    """The rest of the line after `tag`, only when `tag` appears exactly once anywhere in the output (8a review r1).
    Counted as a substring, never as a line start: an anchored match missed the real line spliced after a forged
    one, so the forgery was the only match."""
    if output.count(tag) != 1:
        return None
    rest = output[output.index(tag) + len(tag):]
    return rest[1:].split("\n", 1)[0] if rest.startswith(" ") else None


def result_tag(result: SandboxResult, tag: str) -> str | None:
    """`tagged` over the whole output, never over a cut-off one (review r2): the app can setsid out of killpg's
    reach, write a forged tag to the harness's stderr, then flood its stdout until the real line falls out of the
    kept tail. Counting needs both tags present, so a cut-off output never counts."""
    return None if result.truncated else tagged((result.stdout or "") + (result.stderr or ""), tag)


def result_log(result: SandboxResult, tag: str, missing: str) -> str:
    """The app's JSON log line, read like a result tag (review r2): the app could add its own log line after the
    real one and show the coder and the gate a fake. `missing` when no line; a note when doubled or cut off."""
    if tag not in (result.stdout or "") + (result.stderr or ""):
        return missing
    found = result_tag(result, tag)
    try:
        return str(json.loads(found)) if found is not None else LOG_BAD
    except ValueError:
        return LOG_BAD


def _is_harness(command: list[str]) -> bool:
    """A tower harness: `python -I -c <script>` whose script starts with EMIT. Only tower code builds commands."""
    return command[:3] == ["python", "-I", "-c"] and len(command) > 3 and command[3].startswith(EMIT)


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
            "--cap-drop", "ALL", "--cap-add", "SETUID", "--cap-add", "SETGID",  # review r3: LAUNCH splits uids
            "--security-opt", "no-new-privileges", "--user", "0:0",
            "-v", f"{workspace}:/src:ro", "--tmpfs", f"/work:rw,size=64m,uid={APP_UID},gid={APP_UID}", "-w", "/work",
            self._s.sandbox_image,
            # hard limit inside the container, so it dies even if the host-side kill misses it
            "timeout", "-s", "KILL", str(max(1, int(timeout))),
            "python", "-I", "-c", LAUNCH, "harness" if _is_harness(command) else "app", *command,
        ]
        self._audit.append("sandbox", "sandbox_run", {"program": command[0], "argc": len(command)}, job_id)
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=timeout)
            if proc.returncode == 125 and (proc.stderr or "").lstrip().startswith("docker:"):
                problem = proc.stderr.strip().splitlines()[0]
                self._audit.append("sandbox", "sandbox_unavailable", {"error": problem[:200]}, job_id)
                raise SandboxUnavailable(f"{problem}; fix Docker, then resume")
            out, err = proc.stdout or "", proc.stderr or ""
            cut = getattr(proc, "truncated", False) is True or max(len(out), len(err)) > MAX_OUTPUT
            result = SandboxResult(proc.returncode, out[-MAX_OUTPUT:], err[-MAX_OUTPUT:], False, cut)
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
