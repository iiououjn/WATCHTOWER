from __future__ import annotations

import json
from typing import Callable

from watchtower.engine.model_socket import BadModelOutput
from watchtower.floors.framework import strs, untrusted

SPEC_MORE_PROMPT = (
    "This app spec has too few acceptance criteria for QA to test:\n{spec}\n\nAdd criteria so there are 3 to 5, "
    "each testable: what a user does and what the page then shows. Reply as JSON: {{\"acceptance\": [string]}}"
)
MIN_CRITERIA, MAX_CRITERIA = 3, 6
TOWER_DEFAULTS = (  # what QA can always check in a small web app; marked so the owner sees who added them
    "The home page (GET /) shows the app's title: {title} (tower default)",
    "Something a user adds through the app's form then appears on the page that lists it (tower default)",
    "Empty or invalid input is refused with a clear message, never a crash (tower default)",
)


def enough_criteria(ask: Callable[[str], dict], spec: dict) -> list[str]:
    """C-suite CPO, app jobs: a spec QA can test. Fewer than 3 criteria → the CPO is asked once more; still
    short → tower defaults (marked). Deduped, ≤ 6, each ≤ 200 characters."""
    criteria = list(spec["acceptance"])
    if len(criteria) < MIN_CRITERIA:
        try:
            more = ask(SPEC_MORE_PROMPT.format(
                spec=untrusted("cpo", json.dumps({k: spec[k] for k in ("title", "goal", "acceptance")}))))
            criteria += strs(more.get("acceptance"))
        except BadModelOutput:  # garbage costs the re-ask; low memory still pauses, as for any CPO call
            pass
    out, seen = [], set()
    for c in criteria + [d.format(title=spec["title"][:60]) for d in TOWER_DEFAULTS]:
        text = " ".join(str(c).split())[:200]
        if text and text.lower() not in seen and (len(out) < MIN_CRITERIA or c in criteria):
            seen.add(text.lower())
            out.append(text)
    return out[:MAX_CRITERIA]
