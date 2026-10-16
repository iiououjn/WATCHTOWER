"""The architect's plan, cleaned by code: safe paths, one importable entry, and the units F2 workers write
(8d: moved out of devfloor.py)."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from watchtower.engine.workspace import ALLOWED_SUFFIXES
from watchtower.floors.f2_dev.app_tests import is_test_file
from watchtower.floors.f4_qa_deploy.qafloor import parse_routes

_SAFE_ENTRY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*\.py")  # importable by tests
_UNSAFE = re.compile(r"[<>{}\x00-\x1f\x7f]")
MAX_PLANNED_FILES = 15
MAX_UNITS = 4
UNIT_FILES = 3
ENTRY_PURPOSE = "the app's entry point: starts the HTTP server"
PLAN_PROMPT = (
    "Spec:\n{spec}\n\nResearch notes:\n{research}\n{reference}{lessons}{feedback}\n"
    "Plan the files and the app's routes (the contract QA will test). Reply as JSON: "
    '{{"files": [{{"path": string, "purpose": string}}], "entry": string, '
    '"routes": [{{"method": "GET" or "POST", "path": string, "fields": [form field names], "shows": string}}]}}'
)


def plan_path(raw) -> str | None:
    """A planned path as the workspace will name it ('./a.py' → 'a.py'), or None if it could never be written."""
    text = str(raw or "").strip()
    if not 0 < len(text) <= 100 or "\\" in text or any(ord(c) < 32 or c == "\x7f" for c in text):
        return None
    rel = PurePosixPath(text)
    if rel.is_absolute() or ".." in rel.parts or any(p.startswith(".") for p in rel.parts):
        return None
    return rel.as_posix() if rel.suffix in ALLOWED_SUFFIXES else None


def _safe_entry(entry: str, files: list[dict]) -> tuple[str, list[dict]]:
    """An entry tests can import: '2048.py' → 'app_2048.py', else app.py (8c, C-M7: the old name must not stay
    planned as a second server)."""
    if _SAFE_ENTRY.fullmatch(entry):
        return entry, files
    fixed = re.sub(r"(^|/)(?=\d)", r"\1app_", entry)
    if _SAFE_ENTRY.fullmatch(fixed):
        return fixed, [{**f, "path": fixed} if f["path"] == entry else f for f in files]
    return "app.py", [f for f in files if f["path"] != entry]


def parse_plan(out: dict) -> dict:
    """The architect's JSON as a plan: up to 15 unique files (case-blind), an importable entry that is planned, and
    the routes contract."""
    files, seen = [], set()
    for f in out.get("files") or []:
        path = plan_path(f.get("path")) if isinstance(f, dict) else None
        if path is not None and path.lower() not in seen:  # one name per file, even on case-blind disks
            seen.add(path.lower())
            files.append({"path": path, "purpose": _UNSAFE.sub("", str(f.get("purpose", ""))).strip()[:80]})
    entry, files = _safe_entry(plan_path(out.get("entry")) or "app.py", files)
    files = files[:MAX_PLANNED_FILES]
    files = [f for f in files if f["path"] == entry or f["path"].lower() != entry.lower()]
    if entry not in {f["path"] for f in files}:  # a 3B architect often names an entry it never plans
        files = files[:MAX_PLANNED_FILES - 1] + [{"path": entry, "purpose": ENTRY_PURPOSE}]
    return {"files": files, "entry": entry, "routes": parse_routes(out.get("routes"))}


def units(plan: dict, owned=frozenset()) -> list[list[dict]]:
    """F2 Lead's split, by code: unit 1 is the MVP (entry + test files), then the other planned files in
    groups of up to 3, in plan order; at most 4 units (the fix loop writes anything left over). Under the
    skeleton (8c, run 38) the store comes before its tests: a store written after them copied their names."""
    files = list({f["path"]: f for f in plan["files"]}.values())
    if owned:
        mine = [f for f in files if f["path"] != plan["entry"]]
        split = [[f for f in files if f["path"] == plan["entry"]], [f for f in mine if not is_test_file(f["path"])],
                 [f for f in mine if is_test_file(f["path"])]]
        return [u[:UNIT_FILES] for u in split if u][:MAX_UNITS]
    first = [f for f in files if f["path"] == plan["entry"]]
    first += [f for f in files if PurePosixPath(f["path"]).name.startswith("test")][:UNIT_FILES - len(first)]
    rest = [f for f in files if f not in first]
    split = [first] if first else []
    split += [rest[i:i + UNIT_FILES] for i in range(0, len(rest), UNIT_FILES)]
    return split[:MAX_UNITS]
