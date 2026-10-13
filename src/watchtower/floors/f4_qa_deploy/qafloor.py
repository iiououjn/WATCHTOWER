from __future__ import annotations

import json
import re
from typing import Callable

from watchtower.floors.framework import WorkPackage, untrusted_code
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

TEXT_NOTE = ("\nYour last checks had no usable expect_text. expect_text must be exact short text the page really "
             "shows (a heading, a button label, an item the test added) — never a description of the page.")

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
# the app's own output is JSON-encoded on one line, so nothing it prints can pose as a result line; it goes first
# and unescaped (escaping grows non-ASCII text 6x) so the sandbox's output tail always keeps the result line
print("WATCHTOWER_LOG " + json.dumps(open(log.name, "rb").read().decode(errors="replace")[-4000:], ensure_ascii=False))
print("WATCHTOWER_QA " + json.dumps(results))
"""
_RESULT = re.compile(r"^WATCHTOWER_QA (.*)$", re.M)
_LOG = re.compile(r"^WATCHTOWER_LOG (.*)$", re.M)
_FRAME = re.compile(r'^\s+File "([^"]+)", line (\d+), in (\S+)')
_EXC_LINE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Warning): ")


def app_error(log: str) -> str:
    """The app's own last error, from its log: the exception line and where it was raised, one short line.
    Run 11: a NameError in do_GET sat at the end of the log, past what the coder is shown."""
    text = str(log or "")
    start = text.rfind("Traceback (most recent call last):")
    if start < 0:  # the header fell off the kept tail: the last exception line alone still helps
        last = [ln for ln in text.splitlines() if _EXC_LINE.match(ln)]
        return f"App error: {last[-1].strip()[:200]}" if last else ""
    lines = text[start:].splitlines()[1:]
    at = next((i for i, ln in enumerate(lines) if ln.strip() and not ln[0].isspace()), None)
    if at is None:
        return ""
    where = ""
    frames = [i for i in range(at) if _FRAME.match(lines[i])]
    if frames:
        path, line_no, fn = _FRAME.match(lines[frames[-1]]).groups()
        source = lines[frames[-1] + 1].strip() if frames[-1] + 1 < at else ""
        where = f" (at {path.rsplit('/', 1)[-1][-60:]} line {line_no[:8]} in {fn[:60]}: {source[:100]})"
    return f"App error: {lines[at].strip()[:200]}{where}"


def _str(value, cap: int) -> str | None:
    return value if isinstance(value, str) and len(value) <= cap else None


_DESCRIBES = re.compile(r"^(the|a|an)\s+(\w+\s+){0,2}(home ?page|page|form|list|field|input|button|table|screen)\b"
                       r"(\s+\S+){2,}|\b(input field|text field|text box|submit button)\b", re.IGNORECASE)
MAX_TEXT_WORDS = 12
_MARKUP = re.compile(r"<[^<>]*>|\\[nrt]")
_ESCAPED = re.compile(r"[<>\\]|&(lt|gt);", re.IGNORECASE)
_ESCAPED_ONLY = re.compile(r"\\[nrt]|&(lt|gt);", re.IGNORECASE)


def _page_text(text: str, known: str = "") -> str:
    """Text a check may expect on the page: literal page text. A description of the page ('The homepage with
    an input field…') can never match real HTML, so it is dropped (status-only check) — unless the app's code,
    title or routes really contain it."""
    if text and text.lower() in known.lower():
        return text
    if _ESCAPED_ONLY.search(text):  # raw tags stay: code-derived '<li>milk</li>' is a strong check of the raw page
        text = _unmarked(text)
    return "" if len(text.split()) > MAX_TEXT_WORDS or _DESCRIBES.search(text) else text


def _unmarked(text: str) -> str:
    """'<li>milk</li>' → 'milk'. Escaped tags ('&lt;ul>') or a written '\\n' can never match the raw page."""
    if not (_MARKUP.search(text) or _ESCAPED.search(text)):
        return text
    return max((p for p in map(str.strip, _MARKUP.split(text)) if not _ESCAPED.search(p)), key=len, default="")


def test_first_text(text: str, shows: set[str]) -> str:
    """Test-first text (no code yet) is kept as written — the coder makes it appear — unless no page can show it:
    escaped markup, more than 12 words, or the architect's own route description copied word for word (run 8).
    The description regex is not applied here: 'The list is empty' is real page text."""
    if _MARKUP.search(text) or _ESCAPED.search(text):  # one real piece of text, or none: never a weaker check
        pieces = [p for p in map(str.strip, _MARKUP.split(text)) if p]
        text = pieces[0] if len(pieces) == 1 and not _ESCAPED.search(pieces[0]) and re.search(r"\w{2,}",
                                                                                            pieces[0]) else ""
    return "" if len(text.split()) > MAX_TEXT_WORDS or " ".join(text.lower().split()) in shows else text


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


def has_page_text(checks: list[dict], title: str = "") -> bool:
    """A suite worth running: at least one check expects real words that are not just the app's title."""
    return any(re.search(r"\w{2,}", c["expect_text"]) and c["expect_text"].strip().lower() != title.strip().lower()
               for c in checks)


def _request(c: dict) -> tuple:
    """Same method, path and form (fields in any order) = the same request."""
    return c["method"], c["path"], tuple(sorted((str(k), str(v)) for k, v in (c.get("form") or {}).items()))


def _same_request_hints(checks: list[dict], results: list[dict]) -> dict[int, str]:
    """Run 13: two checks sent one request (no other POST between them, so nothing changed) and wanted different
    texts; the coder saw one failure at a time and flip-flopped. Name the pair once, on its first failing check,
    right after FAIL (the coder sees only the head of this summary). By position: names may repeat."""
    if [r.get("name") for r in results] != [c["name"] for c in checks]:
        return {}
    hints, paired = {}, set()
    for j, r in enumerate(results):
        if r.get("pass") is True or j in paired:
            continue
        for i, c in enumerate(checks):
            first, between = checks[min(i, j)], checks[min(i, j) + 1:max(i, j)]
            real_add = first["method"] == "POST" and first["form"] and all(first["form"].values())  # may change state
            if (i != j and _request(c) == _request(checks[j]) and c["expect_text"] and not real_add
                    and c["expect_text"] != checks[j]["expect_text"] and c["expect_status"] == checks[j]["expect_status"]
                    and not any(b["method"] == "POST" for b in between)):
                hints[j] = f" [same request as {c['name'][:30]!r}: show both texts]"
                paired |= {i, j}
                break
    return hints


def parse_checks(reply, known: str | None = None) -> list[dict]:
    """Keep only checks that are safe to run: local relative paths, small forms, sane values; names made
    unique. With `known` (checks written from existing code), description-like expected text is dropped
    unless the code really contains it; test-first checks (no code yet) keep their text as written."""
    raw = reply.get("checks") if isinstance(reply, dict) else None
    checks, seen = [c for c in map(_check, raw if isinstance(raw, list) else []) if c][:MAX_CHECKS], {}
    for c in checks:
        if known is not None:
            c["expect_text"] = _page_text(c["expect_text"], known)
        seen[c["name"]] = seen.get(c["name"], 0) + 1
        if seen[c["name"]] > 1:
            c["name"] = f"{c['name']} #{seen[c['name']]}"
    return checks


def run_qa(run: Callable[[list[str]], SandboxResult], entry: str, checks: list[dict]) -> WorkPackage:
    """Floor 4: run the QA checks against the app inside the sandbox. No model involved. Zero checks never pass."""
    if not checks:
        return WorkPackage("f4", "QA checks FAILED:\n- no QA checks to run", [entry], [],
                           [{"check": "qa", "pass": False, "results": []}], ["no QA checks"])
    result = run(["python", "-I", "-c", QA_SCRIPT, entry, json.dumps(checks)])
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
    hints = _same_request_hints(checks, results)
    lines = [f"- {r.get('name')}: {'PASS' if r.get('pass') is True else 'FAIL'}{hints.get(i, '')} "
             f"{str(r.get('detail') or '')[:300]}" for i, r in enumerate(results)]
    error = "" if passed else app_error(str(app_log))  # first: the coder sees only the head of this summary
    summary = f"QA checks {'passed' if passed else 'FAILED'}:\n" + (error + "\n" if error else "") + "\n".join(lines)
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
        prompt = QA_PROMPT.format(
            title=spec["title"], goal=spec["goal"], acceptance="\n".join(f"- {a}" for a in spec["acceptance"]),
            code=untrusted_code("workspace", code))
        known = f"{spec['title']}\n{code}"
        checks = parse_checks(self._ask(self._role, prompt), known)
        if not has_page_text(checks, spec["title"]):  # status-only checks pass almost any app: ask once more
            checks = parse_checks(self._ask(self._role, prompt + TEXT_NOTE), known)
        if not has_page_text(checks, spec["title"]):
            raise BadModelOutput("QA wrote no check of real page text; resume to retry")
        return checks
