from __future__ import annotations

import json
import re
from typing import Callable

from watchtower.engine.sandbox import SandboxResult

# Runs INSIDE the sandbox. argv: entry, plan-JSON {"posts": [{"path", "fields", "marker"}], "gets": [path]}.
# F5's HTML-injection worker, by code: post a harmless tag into every form field, then read every page. A page
# that returns the tag raw (not escaped) would run attacker HTML in a browser. The app's own output goes to a log
# file, so it cannot print a result line.
XSS_SCRIPT = """\
import json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
port = os.environ.get("WT_PORT", "8000")
base = "http://127.0.0.1:" + port
plan = json.loads(sys.argv[2])
log = open("/tmp/xss.log", "wb")
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
deadline = time.time() + 50  # leave room inside the 90 s sandbox limit: partial evidence beats none
slow = []
def filler(field):
    f = field.lower()
    return ("a@b.co" if "mail" in f else "2026-01-01" if "date" in f else "http://example.com" if "url" in f
            or "link" in f else "1")
def fetch(path, data=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data), timeout=3) as r:
            return r.read(200000).decode(errors="replace"), r.headers.get("Content-Type") or "", True
    except urllib.error.HTTPError as e:
        return e.read(200000).decode(errors="replace"), e.headers.get("Content-Type") or "", True
    except Exception as e:  # only a timeout is "did not answer"; a crash on odd input is not this probe's call
        if isinstance(e, TimeoutError) or "timed out" in str(e):
            slow.append(("POST " if data else "GET ") + path)
        return "", "", False
pages, answered = {}, 0
def keep(name, got):
    global answered
    body, ctype, ok = got
    answered += ok
    if ok and (not ctype or "html" in ctype.lower()):  # JSON or plain text is not rendered as HTML
        pages[name] = body.lower()
for post in plan["posts"]:  # one field at a time: a validated field must not hide a raw text field
    for field, marker in post["markers"].items():
        if time.time() > deadline:
            break
        form = urllib.parse.urlencode({f: (marker if f == field else filler(f)) for f in post["markers"]}).encode()
        keep("POST " + post["path"] + " " + field, fetch(post["path"], form))
for path in plan["gets"]:
    if time.time() > deadline:
        break
    keep("GET " + path, fetch(path))
hits = [{"post": post["path"], "field": field, "page": page.rsplit(" ", 1)[0] if page.startswith("POST") else page}
        for post in plan["posts"] for field, marker in post["markers"].items()
        for page, body in pages.items() if marker.lower() in body]
try:
    os.killpg(p.pid, 9)
except Exception:
    p.kill()
log.close()
print("WATCHTOWER_XSS " + json.dumps({"answered": answered, "hits": hits, "slow": sorted(set(slow))[:5],
                                      "partial": time.time() > deadline}))
"""
_RESULT = re.compile(r"^WATCHTOWER_XSS (.*)$", re.M)
_PATH = re.compile(r"/[A-Za-z0-9._~/-]{0,80}")
MAX_POSTS, MAX_GETS = 8, 8


def _safe(path) -> bool:
    return isinstance(path, str) and bool(_PATH.fullmatch(path)) and "//" not in path and ".." not in path


def _finding(severity: str, entry: str, text: str) -> dict:
    return {"tool": "probe", "id": "XSS" if severity == "HIGH" else "XSS-PROBE", "severity": severity,
            "confidence": "HIGH", "file": "(running app)", "line": 0, "text": text}


def xss_probe(run: Callable[[list[str]], SandboxResult], entry: str, routes: list[dict]) -> list[dict]:
    """Floor 5 worker: HTML injection through the app's own forms. A raw marker on any page = HIGH finding.
    No form routes → nothing to probe. A missing, doubled or empty result (no page answered) → MEDIUM: an
    incomplete probe fails the build (default fail_on), it never passes as clean."""
    posts = [r for r in routes if r.get("method") == "POST" and r.get("fields") and _safe(r.get("path"))][:MAX_POSTS]
    if not posts:
        return []
    gets = list(dict.fromkeys(["/"] + [r["path"] for r in routes
                                       if r.get("method") == "GET" and _safe(r.get("path"))]))[:MAX_GETS]
    plan = {"posts": [{"path": r["path"], "markers": {f: f"<i>wtprobe{n}x{k}</i>" for k, f in enumerate(r["fields"])}}
                      for n, r in enumerate(posts)], "gets": gets}
    result = run(["python", "-I", "-c", XSS_SCRIPT, entry, json.dumps(plan)])  # -I: app files can't shadow json
    found = _RESULT.findall((result.stdout or "") + (result.stderr or ""))
    try:
        out = json.loads(found[0]) if len(found) == 1 and not result.timed_out else None
    except ValueError:
        out = None
    hits = out.get("hits") if isinstance(out, dict) else None
    if (not isinstance(hits, list) or not all(isinstance(h, dict) for h in hits)
            or not isinstance(out.get("answered"), int) or out["answered"] < 1):
        return [_finding("MEDIUM", entry, "HTML injection probe could not complete: the app did not answer its "
                                          "form and pages; make every route answer")]
    by_post: dict[str, tuple[list[str], list[str]]] = {}
    for h in hits:  # one finding per form route, naming the fields and pages that showed the raw tag
        fields, pages = by_post.setdefault(str(h.get("post"))[:60], ([], []))
        for value, bucket in ((str(h.get("field"))[:30], fields), (str(h.get("page"))[:60], pages)):
            if value not in bucket:
                bucket.append(value)
    findings = [_finding("HIGH", entry, f"use html.escape on user text: POST {post} ({', '.join(fields)[:50]}) shows "
                                        f"raw HTML on {'; '.join(pages[:2])}") for post, (fields, pages) in
                list(by_post.items())[:5]]
    slow = [str(x)[:70] for x in (out.get("slow") or []) if isinstance(x, str)]
    if slow or out.get("partial") is True:  # a route that hangs was not probed: say which, keep what was found
        findings.append(_finding("MEDIUM", entry, f"{'; '.join(slow[:3]) or 'some routes'} did not answer within 3 s, "
                                                  "so they could not be checked for HTML injection; make them answer"))
    return findings
