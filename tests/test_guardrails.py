import pytest

from watchtower.guardrails import GuardrailsError, load_guardrails


def test_packaged_guardrails_load_with_spec_rules():
    g = load_guardrails(None)
    assert g.stdlib_only is True and g.security_fail_on == ("HIGH", "MEDIUM")
    assert g.min_source_domains == 2 and g.max_send_backs == 3
    assert any("acceptance criteria" in r for r in g.rules) and any("secret" in r for r in g.rules)


def test_owner_copy_overrides(tmp_path):
    (tmp_path / "guardrails.yaml").write_text("max_send_backs: 2\nsecurity_fail_on: [HIGH]\nrules: [be kind]\n")
    g = load_guardrails(tmp_path)
    assert g.max_send_backs == 2 and g.security_fail_on == ("HIGH",) and g.rules == ("be kind",)
    assert g.stdlib_only is True  # unset keys keep the packaged default


@pytest.mark.parametrize("text", ["max_send_backs: 99\n", "max_send_backs: 'x'\n", "security_fail_on: [EVIL]\n",
                                  "stdlib_only: maybe\n", "surprise: 1\n", "rules: [" + "'x', " * 20 + "]\n",
                                  "rules: ['" + "y" * 300 + "']\n", "- a list\n", "min_source_domains: -1\n",
                                  "max_send_backs: true\n"])
def test_bad_owner_files_are_refused_clearly(tmp_path, text):
    (tmp_path / "guardrails.yaml").write_text(text)
    with pytest.raises(GuardrailsError):
        load_guardrails(tmp_path)


def test_work_model_is_configurable(monkeypatch, tmp_path):
    from watchtower.config import load_settings
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_WORK_MODEL", "qwen2.5-coder:7b")
    assert load_settings().tiers["work"] == "ollama/qwen2.5-coder:7b"
    monkeypatch.setenv("WATCHTOWER_WORK_MODEL", "bad model;rm")
    with pytest.raises(ValueError):
        load_settings()


@pytest.mark.parametrize("levels,expected", [("[LOW]", ("HIGH", "MEDIUM", "LOW")), ("[MEDIUM]", ("HIGH", "MEDIUM")),
                                             ("[]", ("HIGH",)), ("[high]", ("HIGH",))])
def test_security_fail_on_is_a_minimum_and_always_fails_high(tmp_path, levels, expected):
    (tmp_path / "guardrails.yaml").write_text(f"security_fail_on: {levels}\n")
    assert load_guardrails(tmp_path).security_fail_on == expected


def test_empty_or_commented_owner_file_keeps_defaults(tmp_path):
    (tmp_path / "guardrails.yaml").write_text("# nothing changed yet\n")
    assert load_guardrails(tmp_path) == load_guardrails(None)


@pytest.mark.parametrize("data", [b"rules: ['\xff\xfe']\n", b"[" * 5000 + b"]" * 5000, b"# " + b"x" * 70_000,
                                  b"rules: [" + b"'" + b"r" * 200 + b"', " * 12 + b"]\n",                                  b"rules: [\"a\\tb\"]\n"])
def test_hostile_owner_files_are_refused_clearly(tmp_path, data):
    (tmp_path / "guardrails.yaml").write_bytes(data)
    with pytest.raises(GuardrailsError):
        load_guardrails(tmp_path)


def test_stdlib_only_false_is_documented_as_import_check_only():
    from watchtower.guardrails import PACKAGED
    assert "cannot install packages" in PACKAGED.read_text()


def test_work_model_accepts_namespaced_ollama_names(monkeypatch, tmp_path):
    from watchtower.config import load_settings
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_WORK_MODEL", "hf.co/user/model:Q4_K_M")
    assert load_settings().tiers["work"] == "ollama/hf.co/user/model:Q4_K_M"


def test_owner_path_that_is_not_a_file_is_an_error(tmp_path):
    (tmp_path / "guardrails.yaml").symlink_to(tmp_path / "moved-away.yaml")
    with pytest.raises(GuardrailsError):
        load_guardrails(tmp_path)
    (tmp_path / "guardrails.yaml").unlink()
    (tmp_path / "guardrails.yaml").mkdir()
    with pytest.raises(GuardrailsError):
        load_guardrails(tmp_path)


def test_docs_describe_security_fail_on_as_a_minimum():
    from pathlib import Path
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    assert "Bandit severities that fail the build" not in readme and "lowest severity" in readme


def test_work_model_with_ollama_prefix_is_not_doubled(monkeypatch, tmp_path):
    from watchtower.config import load_settings
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_WORK_MODEL", "ollama/qwen2.5-coder:7b")
    assert load_settings().tiers["work"] == "ollama/qwen2.5-coder:7b"


def test_the_7b_coder_is_the_default_work_model(monkeypatch, tmp_path):
    from watchtower.config import load_settings
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.delenv("WATCHTOWER_WORK_MODEL", raising=False)
    assert load_settings().tiers["work"] == "ollama/qwen2.5-coder:7b"
