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
