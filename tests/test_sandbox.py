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
    assert f"{settings.home / 'workspaces' / 'job1'}:/src:ro" in argv
    assert argv[-3:] == ["python", "-c", "print('hello')"]


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
    with pytest.raises(SandboxUnavailable, match="docker pull python:latest"):
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
    assert argv[argv.index("python:latest") + 1:][:4] == ["timeout", "-s", "KILL", "5"]


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


def test_workspace_is_mounted_read_only_and_copied_to_capped_scratch(settings, audit):
    docker = FakeDocker()
    Sandbox(settings, audit, run=docker).run("j", ["python", "-m", "unittest"])
    argv = docker.run_argv()
    assert f"{settings.home / 'workspaces' / 'j'}:/src:ro" in argv
    assert not any(a.endswith(":/work:rw") for a in argv)
    assert "/work:rw,size=64m,uid=1000,gid=1000" in argv
    tail = argv[argv.index("python:latest") + 1:]
    assert tail[:4] == ["timeout", "-s", "KILL", "60"] and "cp -a /src/. /work/" in tail[6]
    assert tail[-3:] == ["python", "-m", "unittest"]


# 8a (audit D-M2): AI code can print gigabytes inside its time limit; the host keeps only a bounded tail
import sys  # noqa: E402
import tracemalloc  # noqa: E402

from watchtower.engine.sandbox import capped_run  # noqa: E402


def test_sandbox_captures_through_the_bounded_reader_by_default(settings, audit):
    assert Sandbox(settings, audit)._run is capped_run


def test_capped_run_keeps_a_bounded_tail_of_a_flood():
    flood = "import sys\nfor _ in range(300): sys.stdout.write('x' * 99_999 + 'y')\nsys.stderr.write('done')"
    tracemalloc.start()
    try:
        proc = capped_run([sys.executable, "-c", flood], capture_output=True, text=True, timeout=60)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert proc.returncode == 0 and proc.stderr == "done" and proc.stdout.endswith("xy")
    assert MAX_OUTPUT <= len(proc.stdout) <= 4 * MAX_OUTPUT
    assert peak < 3_000_000  # 30 MB went through; subprocess.run would have held all of it


def test_capped_run_times_out_and_kills():
    import time
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        capped_run([sys.executable, "-c", "import time; print('hi', flush=True); time.sleep(30)"], timeout=1)
    assert time.monotonic() - start < 10  # killed, not waited out


def test_capped_run_replaces_broken_utf8_and_keeps_the_exit_code():
    proc = capped_run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ok\\xff'); sys.exit(3)"],
                      timeout=30)
    assert (proc.returncode, proc.stdout) == (3, "ok�")
