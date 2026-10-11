from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from watchtower.config import Settings
from watchtower.engine.bus import Bus
from watchtower.engine.governor.budget import BudgetExceeded
from watchtower.engine.jobs import JobStore
from watchtower.engine.model_socket import CloudDisabled, LowMemory, ModelSocket, ModelUnavailable
from watchtower.engine.scheduler import Scheduler, SchedulerBusy
from watchtower.engine.workflow import Step, Workflow, WorkflowResult

PLAN_PROMPT = (
    "Write a short numbered plan (max 3 steps) for answering this request. "
    "Do not answer it yet.\n\nRequest: {prompt}"
)
ANSWER_PROMPT = "Request: {prompt}\n\nPlan:\n{plan}\n\nFollow the plan and answer the request concisely."
PAUSE_ERRORS = (ModelUnavailable, LowMemory, SchedulerBusy)
FAIL_ERRORS = (BudgetExceeded, CloudDisabled)


@dataclass(frozen=True)
class RunOutcome:
    job_id: str
    status: str
    answer: str | None
    reason: str | None


class JobRunner:
    """Runs a job as a checkpointed plan → answer workflow and decides paused vs failed."""

    def __init__(self, settings: Settings, conn: sqlite3.Connection, socket: ModelSocket,
                 scheduler: Scheduler, bus: Bus):
        self._jobs = JobStore(conn)
        self._socket = socket
        self._scheduler = scheduler
        self._bus = bus
        self._wf = Workflow(
            [Step("plan", self._plan), Step("answer", self._answer)],
            settings.home / "checkpoints.db",
            should_pause=self._jobs.pause_requested,
        )

    def start(self, job_id: str, tier: str) -> RunOutcome:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        self._jobs.set_status(job_id, "running")
        self._bus.publish("job.started", {"tier": tier}, job_id)
        data = {"job_id": job_id, "prompt": job.prompt, "tier": tier}
        return self._drive(job_id, lambda: self._wf.run(job_id, data))

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
        self._jobs.clear_pause(job_id)
        self._jobs.set_status(job_id, "running")
        self._bus.publish("job.resumed", {}, job_id)
        return self._drive(job_id, lambda: self._wf.resume(job_id))

    def close(self) -> None:
        self._wf.close()

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
        self._socket.unload_all(job_id)
        self._jobs.set_status(job_id, status, reason)
        self._bus.publish(f"job.{status}", {"reason": reason} if reason else {}, job_id)
        return RunOutcome(job_id, status, answer, reason)

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
