import pytest
from typer.testing import CliRunner

from conftest import fake_response
from watchtower.interface import cli
from watchtower.engine.model_socket import ModelSocket

runner = CliRunner()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_OFFLINE", "1")  # tests never touch the network
    return tmp_path


def use_completion(monkeypatch, fn):
    monkeypatch.setattr(
        cli, "build_socket",
        lambda s, b, a: ModelSocket(s, b, a, completion_fn=fn, unload_fn=lambda m: None,
                                    resident_fn=lambda: [], free_ram_fn=lambda: 100),
    )


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


@pytest.mark.parametrize("exc,code,status", [(KeyboardInterrupt, 3, "paused"), (RuntimeError, 1, "failed")])
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


def latest_job_id():
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    return JobStore(connect(load_settings().db_path)).list()[0].id


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
    assert runner.invoke(cli.app, ["resume", job_id]).exit_code == 2
    result = runner.invoke(cli.app, ["resume", job_id, "--force"])
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
    assert "after its current step" in result.output
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


from conftest import TOWER_REPLIES, RoleModel


def use_roles(monkeypatch, replies=None):
    model = RoleModel({**TOWER_REPLIES, **(replies or {})})
    use_completion(monkeypatch, model)
    return model


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
    from watchtower.engine.governor.audit import AuditLog

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


class FakeDeployer:
    def __init__(self, fail=None):
        from watchtower.floors.f4_qa_deploy.deploy import Deployment
        self.fail, self.calls = fail, []
        self.dep = Deployment(1, "app", "job1", "wt-app-app:1", 8100, "active", "t", None)

    def _do(self, *call):
        from watchtower.floors.f4_qa_deploy.deploy import DeployError
        self.calls.append(call)
        if self.fail:
            raise DeployError(self.fail)
        return self.dep

    def deploy(self, job_id, name="app"):
        return self._do("deploy", job_id, name)

    def rollback(self, name):
        return self._do("rollback", name)

    def undeploy(self, name):
        self._do("undeploy", name)

    def list(self, limit=20):
        return [self.dep]


def done_app_job(monkeypatch, tmp_path):
    from conftest import APP_REPLIES, FakeSandbox
    use_roles(monkeypatch, APP_REPLIES)
    monkeypatch.setattr(cli, "make_sandbox", lambda settings, conn: FakeSandbox(tmp_path / "apps"))
    assert runner.invoke(cli.app, ["run", "a todo web app", "--yes"]).exit_code == 0
    return latest_job_id()


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
