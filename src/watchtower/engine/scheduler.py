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
    def agent(self, agent_id: str, job_id: str, wait_seconds: float | None = None) -> Iterator[AgentSession]:
        slot = self._acquire(self._s.slot_wait_s if wait_seconds is None else wait_seconds)
        try:
            session = AgentSession(agent_id, job_id, self._memory.load(agent_id, job_id) or {})
            self._bus.publish("agent.wake", {"agent": agent_id}, job_id)
            try:
                yield session
            finally:
                self._idle(session)
        finally:
            fcntl.flock(slot, fcntl.LOCK_UN)
            slot.close()

    def _idle(self, session: AgentSession) -> None:
        """Save the context and say so. A failure here is reported, never raised: it must not replace the
        error in flight (a LowMemory that should pause would become a 'database is locked')."""
        try:
            self._memory.save(session.agent_id, session.job_id, session.context)
            self._bus.publish("agent.idle", {"agent": session.agent_id}, session.job_id)
        except Exception as e:  # noqa: BLE001 — cleanup is best effort by design
            try:
                self._bus.publish("agent.cleanup_failed", {"agent": session.agent_id,
                                                           "error": f"{type(e).__name__}: {str(e)[:200]}"},
                                  session.job_id)
            except Exception:  # noqa: BLE001 — the audit log itself is unavailable: nothing more to do
                pass

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
