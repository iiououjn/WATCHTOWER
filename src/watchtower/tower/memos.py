from __future__ import annotations

from watchtower.engine.advisory import ADVISORY_ERRORS
from watchtower.floors.board import FLOORS, NAMES
from watchtower.floors.framework import untrusted
from watchtower.roles import Role

MAX_MEMOS = 3
MEMO_SENDERS = {"f1.lead", "f2.architect", "f2.coder", "f3.lead", "f4.lead"}
FLOOR_LEADS = {"f1": "f1.lead", "f2": "f2.architect", "f3": "f3.lead", "f4": "f4.lead"}
MEMO_PROMPT = (
    "{sender} asks your floor:\n{question}\n\nWhat your floor knows:\n{known}\n\n"
    "Answer briefly and factually; say 'unknown' if your floor does not know. "
    'Reply as JSON: {{"answer": string}}'
)
BOARD_HEADER = "\n\nTower board (what the other floors know and what comes next):\n"


class MemoDoor:
    """The one door every floor agent goes through (mixed into TowerPipeline, which owns `_ask`, `_board`,
    `_known` and `_roles`): the agent hears the tower board and may send one memo to another floor's lead."""

    def _call(self, role: Role, data: dict, prompt: str) -> dict:
        job_id = data["job_id"]
        brief = self._board.brief(job_id, role.floor) if role.floor in FLOORS else ""
        out = self._ask(role, data, prompt + (BOARD_HEADER + untrusted("board", brief) if brief else ""))
        if role.id in MEMO_SENDERS and isinstance(out, dict) and isinstance(out.get("memo"), dict):
            self._route_memo(role, data, out["memo"])
        return out

    def _route_memo(self, sender: Role, data: dict, memo: dict) -> None:
        job_id, to = data["job_id"], str(memo.get("to") or "").strip().lower()
        question = " ".join(str(memo.get("question") or "").split())[:120]
        lead = self._roles.get(FLOOR_LEADS.get(to, ""))
        if lead is None or to == sender.floor or not question:
            return
        notes = self._board.notes(job_id)
        if sum(n["kind"] == "memo" and n["floor"] == sender.floor for n in notes) >= MAX_MEMOS:
            return
        own = [n["text"] for n in notes if n["floor"] == to and n["kind"] != "memo"][-5:]
        known = "\n".join(filter(None, [self._known.get((job_id, to), "")[:1200]] + own))
        if not known:  # never let a floor invent what it has not done
            answer = "nothing yet: that floor has not worked on this job"
        else:
            try:  # answered through the raw door: an answer can never send another memo
                out = self._ask(lead, data, MEMO_PROMPT.format(sender=NAMES[sender.floor],
                                                               question=untrusted(sender.floor, question),
                                                               known=untrusted(to, known[:1500])))
                answer = " ".join(str(out.get("answer") or "").split())[:150] or "no answer"
            except ADVISORY_ERRORS:  # a memo never pauses a job
                answer = "no answer"
        self._board.note(job_id, sender.floor, "memo",
                         f"{NAMES[sender.floor]} asked {NAMES[to]}: {question[:50]} → {answer}")
