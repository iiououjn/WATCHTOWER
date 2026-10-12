from __future__ import annotations

import re

from watchtower.engine.bus import Bus

FLOORS = ("f1", "f2", "f3", "f4", "f5")
KINDS = {"done", "doing", "plan", "issue", "memo"}
NAMES = {"f1": "F1 Research", "f2": "F2 Dev", "f3": "F3 Build", "f4": "F4 QA", "f5": "F5 Oversight"}
NEXT = {"f1": "F2 Dev will design and code the app.",
        "f2": "F3 Build will start the app; F4 QA will run its HTTP checks.",
        "f3": "F4 QA will run its HTTP checks; F5 will review everything.",
        "f4": "F5 Oversight will review the whole job.",
        "f5": "The owner signs off."}
NOTE_CHARS = 300
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


class Board:
    """The tower's shared notice board for one job: every floor posts what it did, is doing, plans or
    asked; every agent gets a short brief of it. Notes live on the bus (audit log), so they are ordered,
    tamper-evident and visible to the dashboard later."""

    def __init__(self, bus: Bus):
        self._bus = bus

    def note(self, job_id: str, floor: str, kind: str, text: str) -> None:
        if floor not in FLOORS:
            raise ValueError(f"unknown floor {floor!r}")
        if kind not in KINDS:
            raise ValueError(f"unknown note kind {kind!r}")
        clean = " ".join(_CONTROL.sub(" ", str(text)).split())[:NOTE_CHARS]
        self._bus.publish("board.note", {"floor": floor, "kind": kind, "text": clean}, job_id)

    def notes(self, job_id: str) -> list[dict]:
        return [e.detail for e in self._bus.events(job_id=job_id) if e.action == "board.note"]

    def brief(self, job_id: str, floor: str, max_chars: int = 600) -> str:
        notes = self.notes(job_id)
        if not notes:
            return ""
        latest = {}
        for n in notes:
            if n["kind"] in ("done", "doing") and n["floor"] != floor:
                latest[n["floor"]] = n["text"]
        mine = [n["text"] for n in notes if n["floor"] == floor and n["kind"] in ("done", "doing", "issue")][-2:]
        plans = [f"{NAMES[n['floor']]}: {n['text']}" for n in notes if n["kind"] == "plan"][-2:]
        memos = [n["text"] for n in notes if n["kind"] == "memo"][-2:]
        lines = ["Other floors: " + "; ".join(f"{NAMES[f]}: {t}" for f, t in latest.items())] if latest else []
        lines += ["Your floor so far: " + "; ".join(mine)] if mine else []
        lines += ["Planned: " + "; ".join(plans)] if plans else []
        lines += ["Memo answers: " + "; ".join(memos)] if memos else []
        lines.append(f"Coming next: {NEXT.get(floor, '')}")
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 3] + "..."
