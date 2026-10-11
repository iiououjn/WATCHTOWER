import pytest

from watchtower.config import DEFAULT_TIERS
from watchtower.roles import load_roles


def test_packaged_roles_load():
    roles = load_roles(tiers=DEFAULT_TIERS)
    assert {"cpo", "f1.lead", "f1.worker", "f1.hr", "f5.gate"} <= set(roles)
    assert roles["f1.worker"].system.startswith("[role:f1.worker] ")
    assert "untrusted" in roles["f1.worker"].prompt


def test_gate_reviews_with_a_different_family_than_floor_one():
    roles = load_roles(tiers=DEFAULT_TIERS)
    worker_model = DEFAULT_TIERS[roles["f1.worker"].tier]
    gate_model = DEFAULT_TIERS[roles["f5.gate"].tier]
    assert worker_model.split(":")[0] != gate_model.split(":")[0]


def write(tmp_path, name, text):
    (tmp_path / name).write_text(text)


def test_missing_field(tmp_path):
    write(tmp_path, "a.yaml", "id: a\ntitle: A\nfloor: f1\ntier: small\n")
    with pytest.raises(ValueError, match="prompt"):
        load_roles(tmp_path)


def test_duplicate_ids(tmp_path):
    body = "id: a\ntitle: A\nfloor: f1\ntier: small\nprompt: hi\n"
    write(tmp_path, "a.yaml", body)
    write(tmp_path, "b.yaml", body)
    with pytest.raises(ValueError, match="duplicate"):
        load_roles(tmp_path)


def test_unknown_tier(tmp_path):
    write(tmp_path, "a.yaml", "id: a\ntitle: A\nfloor: f1\ntier: giant\nprompt: hi\n")
    with pytest.raises(ValueError, match="tier"):
        load_roles(tmp_path, tiers={"small": "x"})


def test_not_a_mapping(tmp_path):
    write(tmp_path, "a.yaml", "- just\n- a list\n")
    with pytest.raises(ValueError):
        load_roles(tmp_path)
