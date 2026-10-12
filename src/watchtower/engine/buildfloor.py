from __future__ import annotations

import re
from typing import Callable

from watchtower.engine.floor import WorkPackage
from watchtower.engine.sandbox import SandboxResult

SMOKE_SCRIPT = """\
import os, subprocess, sys, time, urllib.request
log = open("/tmp/app.log", "wb")
p = subprocess.Popen([sys.executable, sys.argv[1]], env={**os.environ, "PORT": "8000"},
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
status, body = None, ""
for _ in range(40):
    if p.poll() is not None:
        break
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8000/", timeout=1)
        status, body = r.status, r.read(200000).decode(errors="replace")
        break
    except Exception as e:
        status = getattr(e, "code", None)
        if status:
            break
        time.sleep(0.25)
try:
    os.killpg(p.pid, 9)
except Exception:
    p.kill()
log.close()
out = open("/tmp/app.log", "rb").read().decode(errors="replace")[-1500:]
print("SMOKE_STATUS", status)
expect = sys.argv[2] if len(sys.argv) > 2 else ""
print("SMOKE_TEXT", "yes" if expect and expect in body else "no")
print(out)
"""
_STATUS = re.compile(r"SMOKE_STATUS (\S+)")
_TEXT = re.compile(r"SMOKE_TEXT (yes|no)")


def smoke_test(run: Callable[[list[str]], SandboxResult], entry: str, expect: str = "") -> WorkPackage:
    """Floor 3: start the app inside the sandbox and require HTTP 200 on GET /. The Build Lead's expected
    home-page text is a soft check: a miss becomes an open question for the gate, not a failure."""
    result = run(["python", "-c", SMOKE_SCRIPT, entry] + ([expect] if expect else []))
    output = (result.stdout or "") + (result.stderr or "")
    match = _STATUS.search(output)
    status = match.group(1) if match and match.group(1) != "None" else None
    passed = status == "200" and not result.timed_out
    summary = (f"App {entry} {'answered HTTP 200 on GET /' if passed else f'did not answer HTTP 200 (got {status})'}"
               f"\n{output[-1200:]}")
    text = _TEXT.search(output)
    questions = [] if passed else ["app did not answer HTTP 200"]
    if passed and expect and not (text and text.group(1) == "yes"):
        questions.append(f"home page does not show {expect!r} (F3 Build Lead expected it)")
    return WorkPackage("f3", summary, [entry], [], [{"check": "http", "pass": passed, "status": status}], questions)
