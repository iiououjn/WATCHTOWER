"""Shared helpers and fixtures for test_cli*.py (split from one file to stay under 500 lines)."""
import pytest

from typer.testing import CliRunner

from conftest import fake_response

from watchtower.interface import checks, cli, deploy_cmds, knowledge_cmds, shell

from watchtower.engine.model_socket import ModelSocket

runner = CliRunner()

@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_OFFLINE", "1")  # tests never touch the network
    monkeypatch.setattr(checks, "docker_status", lambda s, a: (True, "ready"))  # nor real Docker (tests override)
    return tmp_path

def use_completion(monkeypatch, fn):
    monkeypatch.setattr(
        cli, "build_socket",
        lambda s, b, a: ModelSocket(s, b, a, completion_fn=fn, unload_fn=lambda m: None,
                                    resident_fn=lambda: [], free_ram_fn=lambda: 100),
    )

def latest_job_id():
    from watchtower.config import load_settings
    from watchtower.engine.db import connect
    from watchtower.engine.jobs import JobStore
    return JobStore(connect(load_settings().db_path)).list()[0].id

from conftest import TOWER_REPLIES, RoleModel

def use_roles(monkeypatch, replies=None):
    model = RoleModel({**TOWER_REPLIES, **(replies or {})})
    use_completion(monkeypatch, model)
    return model

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
    assert runner.invoke(cli.app, ["run", "a todo web app", "--yes"]).exit_code == 3  # 8a: awaits sign-off
    assert runner.invoke(cli.app, ["approve", latest_job_id()]).exit_code == 0
    return latest_job_id()


__all__ = ['CliRunner', 'FakeDeployer', 'ModelSocket', 'RoleModel', 'TOWER_REPLIES', 'checks', 'cli', 'deploy_cmds', 'knowledge_cmds', 'shell', 'done_app_job', 'fake_response', 'home', 'latest_job_id', 'pytest', 'runner', 'use_completion', 'use_roles']
