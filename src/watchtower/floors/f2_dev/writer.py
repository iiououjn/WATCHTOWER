"""F2 writes the coder's files to the workspace, repairing the small models' usual slips on the way, and tells the
coder what was not written and why (8d: devfloor's `_write`, split by step)."""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Callable

from watchtower.engine.workspace import Workspace, WorkspaceError
from watchtower.floors.f2_dev.feedback import UNCHANGED_NOTE
from watchtower.floors.f2_dev.repair import repair_imports, repair_main, repair_strings, sibling_names
from watchtower.floors.f2_dev.skeleton import STORE, STORE_TESTS

MAX_FILES_PER_ROUND = 3
MayImport = Callable[[str], "frozenset[str] | None"]


def _refusal(f: dict, owned: set[str]) -> tuple[str, bool] | None:
    """(note, counts as a change) for a file the coder may not write; None when it may."""
    given = PurePosixPath(str(f.get("path", "")).strip())
    shown = repr(str(f.get("path"))[:100])
    if {str(given).lower(), given.parts[0].lower() if given.parts else ""} & {o.lower() for o in owned}:
        return (f"{shown} belongs to the tower's web server and was not changed: write {STORE} (add and items) "
                "instead"), False
    if owned and f.get("delete") is not True and str(given) not in (STORE, STORE_TESTS):
        # 7c (run 36): a stray AI-written XSS server shipped beside the tower's
        return f"File rejected: {shown}: write only {STORE} and {STORE_TESTS}", True
    return None


def _delete(ws: Workspace, f: dict) -> bool:
    """Delete one file; True when the workspace changed (a missing file is no change)."""
    before = set(ws.files())
    ws.delete(str(f.get("path", "")))
    return set(ws.files()) != before


def _repair(ws: Workspace, path: str, content: str, entry: str, may_import: MayImport) -> tuple[str, list[str]]:
    """Python files only: joined one-line strings, missing imports, and an entry that never starts its server."""
    if not path.endswith(".py"):
        return content, []
    notes = []
    content, lines = repair_strings(content)
    content, added = repair_imports(content, sibling_names(ws, path), may_import(path))
    started = None
    if str(PurePosixPath(path.strip())) == entry:  # run 10: run() defined, never called, the app exited at once
        content, started = repair_main(content)
    if lines:
        notes.append(f"Auto-repaired {path} line(s) {', '.join(map(str, lines))} of what you sent: a line "
                     "break inside a one-line string was joined as \\n. Keep one-line strings on one line.")
    if added:
        shown = "; ".join(f"`{m if m.startswith('from ') else 'import ' + m}`" for m in added)
        notes.append(f"Auto-repaired: added the missing {shown} to {path}.")
    if started:  # reported after the write: a rejected file was not repaired
        notes.append(f'Auto-repaired: {path} never started its server; added `if __name__ == "__main__": '
                     f'{started}()` at the end.')
    return content, notes


def _write_one(ws: Workspace, f: dict, entry: str, may_import: MayImport) -> tuple[str, bool, list[str]]:
    """Write one file under the name the workspace already uses; (path, unchanged, repair notes)."""
    path, content = str(f.get("path", "")), str(f.get("content", ""))
    path = entry if entry and str(PurePosixPath(path.strip())).lower() == entry.lower() else path
    old = next((p for p in ws.files() if p != path and p.lower() == path.lower()), None)
    path = old if old and path != entry else path  # r1: 'Utils.py' keeps utils.py (import utils)
    content, notes = _repair(ws, path, content, entry, may_import)
    try:
        before = ws.read(old or path)
    except (WorkspaceError, OSError):
        before = None
    if old:  # 8c (C-M3): a case-preserving disk kept 'App.py' for every later write of app.py
        ws.write(old, content)  # r1: a rejected write (over 100 KB) leaves App.py alone
        ws.delete(old)
    ws.write(path, content)
    return path, before == content.replace("\r\n", "\n").replace("\r", "\n"), notes  # read() gives \n only


def write_files(ws: Workspace, files, entry: str, owned: set[str], may_import: MayImport) -> list[str]:
    """Write up to MAX_FILES_PER_ROUND files (deletes are free); notes for the coder on everything not written."""
    notes, same, changed, written = [], [], False, 0
    for f in (files if isinstance(files, list) else [])[:MAX_FILES_PER_ROUND + 5]:
        if not isinstance(f, dict):
            continue
        refusal = _refusal(f, owned)
        if refusal is not None:
            notes.append(refusal[0])
            changed = changed or refusal[1]
            continue
        delete = f.get("delete") is True
        if not delete:
            if written >= MAX_FILES_PER_ROUND:  # deletes don't use up the cap; writes beyond it are dropped
                changed = True  # it sent more than was written: never tell it "unchanged"
                notes.append(f"File {str(f.get('path'))[:100]!r} not written: at most {MAX_FILES_PER_ROUND} "
                             "files per reply")
                continue
            written += 1
        try:
            if delete:
                changed = _delete(ws, f) or changed
            elif not isinstance(f.get("content"), str):
                notes.append(f"File rejected: {str(f.get('path'))[:100]!r} has no content")
            else:
                path, unchanged, repaired = _write_one(ws, f, entry, may_import)
                if unchanged:
                    same.append(path)
                else:
                    changed = True
                notes += repaired
        except WorkspaceError as e:
            notes.append(f"File rejected: {e}")
    if same and not changed:  # run 8: the 7B copied the files it was shown, 16 rounds in a row
        notes.append(UNCHANGED_NOTE.format(names=", ".join(same)[:200]))
    return notes
