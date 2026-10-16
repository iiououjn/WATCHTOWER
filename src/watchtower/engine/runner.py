from __future__ import annotations

import fcntl
import signal
import sqlite3
import threading
import traceback
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator

from watchtower.config import Settings
from watchtower.beacon.beacon import Beacon
from watchtower.beacon.fetcher import Fetcher
from watchtower.beacon.glass import Glass, load_glass_rules
from watchtower.beacon.search import Search, SearchUnavailable
from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.governor.approvals import Approvals
from watchtower.engine.governor.budget import BudgetExceeded
from watchtower.engine.jobs import JobStore
from watchtower.engine.knowledge import Knowledge
from watchtower.engine.model_socket import BadModelOutput, CloudDisabled, LowMemory, ModelSocket, ModelUnavailable
from watchtower.tower import NeedsOwner, SpecRejected, TowerPipeline
from watchtower.floors.f4_qa_deploy.releases import Releases
from watchtower.guardrails import load_guardrails
from watchtower.engine.sandbox import Sandbox, SandboxUnavailable
from watchtower.engine.scheduler import Scheduler, SchedulerBusy
from watchtower.engine.workflow import Step, Workflow, WorkflowResult
from watchtower.roles import Role, load_roles

PLAN_PROMPT = (
    "Write a short numbered plan (max 3 steps) for answering this request. "
    "Do not answer it yet.\n\nRequest: {prompt}"
)
ANSWER_PROMPT = "Request: {prompt}\n\nPlan:\n{plan}\n\nFollow the plan and answer the request concisely."
PAUSE_ERRORS = (ModelUnavailable, LowMemory, SchedulerBusy, SandboxUnavailable, BadModelOutput, NeedsOwner,
                SearchUnavailable)
FAIL_ERRORS = (BudgetExceeded, CloudDisabled, SpecRejected)
STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)  # kill, launchd stop, closing the terminal


class Terminated(BaseException):  # a BaseException, like KeyboardInterrupt: no floor's `except Exception` eats it
    pass


def _lock_path(home: Path, job_id: str) -> Path:
    return home / "jobs" / f"{job_id}.lock"


def owner_alive(home: Path, job_id: str) -> bool:
    """Is a process holding this job's lock? The kernel drops a flock when its process dies (even SIGKILL),
    so a 'running' job whose lock is free has no owner: it crashed and can be resumed."""
    path = _lock_path(home, job_id)
    if not path.exists():
        return False
    with open(path, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


@contextmanager
def _stop_signals_pause() -> Iterator[None]:
    """SIGTERM/SIGHUP during a run raise Terminated, which pauses the job (signal handlers: main thread only)."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def stop(signum, frame):
        raise Terminated(f"terminated by {signal.Signals(signum).name}")
    # a signal the parent ignores (`nohup`) stays ignored: the owner chose to outlive the terminal
    previous = {s: signal.signal(s, stop) for s in STOP_SIGNALS if signal.getsignal(s) is not signal.SIG_IGN}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


@dataclass(frozen=True)
class RunOutcome:
    job_id: str
    status: str
    answer: str | None
    reason: str | None


class JobRunner:
    """Runs a job as a checkpointed plan → answer workflow and decides paused vs failed."""

    def __init__(self, settings: Settings, conn: sqlite3.Connection, socket: ModelSocket,
                 scheduler: Scheduler, bus: Bus, beacon_factory=None, sandbox=None):
        self._jobs = JobStore(conn)
        self._socket = socket
        self._scheduler = scheduler
        self._bus = bus
        self._home = settings.home
        self._lock_dir = settings.home / "jobs"
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        if beacon_factory is None and settings.online:
            def beacon_factory(ask, floor="f1"):  # each floor sees the web only through its own glass
                return Beacon(Search(), Fetcher(), Glass(load_glass_rules(floor), ask), Knowledge(conn),
                              AuditLog(conn), max_pages=3 if floor == "f1" else 2, consistency=floor == "f1")
        self._tower = TowerPipeline(self._ask_role, load_roles(tiers=settings.tiers), Approvals(conn), bus,
                                    Knowledge(conn), beacon_factory=beacon_factory,
                                    sandbox=sandbox or Sandbox(settings, AuditLog(conn)), releases=Releases(conn),
                                    guardrails=load_guardrails(settings.home), before_sandbox=getattr(socket, "make_room", None))
        checkpoints = settings.home / "checkpoints.db"
        self._wfs = {
            "demo": Workflow([Step("plan", self._plan), Step("answer", self._answer)], checkpoints,
                             should_pause=self._jobs.pause_requested),
            "tower": Workflow(self._tower.steps(), checkpoints, should_pause=self._jobs.pause_requested),
            "app": Workflow(self._tower.app_steps(), checkpoints, should_pause=self._jobs.pause_requested),
        }

    def start(self, job_id: str, tier: str = "small", extra: dict | None = None) -> RunOutcome:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        data = {"job_id": job_id, "prompt": job.prompt, "tier": tier, **(extra or {})}
        wf = self._wfs[job.pipeline]
        with self._job_lock(job_id):
            def go() -> WorkflowResult:
                self._jobs.set_status(job_id, "running")
                self._bus.publish("job.started", {"tier": tier, "pipeline": job.pipeline}, job_id)
                return wf.run(job_id, data)
            return self._drive(job_id, go)

    def resume(self, job_id: str, force: bool = False) -> RunOutcome:
        """Resume from the last finished step. A 'running' job is accepted only once its lock is ours: the
        kernel freed it, so its process died (kill -9, power loss, OOM). force is kept for old scripts."""
        if self._jobs.get(job_id) is None:
            raise KeyError(job_id)
        with self._job_lock(job_id):  # lock first: a held lock means a live owner, never a crash
            job = self._jobs.get(job_id)
            if job.status not in {"paused", "running"}:
                raise ValueError(f"job {job_id} is {job.status}; only paused jobs can be resumed")

            def go() -> WorkflowResult:
                self._jobs.clear_pause(job_id)
                if job.status == "running":
                    self._bus.publish("job.recovered", {"reason": "its process died (job lock was free)"}, job_id)
                self._jobs.set_status(job_id, "running")
                self._bus.publish("job.resumed", {}, job_id)
                return self._wfs[job.pipeline].resume(job_id)
            return self._drive(job_id, go)

    def close(self) -> None:
        for wf in self._wfs.values():
            wf.close()

    @contextmanager
    def _job_lock(self, job_id: str) -> Iterator[None]:
        """One process per job. The kernel drops the lock if the process dies, so a free
        lock on a 'running' job means its process is gone."""
        handle = open(_lock_path(self._home, job_id), "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise ValueError(f"job {job_id} is running in another process") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()

    def _drive(self, job_id: str, go) -> RunOutcome:
        try:
            with _stop_signals_pause():
                result: WorkflowResult = go()
        except PAUSE_ERRORS as e:
            return self._end(job_id, "paused", str(e))
        except KeyboardInterrupt:
            return self._end(job_id, "paused", "interrupted by owner")
        except Terminated as e:
            return self._end(job_id, "paused", f"{e}; resume it")
        except FAIL_ERRORS as e:
            return self._end(job_id, "failed", str(e))
        except Exception as e:  # 8b (A-F9): the checkpoint is intact, so an unknown error pauses and resume retries
            self._record_error(job_id, e)
            return self._end(job_id, "paused", f"unexpected error: {type(e).__name__}: {str(e)[:200]}")
        if result.status == "paused":
            return self._end(job_id, "paused", result.reason)
        return self._end(job_id, "done", None, result.data.get("answer"))

    def _record_error(self, job_id: str, error: Exception) -> None:
        """Where the tower's own code raised (the last frame inside the package), for the owner and the audit."""
        frames = traceback.extract_tb(error.__traceback__)
        frame = ([f for f in frames if "/watchtower/" in f.filename] or frames or [None])[-1]
        where = f"{frame.filename.rsplit('/watchtower/', 1)[-1]}:{frame.lineno}" if frame else "?"
        try:
            self._bus.publish("job.error", {"type": type(error).__name__, "error": str(error)[:300], "where": where},
                              job_id)
        except Exception:  # noqa: BLE001 — recording must never replace the error being reported
            pass

    def _end(self, job_id: str, status: str, reason: str | None, answer: str | None = None) -> RunOutcome:
        # record the outcome first, so a second Ctrl-C during cleanup cannot leave the job 'running'
        self._jobs.set_status(job_id, status, reason)
        try:
            self._bus.publish(f"job.{status}", {"reason": reason} if reason else {}, job_id)
        except Exception:  # noqa: BLE001 — the status row is right; a locked bus must not hide the outcome
            pass
        try:
            self._socket.unload_all(job_id)
        except (Exception, KeyboardInterrupt):  # noqa: BLE001 — best effort: the outcome is already recorded
            pass
        return RunOutcome(job_id, status, answer, reason)

    def release(self, job_id: str) -> None:
        """Free the model this process loaded (for paths that end outside a workflow run)."""
        self._socket.unload_all(job_id)

    def cpo_questions(self, job_id: str) -> list[str]:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return self._tower.questions({"job_id": job_id, "prompt": job.prompt})

    def _ask_role(self, role: Role, data: dict, prompt: str) -> dict:
        with self._scheduler.agent(role.id, data["job_id"]) as session:
            messages = [{"role": "system", "content": role.system}, {"role": "user", "content": prompt}]
            ask = self._socket.ask_files if role.reply == "files" else self._socket.ask_json
            out = ask(role.tier, messages, data["job_id"])
            session.context["messages"] = messages + [{"role": "assistant", "content": str(out)}]
            return out

    def _ask(self, agent_id: str, data: dict, content: str) -> str:
        with self._scheduler.agent(agent_id, data["job_id"]) as session:
            session.context["messages"] = [{"role": "user", "content": content}]
            reply = self._socket.ask(data["tier"], session.context["messages"], data["job_id"])
            session.context["messages"].append({"role": "assistant", "content": reply.text})
            return reply.text

    def _plan(self, data: dict) -> dict:
        return {"plan": self._ask("ground.planner", data, PLAN_PROMPT.format(prompt=data["prompt"]))}

    def _answer(self, data: dict) -> dict:
        content = ANSWER_PROMPT.format(prompt=data["prompt"], plan=data["plan"])
        return {"answer": self._ask("ground.answerer", data, content)}
