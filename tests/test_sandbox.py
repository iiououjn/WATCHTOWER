import subprocess
from types import SimpleNamespace

import pytest

from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.sandbox import MAX_OUTPUT, Sandbox, SandboxUnavailable


class FakeDocker:
    def __init__(self, daemon=True, image=True, run_result=None, hang=False):
        self.calls = []
        self.daemon, self.image, self.hang = daemon, image, hang
        self.run_result = run_result or SimpleNamespace(returncode=0, stdout="hello\n", stderr="")

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if argv[:2] == ["docker", "info"]:
            return SimpleNamespace(returncode=0 if self.daemon else 1, stdout="27.0", stderr="")
        if argv[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=0 if self.image else 1, stdout="", stderr="")
        if argv[:2] == ["docker", "run"]:
            if self.hang:
                raise subprocess.TimeoutExpired(argv, kw["timeout"])
            return self.run_result
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def run_argv(self):
        return next(a for a in self.calls if a[:2] == ["docker", "run"])


@pytest.fixture
def audit(conn):
    return AuditLog(conn)


def test_runs_command_with_hardening_flags(settings, audit):
    docker = FakeDocker()
    result = Sandbox(settings, audit, run=docker).run("job1", ["python", "-c", "print('hello')"])
    assert (result.exit_code, result.stdout, result.timed_out) == (0, "hello\n", False)
    argv = docker.run_argv()
    for flag in ["--network", "none", "--read-only", "--cap-drop", "ALL", "--pids-limit", "128",
                 "--memory", "512m", "--user", "1000:1000", "--pull", "never", "no-new-privileges"]:
        assert flag in argv
    assert f"{settings.home / 'workspaces' / 'job1'}:/work:rw" in argv
    assert argv[-8:] == ["python:3.12-slim", "timeout", "-s", "KILL", "60", "python", "-c", "print('hello')"]


@pytest.mark.parametrize("bad", ["../../Users/rishi", "a/b", "", "job 1", ".."])
def test_rejects_hostile_job_ids(settings, audit, bad):
    docker = FakeDocker()
    with pytest.raises(ValueError):
        Sandbox(settings, audit, run=docker).run(bad, ["true"])
    assert not any(a[:2] == ["docker", "run"] for a in docker.calls)


def test_docker_not_running(settings, audit):
    with pytest.raises(SandboxUnavailable, match="Docker is not running"):
        Sandbox(settings, audit, run=FakeDocker(daemon=False)).run("j", ["true"])


def test_docker_not_installed(settings, audit):
    def missing(argv, **kw):
        raise FileNotFoundError("docker")

    sandbox = Sandbox(settings, audit, run=missing)
    assert "not installed" in sandbox.check()
    with pytest.raises(SandboxUnavailable):
        sandbox.run("j", ["true"])


def test_image_missing_gives_pull_hint(settings, audit):
    with pytest.raises(SandboxUnavailable, match="docker pull python:3.12-slim"):
        Sandbox(settings, audit, run=FakeDocker(image=False)).run("j", ["true"])


def test_check_ok(settings, audit):
    assert Sandbox(settings, audit, run=FakeDocker()).check() is None


def test_timeout_kills_container(settings, audit):
    docker = FakeDocker(hang=True)
    result = Sandbox(settings, audit, run=docker).run("j", ["sleep", "999"], timeout=1)
    assert result.timed_out and result.exit_code == 124
    name = docker.run_argv()[docker.run_argv().index("--name") + 1]
    assert ["docker", "kill", name] in docker.calls


def test_output_is_truncated(settings, audit):
    big = SimpleNamespace(returncode=0, stdout="x" * (MAX_OUTPUT + 500), stderr="")
    assert len(Sandbox(settings, audit, run=FakeDocker(run_result=big)).run("j", ["x"]).stdout) == MAX_OUTPUT


def test_empty_command_rejected(settings, audit):
    with pytest.raises(ValueError):
        Sandbox(settings, audit, run=FakeDocker()).run("j", [])


def test_runs_are_audited(settings, audit):
    Sandbox(settings, audit, run=FakeDocker()).run("j", ["true"])
    assert [e.action for e in audit.entries(job_id="j")] == ["sandbox_run", "sandbox_result"]


def test_container_has_hard_in_container_time_limit(settings, audit):
    docker = FakeDocker()
    Sandbox(settings, audit, run=docker).run("j", ["sleep", "999"], timeout=5)
    argv = docker.run_argv()
    assert argv[argv.index("python:3.12-slim") + 1:][:4] == ["timeout", "-s", "KILL", "5"]


def test_failed_kill_falls_back_to_force_remove(settings, audit):
    docker = FakeDocker(hang=True)
    real = docker.__call__

    def run(argv, **kw):
        if argv[:2] == ["docker", "kill"]:
            docker.calls.append(argv)
            return SimpleNamespace(returncode=1, stdout="", stderr="No such container")
        return real(argv, **kw)

    Sandbox(settings, audit, run=run).run("j", ["sleep", "999"], timeout=1)
    name = docker.run_argv()[docker.run_argv().index("--name") + 1]
    assert ["docker", "rm", "-f", name] in docker.calls


def test_docker_daemon_error_during_run_is_unavailable(settings, audit):
    err = SimpleNamespace(returncode=125, stdout="",
                          stderr="docker: Error response from daemon: mounts denied.\nmore")
    with pytest.raises(SandboxUnavailable, match="mounts denied"):
        Sandbox(settings, audit, run=FakeDocker(run_result=err)).run("j", ["true"])


def test_agent_exit_125_without_docker_prefix_is_a_normal_result(settings, audit):
    own = SimpleNamespace(returncode=125, stdout="", stderr="my script failed")
    assert Sandbox(settings, audit, run=FakeDocker(run_result=own)).run("j", ["x"]).exit_code == 125


def test_hung_daemon_on_image_inspect_is_reported_not_raised(settings, audit):
    docker = FakeDocker()

    def run(argv, **kw):
        if argv[:3] == ["docker", "image", "inspect"]:
            raise subprocess.TimeoutExpired(argv, 15)
        return docker(argv, **kw)

    assert "not responding" in Sandbox(settings, audit, run=run).check()


def test_command_arguments_are_not_audited(settings, audit, conn):
    Sandbox(settings, audit, run=FakeDocker()).run("j", ["curl", "-H", "Authorization: sk-secret-9"])
    raw = " ".join(r[0] for r in conn.execute("SELECT detail FROM audit_log"))
    assert "sk-secret-9" not in raw and "curl" in raw
