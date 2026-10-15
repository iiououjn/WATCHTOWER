"""Phase 6u: the F4 checks that decide come from the architect's routes contract, not a model (runs 18-21).

For the first POST route that adds something, the tower posts one value per field and expects the list page
to show the first text field's value. Text values carry a space, so an app that splits the form body by hand
instead of decoding it (runs 19-20) fails, and F4's URL-encoded hint names the fix. Typed fields (numbers,
dates, emails, check boxes) get plausible values and never decide; other text fields' checks are advisory."""
import re

from watchtower.floors.f4_qa_deploy.qafloor import parse_checks

QA_ADVISORY = ("small-model QA checks failed (advisory) but the tower's contract checks passed: "
               "judge the app on the contract checks and the spec")
_ADDS = re.compile(r"add|new|create|submit|post|save|sign|entr|message|item|comment|note|todo|guest", re.I)
_DESTRUCTIVE = re.compile(r"delete|remove|clear|done|toggle|edit|update|complete", re.I)
_SKIP_FIELD = re.compile(r"^(id|index|\w+_id|pass(word)?|q|query|search|token|csrf\w*)$", re.I)
_WORD = r"(?:^|_)(?:{})(?:$|_)"  # whole name parts: 'age' must not match 'message' (6u review)
_TYPED = [(re.compile(_WORD.format("amount|price|qty|quantity|count|age|number|num|total|cost|score|rating|year"),
                      re.I), "3"),
          (re.compile(_WORD.format("date|due|deadline|day"), re.I), "2026-01-02"),
          (re.compile(_WORD.format("e-?mail"), re.I), "{token}@example.com"),
          (re.compile(r"^(done|completed?|checked|agree|urgent|flag|is_\w+)$", re.I), "on")]
_LIST = re.compile(r"\b(list|all|entries|items|messages|todos|posts|comments|notes)\b", re.I)


def _value(field: str, token: str) -> tuple[str, bool]:
    """The value to post and whether it is text the list page should show."""
    for pattern, value in _TYPED:
        if pattern.search(field):
            return value.format(token=token), False
    return f"{field} {token}", True


def _adds(route: dict, page: str) -> bool:
    return (route["method"] == "POST" and bool(route["fields"]) and not _DESTRUCTIVE.search(route["path"])
            and (bool(_ADDS.search(route["path"])) or route["path"] == page)
            and not any(_SKIP_FIELD.match(f) for f in route["fields"]))


def contract_checks(routes: list[dict], token: str) -> tuple[list[dict], int]:
    """(checks, decide): add-then-list checks for the first adding POST route; the first `decide` of them decide
    (the POST and one shown text value). ([], 0) when the contract has no such route: the models decide."""
    pages = [r for r in routes if r["method"] == "GET" and not r["fields"]]
    listing = [r for r in pages if _LIST.search(r["shows"])]
    page = (listing or [r for r in pages if r["path"] == "/"] or pages or [{"path": "/"}])[0]["path"]
    route = next((r for r in routes if _adds(r, page)), None)
    if route is None:
        return [], 0
    values = {f: _value(f, token) for f in route["fields"]}
    shown = [(f, v) for f, (v, text) in values.items() if text]
    if not shown:
        return [], 0
    raw = [{"name": f"[tower] POST {route['path']} adds"[:80], "method": "POST", "path": route["path"],
            "form": {f: v for f, (v, _) in values.items()}, "expect_status": 200, "expect_text": ""}]
    raw += [{"name": f"[tower] GET {page} shows {f}"[:80], "method": "GET", "path": page, "form": {},
             "expect_status": 200, "expect_text": v} for f, v in shown]
    return parse_checks({"checks": raw}), 2
