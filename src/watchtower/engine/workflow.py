from __future__ import annotations

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
    fn: Callable[[dict], dict]


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
        graph = StateGraph(_State)
        previous = START
        for step in steps:
            graph.add_node(step.name, self._node(step))
            graph.add_edge(previous, step.name)
            previous = step.name
        graph.add_edge(previous, END)
        self._graph = graph.compile(checkpointer=SqliteSaver(self._conn))

    def run(self, job_id: str, data: dict) -> WorkflowResult:
        return self._invoke({"job_id": job_id, "data": data}, job_id)

    def resume(self, job_id: str) -> WorkflowResult:
        if not self._graph.get_state(self._config(job_id)).values:
            raise KeyError(job_id)
        return self._invoke(None, job_id)

    def close(self) -> None:
        self._conn.close()

    def _node(self, step: Step):
        def node(state: _State) -> dict:
            if self._should_pause(state["job_id"]):
                raise PauseRequested("pause requested by owner")
            return {"data": {**state["data"], **step.fn(dict(state["data"]))}}

        return node

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
