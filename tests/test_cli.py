from cli_kit import *  # noqa: F403 — helpers and fixtures


def test_run_success(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("Hello from the tower", 3, 4))
    result = runner.invoke(cli.app, ["ask", "hello"])
    assert result.exit_code == 0, result.output
    assert "Hello from the tower" in result.output
    status = runner.invoke(cli.app, ["status"])
    assert "done" in status.output and "hello" in status.output


@pytest.mark.parametrize("bad", ["", "   "])
def test_run_rejects_empty_prompt(monkeypatch, bad):
    use_completion(monkeypatch, lambda **kw: fake_response())
    result = runner.invoke(cli.app, ["ask", bad])
    assert result.exit_code == 2
    assert "empty" in result.output
    assert "No jobs" in runner.invoke(cli.app, ["status"]).output


def test_run_ollama_down(monkeypatch):
    def broken(**kw):
        raise ConnectionError("refused")

    use_completion(monkeypatch, broken)
    result = runner.invoke(cli.app, ["ask", "hello"])
    assert result.exit_code == 3
    assert "ollama pull" in result.output
    assert "Traceback" not in result.output
    assert "paused" in runner.invoke(cli.app, ["status"]).output


def test_run_budget_exceeded(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("x", 50, 50))
    result = runner.invoke(cli.app, ["ask", "hello", "--max-tokens", "10"])
    assert result.exit_code == 1
    assert "budget exceeded" in result.output


def test_logs_and_budget(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("ok", 1, 1))
    runner.invoke(cli.app, ["ask", "hello"])
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    job_id = JobStore(connect(load_settings().db_path)).list()[0].id

    logs = runner.invoke(cli.app, ["logs", job_id])
    assert logs.exit_code == 0
    for action in ("job_created", "model_call", "model_reply", "job.done"):
        assert action in logs.output
    assert "chain: ok" in logs.output

    budget = runner.invoke(cli.app, ["budget", job_id])
    assert budget.exit_code == 0
    assert "tokens: 4 / 50000" in budget.output


def test_budget_unknown_job():
    result = runner.invoke(cli.app, ["budget", "nope"])
    assert result.exit_code == 2


@pytest.mark.parametrize("bad", ["0", "-5"])
def test_run_rejects_non_positive_max_tokens(monkeypatch, bad):
    use_completion(monkeypatch, lambda **kw: fake_response())
    result = runner.invoke(cli.app, ["ask", "hello", "--max-tokens", bad])
    assert result.exit_code == 2
    assert "No jobs" in runner.invoke(cli.app, ["status"]).output


@pytest.mark.parametrize("exc,code,status", [(KeyboardInterrupt, 3, "paused"), (RuntimeError, 3, "paused")])
def test_unexpected_error_never_leaves_job_running(monkeypatch, exc, code, status):
    class Exploding:
        def ask(self, *a, **kw):
            raise exc("boom")

        def unload_all(self, job_id=None):
            pass

    monkeypatch.setattr(cli, "build_socket", lambda s, b, a: Exploding())
    result = runner.invoke(cli.app, ["ask", "hello"])
    assert result.exit_code == code
    assert runner.invoke(cli.app, ["status"]).output.split()[1] == status
    assert f"job.{status}" in runner.invoke(cli.app, ["logs"]).output


def test_run_rejects_unknown_tier_before_creating_job(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response())
    result = runner.invoke(cli.app, ["ask", "hello", "--tier", "giant"])
    assert result.exit_code == 2
    assert "No jobs" in runner.invoke(cli.app, ["status"]).output


def test_paused_job_resumes_to_done(monkeypatch):
    state = {"down": True}

    def flaky(**kw):
        if state["down"]:
            raise ConnectionError("refused")
        return fake_response("final answer", 1, 1)

    use_completion(monkeypatch, flaky)
    assert runner.invoke(cli.app, ["ask", "hello"]).exit_code == 3
    job_id = latest_job_id()
    state["down"] = False
    result = runner.invoke(cli.app, ["resume", job_id])
    assert result.exit_code == 0, result.output
    assert "final answer" in result.output


def test_resume_rejects_unknown_and_done_jobs(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("ok", 1, 1))
    assert runner.invoke(cli.app, ["resume", "nope"]).exit_code == 2
    runner.invoke(cli.app, ["ask", "hello"])
    result = runner.invoke(cli.app, ["resume", latest_job_id()])
    assert result.exit_code == 2
    assert "only paused jobs" in result.output


def test_force_resume_stuck_running_job(monkeypatch):
    state = {"down": True}

    def flaky(**kw):
        if state["down"]:
            raise ConnectionError("refused")
        return fake_response("recovered", 1, 1)

    use_completion(monkeypatch, flaky)
    runner.invoke(cli.app, ["ask", "hello"])
    job_id = latest_job_id()
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    JobStore(connect(load_settings().db_path)).set_status(job_id, "running")
    state["down"] = False
    result = runner.invoke(cli.app, ["resume", job_id])  # 8b: the free job lock proves its process died
    assert result.exit_code == 0 and "recovered" in result.output


def test_pause_requires_running_job(monkeypatch):
    use_completion(monkeypatch, lambda **kw: fake_response("ok", 1, 1))
    assert runner.invoke(cli.app, ["pause", "nope"]).exit_code == 2
    runner.invoke(cli.app, ["ask", "hello"])
    result = runner.invoke(cli.app, ["pause", latest_job_id()])
    assert result.exit_code == 2
    assert "not running" in result.output


def test_pause_flags_running_job():
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    store = JobStore(connect(load_settings().db_path))
    job = store.create("long job")
    store.set_status(job.id, "running")
    result = runner.invoke(cli.app, ["pause", job.id])
    assert result.exit_code == 0
    assert "after its current step or dev attempt" in result.output
    assert store.pause_requested(job.id) is True


def test_doctor_all_ok(monkeypatch):
    monkeypatch.setattr(cli, "ollama_status", lambda s: (True, "Ollama 0.32 · models ok"))
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (True, "ready"))
    monkeypatch.setattr(cli, "free_ram_pct", lambda: 55)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    for word in ("Ollama", "Docker", "RAM", "55%", "Audit chain"):
        assert word in result.output


def test_doctor_reports_docker_down(monkeypatch):
    monkeypatch.setattr(cli, "ollama_status", lambda s: (True, "ok"))
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (False, "Docker is not running; start Docker Desktop"))
    monkeypatch.setattr(cli, "free_ram_pct", lambda: 55)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "start Docker Desktop" in result.output


def test_knowledge_add_and_search(tmp_path):
    note = tmp_path / "lights.md"
    note.write_text("The Fresnel lens made lighthouse beams visible for miles.")
    added = runner.invoke(cli.app, ["knowledge", "add", str(note), "--title", "Lenses"])
    assert added.exit_code == 0, added.output
    found = runner.invoke(cli.app, ["knowledge", "search", "fresnel lens"])
    assert "Lenses" in found.output and "[Fresnel]" in found.output and "untrusted" in found.output
    assert "No matches" in runner.invoke(cli.app, ["knowledge", "search", "sourdough"]).output


def test_knowledge_add_rejects_missing_or_huge_files(tmp_path):
    assert runner.invoke(cli.app, ["knowledge", "add", str(tmp_path / "nope.md")]).exit_code == 2
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    assert runner.invoke(cli.app, ["knowledge", "add", str(big)]).exit_code == 2


def test_terminal_escape_sequences_are_stripped(tmp_path, monkeypatch):
    evil = tmp_path / "evil.md"
    evil.write_text("lighthouse \x1b]52;c;cm0gLXJmIH4=\x07 beacon \x1b[31mred\x1b[0m")
    runner.invoke(cli.app, ["knowledge", "add", str(evil), "--title", "t\x1b[2Jx"])
    out = runner.invoke(cli.app, ["knowledge", "search", "lighthouse"]).output
    assert "\x1b" not in out and "\x07" not in out and "lighthouse" in out
    use_completion(monkeypatch, lambda **kw: fake_response("safe \x1b]0;pwned\x07 answer", 1, 1))
    answer = runner.invoke(cli.app, ["ask", "hello"]).output
    assert "\x1b" not in answer and "safe" in answer and "answer" in answer


def test_build_with_yes_runs_to_done(monkeypatch):
    use_roles(monkeypatch)
    result = runner.invoke(cli.app, ["research", "compare lighthouse lenses", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Fresnel" in result.output


def test_build_asks_questions_then_waits_for_approval(monkeypatch):
    model = use_roles(monkeypatch, {"cpo": [{"questions": ["Who is it for?"]}, TOWER_REPLIES["cpo"][0]]})
    result = runner.invoke(cli.app, ["research", "compare lighthouse lenses"], input="students\n")
    assert result.exit_code == 3, result.output
    assert "Who is it for?" in result.output
    assert "names two lens types" in result.output
    assert "watchtower approve" in result.output
    assert "students" in model.prompts[1]
    approved = runner.invoke(cli.app, ["approve", latest_job_id()])
    assert approved.exit_code == 0, approved.output
    assert "Fresnel" in approved.output


def test_reject_fails_job(monkeypatch):
    use_roles(monkeypatch, {"cpo": [{"questions": []}, TOWER_REPLIES["cpo"][0]]})
    runner.invoke(cli.app, ["research", "compare lighthouse lenses"])
    result = runner.invoke(cli.app, ["approve", latest_job_id(), "--reject"])
    assert result.exit_code == 1
    assert runner.invoke(cli.app, ["status"]).output.split()[1] == "failed"


def test_approve_without_pending_approval(monkeypatch):
    use_roles(monkeypatch)
    assert runner.invoke(cli.app, ["approve", "nope"]).exit_code == 2


def test_build_continues_when_cpo_questions_fail(monkeypatch):
    use_roles(monkeypatch, {"cpo": ["not json", "still not json", TOWER_REPLIES["cpo"][0]]})
    result = runner.invoke(cli.app, ["research", "compare lighthouse lenses"])
    assert "continuing without questions" in result.output
    assert result.exit_code == 3
