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
