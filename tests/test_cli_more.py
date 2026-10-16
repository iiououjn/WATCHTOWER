from cli_kit import *  # noqa: F403 — helpers and fixtures


def test_approve_requires_paused_job_and_keeps_approval_pending(monkeypatch):
    use_roles(monkeypatch, {"cpo": [{"questions": []}, TOWER_REPLIES["cpo"][0]]})
    runner.invoke(cli.app, ["research", "compare lighthouse lenses"])
    job_id = latest_job_id()
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.governor.approvals import Approvals
    from watchtower.engine.jobs import JobStore
    conn = connect(load_settings().db_path)
    JobStore(conn).set_status(job_id, "running")
    result = runner.invoke(cli.app, ["approve", job_id])
    assert result.exit_code == 2 and "running" in result.output
    assert Approvals(conn).pending_for(job_id) is not None


def test_ctrl_c_during_cpo_questions_does_not_strand_the_job(monkeypatch):
    import click
    use_roles(monkeypatch, {"cpo": [{"questions": ["Who?"]}, TOWER_REPLIES["cpo"][0]]})

    def abort(*a, **k):
        raise click.exceptions.Abort()

    monkeypatch.setattr(cli.typer, "prompt", abort)
    result = runner.invoke(cli.app, ["research", "compare lighthouse lenses"])
    assert result.exit_code == 130
    assert runner.invoke(cli.app, ["status"]).output.split()[1] == "failed"


def test_unexpected_error_asking_questions_continues(monkeypatch):
    use_roles(monkeypatch)
    monkeypatch.setattr(cli.JobRunner, "cpo_questions", lambda self, job_id: (_ for _ in ()).throw(RuntimeError("x")))
    result = runner.invoke(cli.app, ["research", "compare lighthouse lenses"])
    assert "continuing without questions" in result.output


def test_beacon_command_reports_accepted_and_rejected(monkeypatch):

    class Fake:
        def research(self, task, job_id):
            return [7]

    monkeypatch.setattr(cli, "make_beacon", lambda settings, conn: Fake())
    result = runner.invoke(cli.app, ["beacon", "fresnel lens"])
    assert result.exit_code == 0, result.output
    assert "1 page(s) added" in result.output


def test_beacon_command_search_down(monkeypatch):
    from watchtower.beacon.search import SearchUnavailable

    class Down:
        def research(self, task, job_id):
            raise SearchUnavailable("web search failed; check your internet connection, then resume")

    monkeypatch.setattr(cli, "make_beacon", lambda settings, conn: Down())
    result = runner.invoke(cli.app, ["beacon", "x"])
    assert result.exit_code == 3 and "internet" in result.output


def test_build_offline_flag_is_passed(monkeypatch):
    seen = {}
    real = cli.JobRunner.start

    def spy(self, job_id, tier="small", extra=None):
        seen.update(extra or {})
        return real(self, job_id, tier, extra)

    monkeypatch.setattr(cli.JobRunner, "start", spy)
    use_roles(monkeypatch)
    runner.invoke(cli.app, ["research", "compare lighthouse lenses", "--yes", "--offline"])
    assert seen.get("offline") is True


def test_build_uses_tower_budget(monkeypatch):
    use_roles(monkeypatch)
    runner.invoke(cli.app, ["research", "compare lighthouse lenses", "--yes"])
    assert "tokens: " in (out := runner.invoke(cli.app, ["budget", latest_job_id()]).output)
    assert "/ 300000" in out


def test_build_app_end_to_end_with_fakes(monkeypatch, tmp_path):
    from conftest import APP_REPLIES, FakeSandbox
    use_roles(monkeypatch, APP_REPLIES)
    monkeypatch.setattr(cli, "make_sandbox", lambda settings, conn: FakeSandbox(tmp_path / "apps"))
    result = runner.invoke(cli.app, ["run", "a todo web app", "--yes"])
    assert result.exit_code == 0, result.output
    assert "App ready" in result.output and "python app.py" in result.output


def test_deploy_done_app_prints_local_url(monkeypatch, tmp_path):
    job = done_app_job(monkeypatch, tmp_path)
    fake = FakeDeployer()
    monkeypatch.setattr(cli, "make_deployer", lambda settings, conn: fake)
    result = runner.invoke(cli.app, ["deploy", job, "--name", "todo"])
    assert result.exit_code == 0, result.output
    assert fake.calls == [("deploy", job, "todo")] and "http://127.0.0.1:8100" in result.output
    assert "no internet" in result.output


def test_deploy_refuses_unknown_or_non_app_jobs(monkeypatch):
    fake = FakeDeployer()
    monkeypatch.setattr(cli, "make_deployer", lambda settings, conn: fake)
    assert runner.invoke(cli.app, ["deploy", "nope"]).exit_code == 2
    use_completion(monkeypatch, lambda **kw: fake_response("hi", 1, 1))
    runner.invoke(cli.app, ["ask", "hello"])
    result = runner.invoke(cli.app, ["deploy", latest_job_id()])
    assert result.exit_code == 2 and "app" in result.output and fake.calls == []


def test_deploy_error_is_cleaned_and_exits_1(monkeypatch, tmp_path):
    job = done_app_job(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "make_deployer", lambda settings, conn: FakeDeployer(fail="boom\x1b[31m red"))
    result = runner.invoke(cli.app, ["deploy", job])
    assert result.exit_code == 1 and "boom" in result.output and "\x1b" not in result.output


def test_rollback_undeploy_and_deployments(monkeypatch):
    fake = FakeDeployer()
    monkeypatch.setattr(cli, "make_deployer", lambda settings, conn: fake)
    assert runner.invoke(cli.app, ["rollback", "app"]).exit_code == 0
    assert runner.invoke(cli.app, ["undeploy", "app"]).exit_code == 0
    listing = runner.invoke(cli.app, ["deployments"])
    assert listing.exit_code == 0 and "8100" in listing.output and "active" in listing.output
    assert fake.calls == [("rollback", "app"), ("undeploy", "app")]


def test_app_job_audit_records_app_pipeline(monkeypatch, tmp_path):
    from watchtower.engine.db import connect
    from watchtower.engine.governor.audit import AuditLog
    from watchtower.config import load_settings
    job = done_app_job(monkeypatch, tmp_path)
    created = [e for e in AuditLog(connect(load_settings().db_path)).entries(job_id=job) if e.action == "job_created"]
    assert created[0].detail["pipeline"] == "app"


def test_sign_off_is_shown_and_rejectable_from_the_cli(monkeypatch, tmp_path):
    from conftest import APP_REPLIES, FakeSandbox
    use_roles(monkeypatch, APP_REPLIES)
    monkeypatch.setattr(cli, "make_sandbox", lambda settings, conn: FakeSandbox(tmp_path / "apps"))
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "")
    runner.invoke(cli.app, ["run", "a todo web app"])
    job = latest_job_id()
    signoff = runner.invoke(cli.app, ["approve", job])
    assert signoff.exit_code == 3 and "sign-off" in signoff.output and "app.py" in signoff.output
    rejected = runner.invoke(cli.app, ["approve", job, "--reject"])
    assert rejected.exit_code == 1 and "app rejected by owner" in rejected.output


def test_doctor_checks_bandit(monkeypatch):
    monkeypatch.setattr(cli, "ollama_status", lambda s: (True, "ok"))
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (True, "ready"))
    monkeypatch.setattr(cli, "free_ram_pct", lambda: 55)
    assert "Bandit" in runner.invoke(cli.app, ["doctor"]).output


def test_doctor_reports_bad_guardrails(monkeypatch, home):
    monkeypatch.setattr(cli, "ollama_status", lambda s: (True, "ok"))
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (True, "ready"))
    monkeypatch.setattr(cli, "free_ram_pct", lambda: 55)
    assert "✓ Guardrails" in runner.invoke(cli.app, ["doctor"]).output
    (home / "guardrails.yaml").write_text("max_send_backs: 99\n")
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1 and "✗ Guardrails" in result.output and "max_send_backs" in result.output


def test_bad_guardrails_stop_jobs_with_a_clear_message(monkeypatch, home):
    use_completion(monkeypatch, lambda **kw: fake_response("hi", 1, 1))
    (home / "guardrails.yaml").write_text("surprise: 1\n")
    result = runner.invoke(cli.app, ["ask", "hello"])
    assert result.exit_code == 2 and "guardrails" in result.output and "Traceback" not in result.output
    assert "hello" not in runner.invoke(cli.app, ["status"]).output  # no orphan job left behind


def test_bad_work_model_is_a_clear_error_not_a_traceback(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_WORK_MODEL", "bad model;rm")
    result = runner.invoke(cli.app, ["deployments"])
    assert result.exit_code == 2 and "WATCHTOWER_WORK_MODEL" in result.output


def test_doctor_checks_every_glass_file(monkeypatch, tmp_path):
    import shutil
    from watchtower.beacon import glass as glass_mod
    monkeypatch.setattr(cli, "ollama_status", lambda s: (True, "ok"))
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (True, "ready"))
    monkeypatch.setattr(cli, "free_ram_pct", lambda: 55)
    assert "✓ Glass" in runner.invoke(cli.app, ["doctor"]).output
    for f in glass_mod.GLASS_DIR.glob("*.yaml"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "f3.yaml").write_text("allow_domains:\n  - null\n")
    monkeypatch.setattr(glass_mod, "GLASS_DIR", tmp_path)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1 and "✗ Glass" in result.output and "f3" in result.output


def test_run_checks_docker_before_any_model_work(monkeypatch):
    calls = []
    use_completion(monkeypatch, lambda **kw: calls.append(kw) or fake_response("{}", 1, 1))
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (False, "Docker is not running; start Docker Desktop"))
    result = runner.invoke(cli.app, ["run", "a todo app", "--yes"])
    assert result.exit_code == 2 and "start Docker Desktop" in result.output and calls == []
    assert "todo app" not in runner.invoke(cli.app, ["status"]).output  # no orphan job


def test_research_does_not_need_docker(monkeypatch):
    monkeypatch.setattr(cli, "docker_status", lambda s, a: (_ for _ in ()).throw(AssertionError("not asked")))
    use_completion(monkeypatch, lambda **kw: fake_response('{"title": "t", "goal": "g", "acceptance": ["a"]}', 1, 1))
    result = runner.invoke(cli.app, ["research", "lighthouses", "--yes", "--offline"])
    assert not isinstance(result.exception, AssertionError) and "Docker" not in result.output


def test_status_marks_a_running_job_whose_process_is_gone(monkeypatch):
    import fcntl
    use_completion(monkeypatch, lambda **kw: fake_response("ok", 1, 1))
    runner.invoke(cli.app, ["ask", "hello"])
    job_id = latest_job_id()
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    settings = load_settings()
    JobStore(connect(settings.db_path)).set_status(job_id, "running")
    assert "process gone; resume it" in runner.invoke(cli.app, ["status"]).output
    with open(settings.home / "jobs" / f"{job_id}.lock", "w") as live:
        fcntl.flock(live, fcntl.LOCK_EX)
        assert "process gone" not in runner.invoke(cli.app, ["status"]).output
