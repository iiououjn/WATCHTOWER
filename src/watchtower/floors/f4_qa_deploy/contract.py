"""Phase 6u: the F4 checks that decide come from the architect's routes contract, not a model (runs 18-21).

Only for an unambiguous add-and-list contract: a GET page that lists entries, and a POST route that adds one
whose fields are all plain text (item, name, message...). The tower posts a value per field and expects the
list page to show it. Anything else (typed or choice fields, no list page, a calculator posting to /) leaves
the decision to the model checks, exactly as before. Values are digits with a space: they survive .title(),
and an app that splits the form body by hand (runs 19-20) shows '1234560+123456' and fails with a hint."""
import re
import secrets

from watchtower.floors.f4_qa_deploy.qafloor import parse_checks

QA_ADVISORY = ("small-model QA checks failed (advisory) but the tower's contract checks passed: "
               "judge the app on the contract checks and the spec")


def gate_qa_note(qa: dict) -> tuple[str, ...]:
    """What the gate hears about advisory QA failures on a passing F4 (7b review r1 I1): with tower checks,
    QA_ADVISORY; without, that model checks were judged by status only (the page text is unverified)."""
    if not (qa.get("pass") and qa.get("advisory_failed")):
        return ()
    if qa.get("decide"):
        return (QA_ADVISORY,)
    return (f"{qa['advisory_failed']} model QA check(s) judged by status only: the page text did not match the "
            "small model's expected text, which may itself be wrong: do not send the app back for them alone",)


_ADDS = re.compile(r"add|new|create|submit|post|save|entr|message|item|comment|note|todo|guest", re.I)
_DESTRUCTIVE = re.compile(r"delete|remove|clear|done|toggle|edit|update|complete|sign|log", re.I)
_TEXT = {"item", "task", "todo", "title", "name", "text", "message", "body", "content", "note", "comment",
         "description", "entry", "author", "subject", "details", "summary", "label", "post", "idea", "quote"}
_LIST = re.compile(r"\b(list|all|entries|items|messages|todos|tasks|posts|comments|notes|ideas|quotes)\b", re.I)
_FORM = re.compile(r"\bform\b", re.I)


def coder_token(job_id: str) -> str:
    """The token in the checks the coder is shown; F4 runs with fresh_token(), which the coder never sees."""
    return f"{int(job_id[:6], 16) % 1_000_000:06d}" if re.fullmatch(r"[0-9a-f]{6}.*", job_id) else "000000"


def fresh_token() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


_MODIFIERS = {"new", "my", "your", "user", "guest", "first", "last", "full", "short", "long", "main", "the"}


def _plain_text(field: str) -> bool:
    """'new_item', 'user_name', 'messageText' are text; 'item_count', 'item_cost', 'dueDate', 'todo_id' are not:
    every name part must be a text word or a harmless modifier (6w, run 24; review r1)."""
    parts = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", field).lower().split("_")
    return any(p in _TEXT for p in parts) and all(p in _TEXT or p in _MODIFIERS for p in parts)


def _adds(route: dict) -> bool:
    return (route["method"] == "POST" and bool(route["fields"]) and bool(_ADDS.search(route["path"]))
            and not _DESTRUCTIVE.search(route["path"]) and all(_plain_text(f) for f in route["fields"]))


def contract_checks(routes: list[dict], token: str) -> tuple[list[dict], int]:
    """(checks, decide): for the first plain-text adding route, the list page's form (6w), the POST and the
    first shown value decide; the other fields' checks are advisory. ([], 0) when the contract is not that simple."""
    pages = [r for r in routes if r["method"] == "GET" and not r["fields"] and _LIST.search(r["shows"])]
    pages = [r for r in pages if not _FORM.search(r["shows"])] or pages
    route = next((r for r in routes if _adds(r)), None)
    if not pages or route is None:
        return [], 0
    page = pages[0]["path"]
    gets = [r for r in routes if r["method"] == "GET" and r["path"] != page]
    same = [r for r in gets if r["path"] == route["path"]]  # GET /add shows the add form
    adding = [r for r in gets if _ADDS.search(r["path"]) and not _DESTRUCTIVE.search(r["path"] + " " + r["shows"])]
    form_page = (same or adding or [{"path": page}])[0]["path"]  # 6w reviews: the add form's page, else the list
    values = {f: f"{token}{i} <&> {token}" for i, f in enumerate(route["fields"])}  # 6z: shown escaped once
    raw = [{"name": f"[tower] GET {form_page} has the add form"[:80], "method": "GET", "path": form_page, "form": {},
            "expect_status": 200, "expect_text": "",
            "expect_form": {"action": route["path"], "fields": route["fields"]}}]
    raw += [{"name": f"[tower] POST {route['path']} adds"[:80], "method": "POST", "path": route["path"],
            "form": values, "expect_status": 200, "expect_text": ""}]
    raw += [{"name": f"[tower] GET {page} shows {f}"[:80], "method": "GET", "path": page, "form": {},
             "expect_status": 200, "expect_text": v} for f, v in values.items()]
    checks = parse_checks({"checks": raw})
    for c in checks[2:]:  # tower-only flag: parse_checks never takes it from a model's JSON (6z review r1)
        c["expect_escaped"] = True
    return checks, 3
