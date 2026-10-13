from __future__ import annotations

import json
import re
from typing import Callable

from watchtower.floors.framework import WorkPackage
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
code = p.poll() if status is None else None  # the app stopped by itself before it answered
try:
    os.killpg(p.pid, 9)
except Exception:
    p.kill()
log.close()
out = open("/tmp/app.log", "rb").read().decode(errors="replace")[-1500:]
print("SMOKE_STATUS", status)
print("SMOKE_EXIT", code)
expect = sys.argv[2] if len(sys.argv) > 2 else ""
print("SMOKE_TEXT", "yes" if expect and expect in body else "no")
print(out)
"""
_STATUS = re.compile(r"SMOKE_STATUS (\S+)")
_TEXT = re.compile(r"SMOKE_TEXT (yes|no)")
_EXIT = re.compile(r"SMOKE_EXIT (-?\d+|None)")
EXITED = ("App {entry} exited with code {code} before answering any request: it ran and stopped. When run as "
          "`python {entry}` it must start its HTTP server and keep serving, e.g. end the file with "
          "`if __name__ == \"__main__\":` and a call to the function that calls serve_forever().")


def smoke_test(run: Callable[[list[str]], SandboxResult], entry: str, expect: str = "") -> WorkPackage:
    """Floor 3: start the app inside the sandbox and require HTTP 200 on GET /. The Build Lead's expected
    home-page text is a soft check: a miss becomes an open question for the gate, not a failure."""
    result = run(["python", "-I", "-c", SMOKE_SCRIPT, entry] + ([expect] if expect else []))
    output = (result.stdout or "") + (result.stderr or "")
    match = _STATUS.search(output)
    status = match.group(1) if match and match.group(1) != "None" else None
    passed = status == "200" and not result.timed_out
    exited = _EXIT.search(output)  # first match: the tower's own line comes before the app's log
    head = (f"App {entry} {'answered HTTP 200 on GET /' if passed else f'did not answer HTTP 200 (got {status})'}")
    if not passed and exited and exited.group(1) == "0":  # it ran to the end: nothing started the server
        head = EXITED.format(entry=entry, code=0)
    elif not passed and exited and exited.group(1) != "None":  # a crash: short head, the error below stays seen
        head = f"App {entry} crashed (exit code {exited.group(1)}) before answering any request; its error is below."
    summary = f"{head}\n{output[-1200:]}"
    text = _TEXT.search(output)
    questions = [] if passed else ["app did not answer HTTP 200"]
    if passed and expect and not (text and text.group(1) == "yes"):
        questions.append(f"home page does not show {expect!r} (F3 Build Lead expected it)")
    return WorkPackage("f3", summary, [entry], [], [{"check": "http", "pass": passed, "status": status}], questions)


# Runs INSIDE the sandbox. argv: entry, paths-JSON. F3's workers, by code: start the app, GET every route of
# the contract (redirects are not followed: a 3xx is an answer), print one WATCHTOWER_PROBE line, then the log.
PROBE_SCRIPT = """\
import json, os, subprocess, sys, time, urllib.error, urllib.request
port = os.environ.get("WT_PORT", "8000")
base = "http://127.0.0.1:" + port
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None
opener = urllib.request.build_opener(NoRedirect)
log = open("/tmp/probe.log", "wb")
p = subprocess.Popen([sys.executable, sys.argv[1]], env={**os.environ, "PORT": port},
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
for _ in range(40):
    if p.poll() is not None:
        break
    try:
        opener.open(base + "/", timeout=1)
        break
    except urllib.error.HTTPError:
        break
    except Exception:
        time.sleep(0.25)
results = []
for path in json.loads(sys.argv[2]):
    try:
        with opener.open(base + path, timeout=2) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = None
    results.append({"path": path, "status": status})
try:
    os.killpg(p.pid, 9)
except Exception:
    p.kill()
log.close()
print("WATCHTOWER_PROBE " + json.dumps(results))
print("WATCHTOWER_LOG " + json.dumps(open(log.name, "rb").read().decode(errors="replace")[-2500:]))
"""
_ACCESS = re.compile(r'"(GET|POST|HEAD|PUT|DELETE) \S* HTTP/[\d.]+" \d{3}')
_ERROR = re.compile(r"\b\w*(Error|Exception)\b")
_PROBE = re.compile(r"^WATCHTOWER_PROBE (.*)$", re.M)
_PROBE_LOG = re.compile(r"^WATCHTOWER_LOG (.*)$", re.M)
_ROUTE_PATH = re.compile(r"/[A-Za-z0-9._~/?=&%+-]{0,80}")
MAX_PROBES = 8


def _probe_paths(routes: list[dict]) -> list[str]:
    paths = [r.get("path") for r in routes if isinstance(r, dict) and r.get("method") == "GET"]
    safe = [p for p in paths if isinstance(p, str) and p != "/" and _ROUTE_PATH.fullmatch(p)
            and "//" not in p and ".." not in p]
    return list(dict.fromkeys(safe))[:MAX_PROBES]


def route_probe(run: Callable[[list[str]], SandboxResult], entry: str, routes: list[dict]) -> WorkPackage:
    """Floor 3, full app: every GET route of the architect's contract must answer (no 404, no 5xx, no
    silence). Exactly one result line counts: a second one means the app tried to forge it."""
    paths = _probe_paths(routes)
    if not paths:
        return WorkPackage("f3", "Full app: no other GET routes to probe (MVP: GET / answered)", [entry], [],
                           [{"check": "routes", "pass": True, "results": []}], [])
    result = run(["python", "-I", "-c", PROBE_SCRIPT, entry, json.dumps(paths)])
    output = (result.stdout or "") + (result.stderr or "")
    found = _PROBE.findall(output)
    try:
        results = json.loads(found[0]) if len(found) == 1 else None
    except ValueError:
        results = None
    if not isinstance(results, list) or [r.get("path") if isinstance(r, dict) else None for r in results] != paths:
        results = [{"path": p, "status": None} for p in paths]
        bad_note = "probe result missing, duplicated or incomplete"
    else:
        bad_note = ""
    failed = [r for r in results if not isinstance(r.get("status"), int) or r["status"] >= 500
              or r["status"] == 404]
    logs = _PROBE_LOG.findall(output)
    try:
        log = json.loads(logs[-1]) if logs else ""
    except ValueError:
        log = ""
    if result.timed_out:
        bad_note = "probe timed out: the app answered too slowly"
    useful = [ln.strip() for ln in str(log).splitlines() if ln.strip() and not _ACCESS.search(ln)]
    errors = [ln for ln in useful if _ERROR.search(ln)]  # the exception, not the server's access log
    error = (errors or useful)[-2:] if failed else []
    lines = [f"- GET {r['path']} → {r['status'] if r['status'] is not None else 'no answer'}" for r in results]
    summary = (f"Full app: {len(results) - len(failed)}/{len(results)} routes answered"
               + (f" ({bad_note})" if bad_note else "")  # the cause first: feedback items are cut at 600 chars
               + (f"\nApp error: {' | '.join(error)[-300:]}" if error else "") + "\n" + "\n".join(lines)
               + (f"\nApp output:\n{chr(10).join(useful)[-600:]}" if failed and useful else ""))
    questions = [f"GET {r['path']} did not answer properly" for r in failed[:3]]
    return WorkPackage("f3", summary, [entry], [], [{"check": "routes", "pass": not failed, "results": results}],
                       questions)


def build_check(run: Callable[[list[str]], SandboxResult], entry: str, expect: str,
                routes: list[dict]) -> WorkPackage:
    """Floor 3 office: MVP first (GET / answers 200), then the full app (every contract route answers)."""
    mvp = smoke_test(run, entry, expect)
    if not mvp.checks_run[-1]["pass"]:
        return mvp
    full = route_probe(run, entry, routes)
    return WorkPackage("f3", full.summary + "\nMVP: " + mvp.summary.splitlines()[0], [entry], [],
                       mvp.checks_run + full.checks_run, mvp.open_questions + full.open_questions)
