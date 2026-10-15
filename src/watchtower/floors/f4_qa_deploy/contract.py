"""Phase 6u: the F4 checks that decide come from the architect's routes contract, not a model (runs 18-21).

For each POST route that adds something, the tower posts one value per field and expects the list page to
show each value. The values carry a space, so an app that splits the form body by hand instead of decoding
it (runs 19-20) fails, and F4's URL-encoded hint names the fix."""
import re

from watchtower.floors.f4_qa_deploy.qafloor import parse_checks

MAX_ADD_ROUTES = 2
_DESTRUCTIVE = re.compile(r"delete|remove|clear|done|toggle|edit|update|complete", re.IGNORECASE)
_ID_FIELD = re.compile(r"^(id|index|\w+_id)$", re.IGNORECASE)


def _adds(route: dict) -> bool:
    return (route["method"] == "POST" and bool(route["fields"]) and not _DESTRUCTIVE.search(route["path"])
            and not any(_ID_FIELD.match(f) for f in route["fields"]))


def contract_checks(routes: list[dict], token: str) -> list[dict]:
    """Add-then-list checks for up to two adding POST routes; [] when the contract has none (models decide)."""
    pages = [r["path"] for r in routes if r["method"] == "GET" and not r["fields"]]
    page = pages[0] if pages else "/"
    raw = []
    for route in [r for r in routes if _adds(r)][:MAX_ADD_ROUTES]:
        form = {f: f"{f} {token}" for f in route["fields"]}
        raw.append({"name": f"[tower] POST {route['path']} adds", "method": "POST", "path": route["path"],
                    "form": form, "expect_status": 200, "expect_text": ""})
        raw += [{"name": f"[tower] GET {page} shows {f} from {route['path']}", "method": "GET", "path": page,
                 "form": {}, "expect_status": 200, "expect_text": value} for f, value in form.items()]
    return parse_checks({"checks": raw})
