"""8a review r3: the app and the tower's harness run under different uids inside the sandbox. With one shared uid
the app could ptrace the harness (or PID 1) and rewrite its result in memory. These tests start the real sandbox
image with a harmless probe app (a test fixture) and are skipped when Docker or the image is missing."""
import os
import shutil

import pytest

from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.sandbox import EMIT, Sandbox, result_log
from watchtower.floors.f3_build.buildfloor import PROBE_SCRIPT, SMOKE_SCRIPT, smoke_test
from watchtower.floors.f4_qa_deploy.qafloor import QA_SCRIPT
from watchtower.floors.f5_oversight.probe import XSS_SCRIPT

# The probe app: tries to attach to its parent (the harness) and to PID 1, and to open their memory and fds.
# PTRACE_SEIZE does not stop the target, so a successful attach cannot hang the run.
PTRACE_APP = """\
import ctypes, os, time
time.sleep(0.5)
libc = ctypes.CDLL(None, use_errno=True)
uids = [ln.split()[1:] for ln in open("/proc/%d/status" % os.getppid()) if ln.startswith("Uid:")][0]
out = ["uid=%d" % os.getuid(), "harness_uids=" + ",".join(uids)]
for name, pid in (("harness", os.getppid()), ("init", 1)):
    seized = libc.ptrace(0x4206, pid, 0, 0) == 0
    try:
        open("/proc/%d/mem" % pid, "r+b").close()
        mem = True
    except OSError:
        mem = False
    try:
        os.listdir("/proc/%d/fd" % pid)
        fds = True
    except OSError:
        fds = False
    out.append("%s ptrace=%s mem=%s fd=%s" % (name, seized, mem, fds))
print(" ".join(out), flush=True)
"""


@pytest.fixture
def sandbox(settings, conn):
    box = Sandbox(settings, AuditLog(conn))
    if shutil.which("docker") is None or box.check() is not None:
        pytest.skip("Docker or the pinned sandbox image is not available")
    return box


def test_the_app_cannot_ptrace_or_open_the_harness_or_init(sandbox):
    (sandbox.workspace("uids") / "app.py").write_text(PTRACE_APP)
    result = sandbox.run("uids", ["python", "-I", "-c", PROBE_SCRIPT, "app.py", "[]"], timeout=60)
    log = result_log(result, "WATCHTOWER_LOG", "")
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert "uid=1001" in log and "harness_uids=1000,1000,1000,1000" in log, log  # the harness left uid 0
    assert "harness ptrace=False mem=False fd=False" in log, log
    assert "init ptrace=False mem=False fd=False" in log, log


def test_split_mode_without_root_fails_closed(monkeypatch, tmp_path):
    """A harness told to split uids (WT_SPLIT) but not started as root must crash (exit != 0, FAIL), never run
    the app under its own uid."""
    if os.geteuid() == 0:
        pytest.skip("runs as root")
    scope = {}
    exec(EMIT, scope)
    monkeypatch.setenv("WT_SPLIT", "1")
    with open(tmp_path / "log", "wb") as log, pytest.raises(PermissionError):
        scope["start"]("app.py", "8000", log)


@pytest.mark.parametrize("script", [SMOKE_SCRIPT, PROBE_SCRIPT, QA_SCRIPT, XSS_SCRIPT])
def test_every_harness_starts_the_app_through_start(script):
    body = script[len(EMIT):]
    assert script.startswith(EMIT) and "= start(sys.argv[1], " in body and "Popen" not in body
    assert "stop(p)" in body and "killpg" not in body


# An honest app under the split: it writes a data file in its working dir and serves GET / as before.
HONEST_APP = """\
import http.server, os
open("data.json", "w").write("[]")
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Todos " + open("data.json", "rb").read())
http.server.HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"""


def test_an_honest_app_still_passes_smoke_under_split_uids(sandbox):
    (sandbox.workspace("honest") / "app.py").write_text(HONEST_APP)
    pkg = smoke_test(lambda cmd: sandbox.run("honest", cmd, timeout=60), "app.py", "Todos")
    assert pkg.checks_run[-1]["pass"] is True and pkg.open_questions == [], pkg.summary


def test_a_plain_command_runs_as_the_app_uid_without_capabilities(sandbox):
    probe = ("import os; print(os.getresuid(), os.getgroups(), "
             "open('/proc/self/status').read().split('CapEff:')[1].split()[0])")
    result = sandbox.run("plain", ["python", "-c", probe], timeout=60)
    assert result.stdout.split("\n")[0] == "(1001, 1001, 1001) [] 0000000000000000", (result.stdout, result.stderr)
