from __future__ import annotations

import json
import re
from typing import Callable

from watchtower.engine.floor import WorkPackage, untrusted
from watchtower.engine.model_socket import BadModelOutput
from watchtower.engine.sandbox import SandboxResult
from watchtower.roles import Role

MAX_CHECKS = 8
_PATH = re.compile(r"/[A-Za-z0-9_\-./?=&%+]*")
QA_PROMPT = (
    "Spec:\nTitle: {title}\nGoal: {goal}\nAcceptance criteria:\n{acceptance}\n\nThe app's code:\n{code}\n\n"
    "Write at most 8 HTTP checks that prove the acceptance criteria work, in order (later checks may rely on "
    "earlier ones, e.g. POST a form, then GET the page and expect the new text). Paths start with '/'. "
    'Reply as JSON: {{"checks": [{{"name": string, "method": "GET" or "POST", "path": string, '
    '"form": {{field: value}}, "expect_status": number, "expect_text": string}}]}}'
)

# Runs INSIDE the sandbox. argv: entry, checks-JSON. Starts the app, runs each check in order against it,
# prints one WATCHTOWER_QA line with the results, then the app's log tail.
QA_SCRIPT = """\
import json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
port = os.environ.get("WT_PORT", "8000")
base = "http://127.0.0.1:" + port
log = open("/tmp/app.log", "wb")
p = subprocess.Popen([sys.executable, sys.argv[1]], env={**os.environ, "PORT": port},
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
for _ in range(40):
    if p.poll() is not None:
        break
    try:
        urllib.request.urlopen(base + "/", timeout=1)
        break
    except urllib.error.HTTPError:
        break
    except Exception:
        time.sleep(0.25)
results = []
for c in json.loads(sys.argv[2]):
    data = urllib.parse.urlencode(c["form"]).encode() if c["method"] == "POST" else None
    status, body, detail = None, "", ""
    try:
        with urllib.request.urlopen(urllib.request.Request(base + c["path"], data=data, method=c["method"]),
                                    timeout=3) as r:
            status, body = r.status, r.read(200000).decode(errors="replace")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read(200000).decode(errors="replace")
    except Exception as e:
        detail = type(e).__name__ + ": " + str(e)[:200]
    ok = status == c["expect_status"] and c["expect_text"] in body
    if not ok and not detail:
        detail = f"expected {c['expect_status']} with {c['expect_text']!r}, got {status}: {body[:300]}"
    results.append({"name": c["name"], "pass": ok, "status": status, "detail": detail})
try:
    os.killpg(p.pid, 9)
except Exception:
    p.kill()
log.close()
print("WATCHTOWER_QA " + json.dumps(results))
# the app's own output is JSON-encoded on one line, so nothing it prints can pose as a result line
print("WATCHTOWER_LOG " + json.dumps(open(log.name, "rb").read().decode(errors="replace")[-1000:]))
"""
_RESULT = re.compile(r"^WATCHTOWER_QA (.*)$", re.M)
_LOG = re.compile(r"^WATCHTOWER_LOG (.*)$", re.M)


def _str(value, cap: int) -> str | None:
    return value if isinstance(value, str) and len(value) <= cap else None


def _check(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    method = str(raw.get("method") or "GET").upper()
    path = _str(raw.get("path"), 200)
    if method not in ("GET", "POST") or not path or not _PATH.fullmatch(path) or ".." in path or "//" in path:
        return None
    form = raw.get("form") or {}
    if not isinstance(form, dict) or (form and method != "POST") or len(form) > 10:
        return None
    if not all(_str(k, 50) and _str(v, 200) is not None for k, v in form.items()):
        return None
    status = raw.get("expect_status")
    status = status if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599 else 200
    status = 200 if 300 <= status < 400 else status  # the runner follows redirects, so 3xx means the page after
    return {"name": _str(raw.get("name"), 80) or path, "method": method, "path": path, "form": dict(form),
            "expect_status": status, "expect_text": _str(raw.get("expect_text"), 200) or ""}


_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,30}")
MAX_ROUTES = 8
_SAFE_TEXT = re.compile(r"[^<>{}\x00-\x1f\x7f]*")


def _route(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    method = str(raw.get("method") or "GET").upper()
    path = _str(raw.get("path"), 200)
    if method not in ("GET", "POST") or not path or not _PATH.fullmatch(path) or ".." in path or "//" in path:
        return None
    fields = raw.get("fields") or []
    if not isinstance(fields, list) or len(fields) > 6 or not all(isinstance(f, str) and _FIELD.fullmatch(f)
                                                                  for f in fields):
        return None
    shows = raw.get("shows") or ""
    if not isinstance(shows, str) or len(shows) > 100 or not _SAFE_TEXT.fullmatch(shows):
        return None
    return {"method": method, "path": path, "fields": list(fields), "shows": shows}


def parse_routes(raw) -> list[dict]:
    """The architect's routes contract, kept only if every value is safe to show other floors."""
    return [r for r in map(_route, raw if isinstance(raw, list) else []) if r][:MAX_ROUTES]


def parse_checks(reply) -> list[dict]:
    """Keep only checks that are safe to run: local relative paths, small forms, sane values."""
    raw = reply.get("checks") if isinstance(reply, dict) else None
    checks = [c for c in map(_check, raw if isinstance(raw, list) else []) if c]
    return checks[:MAX_CHECKS]


def run_qa(run: Callable[[list[str]], SandboxResult], entry: str, checks: list[dict]) -> WorkPackage:
    """Floor 4: run the QA checks against the app inside the sandbox. No model involved."""
    result = run(["python", "-c", QA_SCRIPT, entry, json.dumps(checks)])
    output = (result.stdout or "") + (result.stderr or "")
    found = _RESULT.findall(output)
    try:
        results = json.loads(found[0]) if len(found) == 1 else None  # a second line means someone forged one
    except ValueError:
        results = None
    if (not isinstance(results, list) or not all(isinstance(r, dict) for r in results)
            or [r.get("name") for r in results] != [c["name"] for c in checks]):
        results = [{"name": "qa", "pass": False, "status": None,
                    "detail": "QA runner result missing, duplicated or incomplete"}]
    logs = _LOG.findall(output)
    try:
        app_log = json.loads(logs[-1]) if logs else output
    except ValueError:
        app_log = output
    passed = not result.timed_out and all(r.get("pass") is True for r in results)
    lines = [f"- {r.get('name')}: {'PASS' if r.get('pass') is True else 'FAIL'} {str(r.get('detail') or '')[:300]}"
             for r in results]
    summary = f"QA checks {'passed' if passed else 'FAILED'}:\n" + "\n".join(lines)
    if not passed:
        summary += f"\nApp output:\n{str(app_log)[-800:]}"
    return WorkPackage("f4", summary, [entry], [], [{"check": "qa", "pass": passed, "results": results}],
                       [] if passed else ["QA checks failed"])


class QAFloor:
    """Floor 4 QA: an independent model turns the spec into HTTP checks; the sandbox runs them."""

    def __init__(self, role: Role, ask: Callable[[Role, str], dict]):
        self._role = role
        self._ask = ask

    def write_checks(self, spec: dict, code: str) -> list[dict]:
        out = self._ask(self._role, QA_PROMPT.format(
            title=spec["title"], goal=spec["goal"], acceptance="\n".join(f"- {a}" for a in spec["acceptance"]),
            code=untrusted("workspace", code)))
        checks = parse_checks(out)
        if not checks:
            raise BadModelOutput("QA wrote no usable checks; resume to retry")
        return checks
