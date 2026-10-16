"""Phase 8c (audit C-M5): every F2 prompt within PROMPT_CHARS. Over num_ctx, Ollama drops the head of the
prompt (the spec) without a word, so the tower trims first: least important part first, never the reply format."""
from __future__ import annotations

import json
from typing import Sequence

from watchtower.floors.framework import untrusted

PROMPT_CHARS = 9_000  # + system (~1.2k) + tower brief (~0.8k) ≈ 3.4k tokens; + 2048 output < num_ctx 6144
FILES_MIN, FILES_MAX = 1500, 6000  # the coder always sees some code; never more than this
WRAP = 100  # the untrusted wrapper and a snapshot's last fence can pass its max_chars by this much
SPEC_CHARS, RESEARCH_CHARS = 1500, 1500


def spec_text(spec: dict, cap: int | None = None) -> str:
    """The spec the floor works to; non-ASCII stays readable (json's \\uXXXX made a Hindi purpose 6x longer)."""
    text = json.dumps({k: spec.get(k) for k in ("title", "goal", "acceptance", "out_of_scope")}, indent=1,
                      ensure_ascii=False)
    return text if cap is None or len(text) <= cap else text[:cap] + " ...(cut)"


def plan_text(plan: dict, purposes: bool = True) -> str:
    """The architect's plan as untrusted JSON; without purposes when the prompt is full (paths always stay)."""
    shown = plan if purposes else {**plan, "files": [{"path": f["path"]} for f in plan.get("files", [])]}
    return untrusted("f2.architect", json.dumps(shown, ensure_ascii=False))


def fit(template: str, parts: dict, trims: Sequence[tuple[str, str]], room: int = 0) -> dict:
    """`parts` with trims applied in order (each replaces one part) until the formatted template leaves `room`
    characters for the slot the caller fills last (files or code, passed here as "")."""
    parts = dict(parts)
    for key, smaller in trims:
        if len(template.format(**parts)) <= PROMPT_CHARS - room:
            break
        parts[key] = smaller
    return parts


def room_left(template: str, parts: dict, most: int = FILES_MAX) -> int:
    """What the last slot may use: at least FILES_MIN (fit() made room for it), at most `most`."""
    return max(FILES_MIN, min(most, PROMPT_CHARS - len(template.format(**parts)))) - WRAP
