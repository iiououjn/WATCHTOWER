from types import SimpleNamespace

import pytest

from watchtower.config import Settings, DEFAULT_TIERS
from watchtower.engine.db import connect


@pytest.fixture
def settings(tmp_path):
    return Settings(home=tmp_path, tiers=dict(DEFAULT_TIERS))


@pytest.fixture
def conn(settings):
    c = connect(settings.db_path)
    yield c
    c.close()


def fake_response(text="hi", pt=3, ct=2):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct),
    )


import json

TOWER_REPLIES = {
    "cpo": [{"title": "Lens report", "goal": "Compare lighthouse lenses",
             "acceptance": ["names two lens types"], "out_of_scope": ["prices"]}],
    "f1.lead": [{"tasks": ["List lens types", "Compare them"]}],
    "f1.worker": [{"result": "Fresnel and catadioptric lenses", "sources": ["file:///notes.md"]}],
    "f1.hr": [{"pass": True, "reason": "ok"}],
    "f5.gate": [{"pass": True, "reasons": []}],
}


class RoleModel:
    """Fake completion answering per role (from the '[role:<id>]' system marker) with queued JSON."""

    def __init__(self, replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.calls = []
        self.prompts = []

    def __call__(self, **kw):
        role = kw["messages"][0]["content"].split("]")[0].removeprefix("[role:")
        self.calls.append(role)
        self.prompts.append(kw["messages"][-1]["content"])
        queue = self.replies[role]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return fake_response(reply if isinstance(reply, str) else json.dumps(reply), 2, 3)
