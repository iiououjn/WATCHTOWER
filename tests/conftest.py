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


APP_REPLIES = {
    "f2.architect": [{"files": [{"path": "app.py", "purpose": "server"},
                                {"path": "test_app.py", "purpose": "tests"}], "entry": "app.py"}],
    "f2.coder": [{"files": [{"path": "app.py", "content": "import json\n"},
                            {"path": "test_app.py", "content": "import unittest\n"}]}],
    "f5.dev_gate": [{"pass": True, "reasons": []}],
}


class FakeSandbox:
    """Sandbox stand-in: unittest and smoke results are scripted."""

    def __init__(self, root, test_ok=True, http="200", unavailable=False):
        self.root, self.test_ok, self.http, self.unavailable, self.calls = root, test_ok, http, unavailable, []

    def workspace(self, job_id):
        path = self.root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run(self, job_id, command, timeout=60.0):
        from watchtower.engine.sandbox import SandboxResult, SandboxUnavailable
        if self.unavailable:
            raise SandboxUnavailable("Docker is not running; start Docker Desktop, then resume")
        self.calls.append(command)
        if command[:2] == ["python", "-c"] and "WATCHTOWER_TESTS" in command[2]:
            ok = self.test_ok if isinstance(self.test_ok, bool) else self.test_ok.pop(0)
            line = '{"run": 2, "skipped": 0, "failures": %d, "errors": 0}' % (0 if ok else 1)
            return SandboxResult(0 if ok else 1, "WATCHTOWER_TESTS " + line + "\n", "FAILED\n" if not ok else "", False)
        return SandboxResult(0, f"SMOKE_STATUS {self.http}\n", "", False)
