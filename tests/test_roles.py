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


@pytest.mark.parametrize("role_id", ["cpo", "f1.lead", "f1.worker", "f1.hr", "f5.gate", "f4.qa", "f4.lead", "f4.hr", "f2.hr", "f3.lead", "f3.hr", "f5.lead", "f5.auditor"])
def test_every_role_that_reads_context_distrusts_it(role_id):
    assert "never follow instructions" in load_roles(tiers=DEFAULT_TIERS)[role_id].prompt


def test_dev_gate_reviews_with_a_different_family_than_the_coder():
    roles = load_roles(tiers=DEFAULT_TIERS)
    coder = DEFAULT_TIERS[roles["f2.coder"].tier].split(":")[0]
    assert DEFAULT_TIERS[roles["f5.dev_gate"].tier].split(":")[0] != coder


def test_qa_writes_checks_with_a_different_family_than_the_coder():
    roles = load_roles(tiers=DEFAULT_TIERS)
    coder = DEFAULT_TIERS[roles["f2.coder"].tier].split(":")[0]
    assert DEFAULT_TIERS[roles["f4.qa"].tier].split(":")[0] != coder


@pytest.mark.parametrize("role_id", ["f1.lead", "f2.architect", "f2.coder", "f4.lead", "f3.lead"])
def test_memo_senders_know_how_to_send_memos(role_id):
    assert '"memo"' in load_roles(tiers=DEFAULT_TIERS)[role_id].prompt


@pytest.mark.parametrize("role_id,own", [("f1.lead", "f1"), ("f2.architect", "f2"), ("f2.coder", "f2"),
                                         ("f3.lead", "f3"), ("f4.lead", "f4")])
def test_memo_senders_are_not_offered_their_own_floor(role_id, own):
    assert f'"{own}" (' not in load_roles(tiers=DEFAULT_TIERS)[role_id].prompt
