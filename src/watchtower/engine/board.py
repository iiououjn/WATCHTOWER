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
        """Every board note of the job, however many other bus events it has."""
        out, after = [], 0
        while True:
            page = self._bus.events(after, job_id=job_id, limit=1000, topic="board.note")
            out += [e.detail for e in page]
            if len(page) < 1000:
                return out
            after = page[-1].seq

    def brief(self, job_id: str, floor: str, max_chars: int = 600) -> str:
        notes = self.notes(job_id)
        if not notes:
            return ""
        status: dict[str, dict] = {}
        plans: dict[str, str] = {}
        for n in notes:
            if n["kind"] in ("done", "doing", "issue") and n["floor"] != floor:
                status[n["floor"]] = n  # the latest word from each floor wins, problems included
            elif n["kind"] == "plan":
                plans[n["floor"]] = n["text"]  # only the current plan
        mine = [_cut(n["text"], 120) for n in notes
                if n["floor"] == floor and n["kind"] in ("done", "doing", "issue")][-2:]
        all_memos = [n for n in notes if n["kind"] == "memo"]
        own = [n for n in all_memos if n["floor"] == floor]  # a floor's own answers come first
        memos = [_cut(n["text"], 240) for n in (own[-2:] if own else all_memos[-1:])]
        others = "; ".join(f"{NAMES[f]}{' (problem)' if n['kind'] == 'issue' else ''}: {_cut(n['text'], 110)}"
                           for f, n in status.items())
        sections = {  # display order; filled by priority so memo answers and what comes next always fit
            "others": f"Other floors: {others}" if others else "",
            "mine": "Your floor so far: " + "; ".join(mine) if mine else "",
            "plans": "Planned: " + "; ".join(f"{NAMES[f]}: {_cut(t, 110)}" for f, t in plans.items()) if plans else "",
            "memos": "Memo answers: " + "; ".join(memos) if memos else "",
            "next": f"Coming next: {NEXT.get(floor, '')}",
        }
        room, chosen = max_chars, {}
        for key in ("memos", "next", "others", "mine", "plans"):
            text = sections[key]
            if text and room > 20:
                chosen[key] = _cut(text, room - 1)
                room -= len(chosen[key]) + 1
        return "\n".join(chosen[k] for k in sections if k in chosen)


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: max(0, n - 3)] + "..."
