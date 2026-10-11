from __future__ import annotations

import re
from typing import Callable

from watchtower.engine.floor import WorkPackage
from watchtower.engine.sandbox import SandboxResult

SMOKE_SCRIPT = """\
import os, subprocess, sys, time, urllib.request
p = subprocess.Popen([sys.executable, sys.argv[1]], env={**os.environ, "PORT": "8000"},
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
status = None
for _ in range(40):
    if p.poll() is not None:
        break
    try:
        status = urllib.request.urlopen("http://127.0.0.1:8000/", timeout=1).status
        break
    except Exception as e:
        status = getattr(e, "code", None)
        if status:
            break
        time.sleep(0.25)
p.kill()
out = p.stdout.read().decode(errors="replace")[-1500:]
print("SMOKE_STATUS", status)
print(out)
"""
_STATUS = re.compile(r"SMOKE_STATUS (\S+)")


def smoke_test(run: Callable[[list[str]], SandboxResult], entry: str) -> WorkPackage:
    """Floor 3: start the app inside the sandbox and require HTTP 200 on GET /. No model involved."""
    result = run(["python", "-c", SMOKE_SCRIPT, entry])
    output = (result.stdout or "") + (result.stderr or "")
    match = _STATUS.search(output)
    status = match.group(1) if match and match.group(1) != "None" else None
    passed = status == "200" and not result.timed_out
    summary = (f"App {entry} {'answered HTTP 200 on GET /' if passed else f'did not answer HTTP 200 (got {status})'}"
               f"\n{output[-1200:]}")
    return WorkPackage("f3", summary, [entry], [], [{"check": "http", "pass": passed, "status": status}],
                       [] if passed else ["app did not answer HTTP 200"])
