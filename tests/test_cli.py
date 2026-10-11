import pytest
from typer.testing import CliRunner

from conftest import fake_response
from watchtower import cli
from watchtower.engine.model_socket import ModelSocket

runner = CliRunner()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    return tmp_path


def use_completion(monkeypatch, fn):
    monkeypatch.setattr(
        cli, "build_socket",
        lambda s, b, a: ModelSocket(s, b, a, completion_fn=fn, unload_fn=lambda m: None),
    )


def test_run_success(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("Hello from the tower", 3, 4))
    result = runner.invoke(cli.app, ["run", "hello"])
    assert result.exit_code == 0, result.output
    assert "Hello from the tower" in result.output
    status = runner.invoke(cli.app, ["status"])
    assert "done" in status.output and "hello" in status.output


@pytest.mark.parametrize("bad", ["", "   "])
def test_run_rejects_empty_prompt(monkeypatch, bad):
    use_completion(monkeypatch, lambda **kw: fake_response())
    result = runner.invoke(cli.app, ["run", bad])
    assert result.exit_code == 2
    assert "empty" in result.output
    assert "No jobs" in runner.invoke(cli.app, ["status"]).output


def test_run_ollama_down(monkeypatch):
    def broken(**kw):
        raise ConnectionError("refused")

    use_completion(monkeypatch, broken)
    result = runner.invoke(cli.app, ["run", "hello"])
    assert result.exit_code == 1
    assert "ollama pull" in result.output
    assert "Traceback" not in result.output
    assert "failed" in runner.invoke(cli.app, ["status"]).output


def test_run_budget_exceeded(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("x", 50, 50))
    result = runner.invoke(cli.app, ["run", "hello", "--max-tokens", "10"])
    assert result.exit_code == 1
    assert "budget exceeded" in result.output


def test_logs_and_budget(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("ok", 1, 1))
    runner.invoke(cli.app, ["run", "hello"])
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    job_id = JobStore(connect(load_settings().db_path)).list()[0].id

    logs = runner.invoke(cli.app, ["logs", job_id])
    assert logs.exit_code == 0
    for action in ("job_created", "model_call", "model_reply", "job_done"):
        assert action in logs.output
    assert "chain: ok" in logs.output

    budget = runner.invoke(cli.app, ["budget", job_id])
    assert budget.exit_code == 0
    assert "tokens: 2 / 50000" in budget.output


def test_budget_unknown_job():
    result = runner.invoke(cli.app, ["budget", "nope"])
    assert result.exit_code == 2
