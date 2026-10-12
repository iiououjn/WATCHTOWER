from __future__ import annotations

import fcntl
import sqlite3
from contextlib import contextmanager
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
        self._lock_dir = settings.home / "jobs"
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        if beacon_factory is None and settings.online:
            def beacon_factory(ask, floor="f1"):  # each floor sees the web only through its own glass
                return Beacon(Search(), Fetcher(), Glass(load_glass_rules(floor), ask), Knowledge(conn),
                              AuditLog(conn), max_pages=3 if floor == "f1" else 2)
        self._tower = TowerPipeline(self._ask_role, load_roles(tiers=settings.tiers), Approvals(conn), bus,
                                    Knowledge(conn), beacon_factory=beacon_factory,
                                    sandbox=sandbox or Sandbox(settings, AuditLog(conn)), releases=Releases(conn),
                                    guardrails=load_guardrails(settings.home))
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
            self._jobs.set_status(job_id, "running")
            self._bus.publish("job.started", {"tier": tier, "pipeline": job.pipeline}, job_id)
            return self._drive(job_id, lambda: wf.run(job_id, data))

    def resume(self, job_id: str, force: bool = False) -> RunOutcome:
        """Resume from the last finished step. force=True also accepts a job stuck in
        'running' after power loss or kill -9 (the owner asserts its process is gone)."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        allowed = {"paused", "running"} if force else {"paused"}
        if job.status not in allowed:
            hint = " (use --force if its process died)" if job.status == "running" else ""
            raise ValueError(f"job {job_id} is {job.status}; only paused jobs can be resumed{hint}")
        with self._job_lock(job_id):
            self._jobs.clear_pause(job_id)
            self._jobs.set_status(job_id, "running")
            self._bus.publish("job.resumed", {}, job_id)
            return self._drive(job_id, lambda: self._wfs[job.pipeline].resume(job_id))

    def close(self) -> None:
        for wf in self._wfs.values():
            wf.close()

    @contextmanager
    def _job_lock(self, job_id: str) -> Iterator[None]:
        """One process per job. The kernel drops the lock if the process dies, so a free
        lock on a 'running' job means its process is gone."""
        handle = open(self._lock_dir / f"{job_id}.lock", "w")
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
            result: WorkflowResult = go()
        except PAUSE_ERRORS as e:
            return self._end(job_id, "paused", str(e))
        except KeyboardInterrupt:
            return self._end(job_id, "paused", "interrupted by owner")
        except FAIL_ERRORS as e:
            return self._end(job_id, "failed", str(e))
        except Exception as e:
            return self._end(job_id, "failed", f"unexpected error: {type(e).__name__}: {str(e)[:200]}")
        if result.status == "paused":
            return self._end(job_id, "paused", result.reason)
        return self._end(job_id, "done", None, result.data.get("answer"))

    def _end(self, job_id: str, status: str, reason: str | None, answer: str | None = None) -> RunOutcome:
        # record the outcome first, so a second Ctrl-C during cleanup cannot leave the job 'running'
        self._jobs.set_status(job_id, status, reason)
        self._bus.publish(f"job.{status}", {"reason": reason} if reason else {}, job_id)
        try:
            self._socket.unload_all(job_id)
        except KeyboardInterrupt:
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
            out = self._socket.ask_json(role.tier, messages, data["job_id"])
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
