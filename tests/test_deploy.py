import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from watchtower.engine.deploy import DeployError, Deployer, http_ok
from watchtower.engine.deploy_scripts import EDGE, FORWARD
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.releases import Releases


class Docker:
    """Records docker argv; build reads the context so tests can see what would ship."""

    def __init__(self, fail=None, raise_os=False, stderr="Error response from daemon: boom\nmore"):
        self.calls, self.fail, self.raise_os, self.context = [], fail or (lambda argv: False), raise_os, None
        self.stderr = stderr

    def __call__(self, argv, **kw):
        if self.raise_os:
            raise OSError("no docker")
        self.calls.append(argv)
        if argv[:2] == ["docker", "build"]:
            ctx = argv[-1]
            self.context = {os.path.relpath(os.path.join(d, f), ctx): open(os.path.join(d, f)).read()
                            for d, _, files in os.walk(ctx) for f in files}
        if self.fail(argv):
            return subprocess.CompletedProcess(argv, 1, "", self.stderr)
        return subprocess.CompletedProcess(argv, 0, "sha256:abc\n", "")

    def runs(self, suffix):
        return [c for c in self.calls if c[:2] == ["docker", "run"] and f"wt-dep-app-{suffix}" in c]


@pytest.fixture
def setup(conn, settings):
    def make(health=lambda port: True, busy=(), **docker_kw):
        ws = settings.home / "workspaces" / "job1"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "app.py").write_text("print('app')\n")
        (ws / "test_app.py").write_text("import unittest\n")
        Releases(conn).record("job1", "app.py", ws, ["app.py", "test_app.py"])
        docker = Docker(**docker_kw)
        dep = Deployer(settings, conn, AuditLog(conn), run=docker, health=health,
                       port_free=lambda p: p not in busy)
        return dep, docker, ws
    return make


def test_deploy_builds_offline_and_runs_isolated_on_localhost(setup):
    dep, docker, _ = setup()
    d = dep.deploy("job1")
    assert (d.name, d.job_id, d.port, d.status) == ("app", "job1", 8100, "active")
    build = next(c for c in docker.calls if c[:2] == ["docker", "build"])
    assert "--network" in build and build[build.index("--network") + 1] == "none" and "--pull=false" in build
    assert set(docker.context) == {"Dockerfile", "forward.py", "app/app.py", "app/test_app.py"}
    assert docker.context["forward.py"] == FORWARD and "USER 1000:1000" in docker.context["Dockerfile"]
    edge_run = docker.runs("edge")[-1]
    assert EDGE in edge_run
    assert any(c[:4] == ["docker", "network", "create", "--internal"] for c in docker.calls)
    app = docker.runs("app")[-1]
    assert "-p" not in app and app[app.index("--network") + 1] == "wt-dep-app" and "--read-only" in app
    assert "--cap-drop" in app and d.image in app
    edge = docker.runs("edge")[-1]
    assert edge[edge.index("-p") + 1] == "127.0.0.1:8100:8000"
    assert ["docker", "network", "connect", "wt-dep-app", "wt-dep-app-edge"] in docker.calls


def test_bad_name_unknown_job_and_changed_workspace_are_refused(setup):
    dep, docker, ws = setup()
    with pytest.raises(DeployError, match="name"):
        dep.deploy("job1", name="Bad Name;rm")
    with pytest.raises(DeployError, match="no release"):
        dep.deploy("nojob")
    (ws / "app.py").write_text("print('tampered')\n")
    with pytest.raises(DeployError, match="changed after QA"):
        dep.deploy("job1")
    assert not any(c[:2] == ["docker", "build"] for c in docker.calls)


def test_build_failure_runs_nothing(setup):
    dep, docker, _ = setup(fail=lambda argv: argv[:2] == ["docker", "build"])
    with pytest.raises(DeployError, match="boom"):
        dep.deploy("job1")
    assert not docker.runs("app") and dep.list()[0].status == "failed"


def test_docker_missing_is_a_clean_error(setup):
    dep, _, _ = setup(raise_os=True)
    with pytest.raises(DeployError, match="Docker is not responding"):
        dep.deploy("job1")


def test_first_deploy_failing_health_is_removed(setup):
    dep, docker, _ = setup(health=lambda port: False)
    with pytest.raises(DeployError, match="nothing to roll back"):
        dep.deploy("job1")
    assert docker.calls[-2:] == [["docker", "rm", "-f", "wt-dep-app-app", "wt-dep-app-edge"],
                                 ["docker", "network", "rm", "wt-dep-app"]]
    assert dep.list()[0].status == "failed"


def test_redeploy_reuses_port_and_replaces_previous(setup):
    dep, docker, _ = setup(busy={8100})
    first = dep.deploy("job1")
    second = dep.deploy("job1")
    assert first.port == second.port == 8101
    assert [d.status for d in dep.list()] == ["active", "replaced"]


def test_redeploy_failing_health_rolls_back_to_previous(setup):
    answers = [True, False, True]
    dep, docker, _ = setup(health=lambda port: answers.pop(0))
    first = dep.deploy("job1")
    with pytest.raises(DeployError, match=f"rolled back to deployment {first.id}"):
        dep.deploy("job1")
    assert first.image in docker.runs("app")[-1]
    assert [d.status for d in dep.list()] == ["failed", "active"]


def test_rollback_and_undeploy(setup):
    dep, docker, _ = setup()
    first, second = dep.deploy("job1"), dep.deploy("job1")
    back = dep.rollback("app")
    assert back.id == first.id and first.image in docker.runs("app")[-1]
    assert {d.id: d.status for d in dep.list()} == {second.id: "rolled_back", first.id: "active"}
    with pytest.raises(DeployError, match="nothing to roll back"):
        dep.rollback("app")
    dep.undeploy("app")
    assert dep.list()[1].status == "stopped" and ["docker", "network", "rm", "wt-dep-app"] in docker.calls
    with pytest.raises(DeployError, match="nothing is deployed"):
        dep.undeploy("app")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


APP = '''
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"hello todos")
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
'''


def test_forwarder_reaches_an_app_bound_to_localhost(tmp_path):
    (tmp_path / "app.py").write_text(APP)
    listen, inner = free_port(), free_port()
    proc = subprocess.Popen([sys.executable, "-c", FORWARD, str(listen), "127.0.0.1", str(inner), "app.py"],
                            cwd=tmp_path, start_new_session=True)
    try:
        body = None
        for _ in range(40):
            try:
                body = urllib.request.urlopen(f"http://127.0.0.1:{listen}/", timeout=1).read()
                break
            except OSError:
                time.sleep(0.25)
        assert body == b"hello todos"
    finally:
        os.killpg(proc.pid, 9)
        proc.wait()


def test_restore_waits_for_health_and_says_when_previous_is_not_answering(setup):
    answers = [True, False, False]
    dep, docker, _ = setup(health=lambda port: answers.pop(0))
    first = dep.deploy("job1")
    with pytest.raises(DeployError, match=f"restored deployment {first.id} is not answering"):
        dep.deploy("job1")
    assert answers == []


def test_build_failure_leaves_the_running_previous_deployment_alone(setup):
    builds = []
    dep, docker, _ = setup(fail=lambda argv: argv[:2] == ["docker", "build"] and builds.append(1) is None
                           and len(builds) > 1)
    first = dep.deploy("job1")
    before = len(docker.calls)
    with pytest.raises(DeployError, match="boom"):
        dep.deploy("job1")
    after = docker.calls[before:]
    assert [c[:2] for c in after] == [["docker", "build"]]
    assert {d.id: d.status for d in dep.list()}[first.id] == "active"


def test_failed_restore_leaves_no_orphans(setup):
    answers = [True, False]
    starts = []

    def fail(argv):
        if argv[:2] == ["docker", "run"] and "wt-dep-app-edge" in argv:
            starts.append(1)
            return len(starts) == 3  # edge of the restore fails (1: first deploy, 2: second, 3: restore)
        return False
    dep, docker, _ = setup(health=lambda port: answers.pop(0), fail=fail)
    first = dep.deploy("job1")
    with pytest.raises(DeployError, match=f"restoring deployment {first.id} also failed"):
        dep.deploy("job1")
    assert docker.calls[-2:] == [["docker", "rm", "-f", "wt-dep-app-app", "wt-dep-app-edge"],
                                 ["docker", "network", "rm", "wt-dep-app"]]
    assert {d.id: d.status for d in dep.list()}[first.id] == "failed"


def test_rollback_whose_target_cannot_start_restores_current(setup):
    dep, docker, _ = setup()
    first, second = dep.deploy("job1"), dep.deploy("job1")
    docker.fail = lambda argv: argv[:2] == ["docker", "run"] and first.image in argv
    with pytest.raises(DeployError, match=f"rolled back to deployment {second.id}"):
        dep.rollback("app")
    assert second.image in docker.runs("app")[-1]
    assert {d.id: d.status for d in dep.list()} == {second.id: "active", first.id: "replaced"}


def test_rollback_skips_targets_whose_image_is_gone_before_stopping_anything(setup):
    dep, docker, _ = setup()
    dep.deploy("job1")
    dep.deploy("job1")
    docker.fail = lambda argv: argv[:3] == ["docker", "image", "inspect"]
    before = len(docker.calls)
    with pytest.raises(DeployError, match="nothing to roll back"):
        dep.rollback("app")
    assert not any(c[:3] == ["docker", "rm", "-f"] for c in docker.calls[before:])


def test_prune_never_deletes_rollback_targets_for_failed_deploys(setup):
    answers = [True, True, False, True, False, True, False, True, True]  # each failure: new, then restore
    dep, docker, _ = setup(health=lambda port: answers.pop(0))
    a, b = dep.deploy("job1"), dep.deploy("job1")
    for _ in range(3):
        with pytest.raises(DeployError):
            dep.deploy("job1")
    dep.deploy("job1")
    removed = [c[2] for c in docker.calls if c[:2] == ["docker", "rmi"]]
    assert a.image not in removed and b.image not in removed
    assert {f"wt-app-app:{i}" for i in (3, 4, 5)} <= set(removed)


def test_undeploy_only_reports_stopped_when_docker_removed_it(setup):
    dep, docker, _ = setup()
    dep.deploy("job1")
    docker.fail = lambda argv: argv[:3] == ["docker", "rm", "-f"]
    with pytest.raises(DeployError, match="boom"):
        dep.undeploy("app")
    assert dep.list()[0].status == "active"
    docker.stderr = "Error response from daemon: No such container: wt-dep-app-edge"
    dep.undeploy("app")
    assert dep.list()[0].status == "stopped"


def serve(handler_body, port):
    code = ("import http.server, sys\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def log_message(self, *a): pass\n" + handler_body +
            f"http.server.HTTPServer(('127.0.0.1', {port}), H).serve_forever()\n")
    return subprocess.Popen([sys.executable, "-c", code])


def wait_up(port):
    for _ in range(40):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.25)


def test_health_check_never_follows_the_apps_redirects(tmp_path):
    trap, app = free_port(), free_port()
    hits = tmp_path / "hits"
    procs = [serve("    def do_GET(self):\n        open(%r, 'a').write('x'); self.send_response(200); self.end_headers()\n"
                   % str(hits), trap),
             serve("    def do_GET(self):\n        self.send_response(302); self.send_header('Location', "
                   f"'http://127.0.0.1:{trap}/leak'); self.end_headers()\n", app)]
    try:
        wait_up(trap), wait_up(app)
        assert http_ok(app, wait=3) is True and not hits.exists()
    finally:
        for p in procs:
            p.kill()
            p.wait()


def test_edge_adds_strict_csp_and_drops_the_apps_own(tmp_path):
    app, edge = free_port(), free_port()
    procs = [serve("    def do_GET(self):\n        self.send_response(200); self.send_header('Content-Security-Policy',"
                   " 'default-src *'); self.end_headers(); self.wfile.write(b'hello')\n"
                   "    def do_POST(self):\n        n = int(self.headers['Content-Length']); b = self.rfile.read(n)\n"
                   "        self.send_response(200); self.end_headers(); self.wfile.write(b)\n", app),
             subprocess.Popen([sys.executable, "-c", EDGE, str(edge), "127.0.0.1", str(app)])]
    try:
        wait_up(app), wait_up(edge)
        r = urllib.request.urlopen(f"http://127.0.0.1:{edge}/", timeout=5)
        csp = r.headers.get_all("Content-Security-Policy")
        assert r.read() == b"hello" and len(csp) == 1 and "connect-src 'self'" in csp[0]
        post = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{edge}/add", data=b"item=milk"),
                                      timeout=5)
        assert post.read() == b"item=milk"
    finally:
        for p in procs:
            p.kill()
            p.wait()


def test_forwarder_keeps_the_reply_after_the_client_half_closes(tmp_path):
    (tmp_path / "app.py").write_text(APP)
    listen, inner = free_port(), free_port()
    proc = subprocess.Popen([sys.executable, "-c", FORWARD, str(listen), "127.0.0.1", str(inner), "app.py"],
                            cwd=tmp_path, start_new_session=True)
    try:
        wait_up(listen)
        for _ in range(40):
            s = socket.create_connection(("127.0.0.1", listen), timeout=5)
            s.sendall(b"GET / HTTP/1.0\r\n\r\n")
            s.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := s.recv(65536):
                data += chunk
            s.close()
            if data:
                break
            time.sleep(0.25)
        assert data.endswith(b"hello todos")
    finally:
        os.killpg(proc.pid, 9)
        proc.wait()
