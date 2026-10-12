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
def fetch(path, data=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data), timeout=3) as r:
            return r.read(200000).decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.read(200000).decode(errors="replace")
    except Exception:
        return ""
pages = {}
for post in plan["posts"]:
    form = urllib.parse.urlencode({f: post["marker"] for f in post["fields"]}).encode()
    pages["POST " + post["path"]] = fetch(post["path"], form)
for path in plan["gets"]:
    pages["GET " + path] = fetch(path)
hits = [{"post": post["path"], "fields": post["fields"], "page": page}
        for post in plan["posts"] for page, body in pages.items() if post["marker"] in body]
try:
    os.killpg(p.pid, 9)
except Exception:
    p.kill()
log.close()
print("WATCHTOWER_XSS " + json.dumps(hits))
"""
_RESULT = re.compile(r"^WATCHTOWER_XSS (.*)$", re.M)
_PATH = re.compile(r"/[A-Za-z0-9._~/-]{0,80}")
MAX_POSTS, MAX_GETS = 8, 8


def _safe(path) -> bool:
    return isinstance(path, str) and bool(_PATH.fullmatch(path)) and "//" not in path and ".." not in path


def _finding(severity: str, entry: str, text: str) -> dict:
    return {"tool": "probe", "id": "XSS" if severity == "HIGH" else "XSS-PROBE", "severity": severity,
            "confidence": "HIGH", "file": entry, "line": 0, "text": text}


def xss_probe(run: Callable[[list[str]], SandboxResult], entry: str, routes: list[dict]) -> list[dict]:
    """Floor 5 worker: HTML injection through the app's own forms. A raw marker on any page = HIGH finding.
    No form routes → nothing to probe. A missing or doubled result line → UNKNOWN (scan incomplete), never a pass."""
    posts = [r for r in routes if r.get("method") == "POST" and r.get("fields") and _safe(r.get("path"))][:MAX_POSTS]
    if not posts:
        return []
    gets = list(dict.fromkeys(["/"] + [r["path"] for r in routes
                                       if r.get("method") == "GET" and _safe(r.get("path"))]))[:MAX_GETS]
    plan = {"posts": [{"path": r["path"], "fields": list(r["fields"]), "marker": f"<i>wtprobe{n}x</i>"}
                      for n, r in enumerate(posts)], "gets": gets}
    result = run(["python", "-c", XSS_SCRIPT, entry, json.dumps(plan)])
    found = _RESULT.findall((result.stdout or "") + (result.stderr or ""))
    try:
        hits = json.loads(found[0]) if len(found) == 1 and not result.timed_out else None
    except ValueError:
        hits = None
    if not isinstance(hits, list) or not all(isinstance(h, dict) for h in hits):
        return [_finding("UNKNOWN", entry, "HTML injection probe did not complete")]
    by_post: dict[str, tuple[list[str], list[str]]] = {}
    for h in hits:  # one finding per form route, naming every page that showed the raw tag
        fields, pages = by_post.setdefault(str(h.get("post"))[:90], ([str(f) for f in (h.get("fields") or [])], []))
        if str(h.get("page")) not in pages:
            pages.append(str(h.get("page"))[:90])
    return [_finding("HIGH", entry, f"POST {post} ({', '.join(fields)[:80]}) → raw HTML shown on "
                                    f"{'; '.join(pages[:3])}; escape user text with html.escape before writing "
                                    "it into HTML") for post, (fields, pages) in list(by_post.items())[:5]]
