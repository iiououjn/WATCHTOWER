from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, TextIO

from watchtower.config import Settings
from watchtower.engine.bus import Bus
from watchtower.engine.memory import ContextStore

POLL_SECONDS = 0.5


class SchedulerBusy(Exception):
    pass


@dataclass
class AgentSession:
    agent_id: str
    job_id: str
    context: dict = field(default_factory=dict)


class Scheduler:
    """Hands out agent slots (file locks, so the limit holds across processes) and
    wakes/idles agents: context is restored on wake and saved on idle."""

    def __init__(
        self,
        settings: Settings,
        memory: ContextStore,
        bus: Bus,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._s = settings
        self._memory = memory
        self._bus = bus
        self._sleep = sleep
        self._clock = clock
        self._slot_dir = settings.home / "slots"
        self._slot_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def agent(self, agent_id: str, job_id: str, wait_seconds: float = 30.0) -> Iterator[AgentSession]:
        slot = self._acquire(wait_seconds)
        try:
            session = AgentSession(agent_id, job_id, self._memory.load(agent_id, job_id) or {})
            self._bus.publish("agent.wake", {"agent": agent_id}, job_id)
            try:
                yield session
            finally:
                self._memory.save(agent_id, job_id, session.context)
                self._bus.publish("agent.idle", {"agent": agent_id}, job_id)
        finally:
            fcntl.flock(slot, fcntl.LOCK_UN)
            slot.close()

    def _acquire(self, wait_seconds: float) -> TextIO:
        deadline = self._clock() + wait_seconds
        while True:
            for i in range(self._s.agent_slots):
                handle = open(self._slot_dir / f"{i}.lock", "w")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return handle
                except BlockingIOError:
                    handle.close()
            if self._clock() >= deadline:
                raise SchedulerBusy(
                    f"all {self._s.agent_slots} agent slot(s) busy after {wait_seconds}s; "
                    "another job is running — resume this one later"
                )
            self._sleep(POLL_SECONDS)
