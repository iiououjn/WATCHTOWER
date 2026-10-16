from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph


class PauseRequested(Exception):
    pass


@dataclass(frozen=True)
class Step:
    name: str
    fn: Callable[..., dict]
    resumable: bool = False  # fn(data, progress): the step checkpoints its own rounds (the dev floor's attempts)


class Progress:
    """A resumable step's own checkpoint between steps: `state` is what it saved last (empty on a fresh start).
    `save` is durable before it returns, then honours the owner's pause, so a pause loses no finished round."""

    def __init__(self, state: dict, write: Callable[[dict | None], None], should_pause: Callable[[], bool]):
        self.state = state
        self._write, self._should_pause = write, should_pause

    @classmethod
    def none(cls) -> "Progress":  # for callers outside a workflow: nothing is kept
        return cls({}, lambda state: None, lambda: False)

    def save(self, state: dict) -> None:
        self._write(state)
        self.state = dict(state)
        if self._should_pause():
            raise PauseRequested("pause requested by owner")

    def clear(self) -> None:
        self._write(None)
        self.state = {}


@dataclass(frozen=True)
class WorkflowResult:
    status: str  # "done" | "paused"
    data: dict
    reason: str | None = None


class _State(TypedDict):
    job_id: str
    data: dict


class Workflow:
    """Runs steps in order and checkpoints after each one, so a crashed or paused job
    resumes from its last finished step. LangGraph stays behind this interface."""

    def __init__(
        self,
        steps: list[Step],
        checkpoint_db: Path,
        should_pause: Callable[[str], bool] = lambda job_id: False,
    ):
        names = [s.name for s in steps]
        if not steps or len(set(names)) != len(names):
            raise ValueError("workflow needs at least one step and unique step names")
        self._should_pause = should_pause
        self._conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
        self._progress = sqlite3.connect(checkpoint_db, check_same_thread=False, isolation_level=None)
        self._progress.execute("PRAGMA busy_timeout=10000")
        self._progress.execute("CREATE TABLE IF NOT EXISTS step_progress(thread_id TEXT NOT NULL, step TEXT NOT NULL,"
                               " state TEXT NOT NULL, PRIMARY KEY(thread_id, step))")
        graph = StateGraph(_State)
        previous = START
        for step in steps:
            graph.add_node(step.name, self._node(step))
            graph.add_edge(previous, step.name)
            previous = step.name
        graph.add_edge(previous, END)
        self._graph = graph.compile(checkpointer=SqliteSaver(self._conn))

    def run(self, job_id: str, data: dict) -> WorkflowResult:
        self._progress.execute("DELETE FROM step_progress WHERE thread_id=?", (job_id,))  # a fresh run starts clean
        return self._invoke({"job_id": job_id, "data": data}, job_id)

    def has_checkpoint(self, job_id: str) -> bool:
        return bool(self._graph.get_state(self._config(job_id)).values)

    def resume(self, job_id: str) -> WorkflowResult:
        if not self.has_checkpoint(job_id):
            raise KeyError(job_id)
        return self._invoke(None, job_id)

    def close(self) -> None:
        self._conn.close()
        self._progress.close()

    def _node(self, step: Step):
        def node(state: _State) -> dict:
            job_id = state["job_id"]
            if self._should_pause(job_id):
                raise PauseRequested("pause requested by owner")
            if not step.resumable:
                return {"data": {**state["data"], **step.fn(dict(state["data"]))}}
            progress = Progress(self._load(job_id, step.name), lambda saved: self._save(job_id, step.name, saved),
                                lambda: self._should_pause(job_id))
            out = step.fn(dict(state["data"]), progress)
            self._save(job_id, step.name, None)  # finished: its checkpoint is the graph's from here on
            return {"data": {**state["data"], **out}}

        return node

    def _load(self, job_id: str, step: str) -> dict:
        row = self._progress.execute("SELECT state FROM step_progress WHERE thread_id=? AND step=?",
                                     (job_id, step)).fetchone()
        return json.loads(row[0]) if row else {}

    def _save(self, job_id: str, step: str, state: dict | None) -> None:
        if state is None:
            self._progress.execute("DELETE FROM step_progress WHERE thread_id=? AND step=?", (job_id, step))
        else:
            self._progress.execute("INSERT OR REPLACE INTO step_progress(thread_id, step, state) VALUES (?,?,?)",
                                   (job_id, step, json.dumps(state)))

    def _invoke(self, payload: dict | None, job_id: str) -> WorkflowResult:
        config = self._config(job_id)
        try:
            out = self._graph.invoke(payload, config, durability="sync")
        except PauseRequested as e:
            return WorkflowResult("paused", self._graph.get_state(config).values.get("data", {}), str(e))
        return WorkflowResult("done", out["data"])

    @staticmethod
    def _config(job_id: str) -> dict:
        return {"configurable": {"thread_id": job_id}}
