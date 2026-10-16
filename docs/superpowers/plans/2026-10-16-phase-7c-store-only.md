# Phase 7c: a skeleton coder writes only store.py and test_store.py

**Goal:** nothing AI-written but the store and its tests ships in a tower-served app.

**Evidence:** run 36 (job 80389f5bdd6d, PENDING-SIGNOFF). All tower checks passed and 7b's escaping worked, but
the coder also wrote `app.py`: a second, unused HTTP server rendering `f'<li>{item}</li>'` raw (XSS). It
shipped beside the tower's `todo.py`. `DevFloor._write` only refused the tower's own paths.

## Change

Under the skeleton (`self.owned`), `_write` rejects any write whose normalised path is not `store.py` or
`test_store.py` (case-blind): "File rejected: 'x': write only store.py and test_store.py". Deletes stay allowed
(the tower's own files remain protected by the older rule). Non-skeleton apps are unchanged.
STORE_NOTE moved to skeleton.py (devfloor.py stays under 500 lines).

## Critique, counters, rulings

- *Denylist servers (`http.server`, `socket`) instead.* Evadable. Ruling: allowlist.
- *Allow any `test*.py`.* A server could ship as `test_server.py`. Ruling: exact names; cost: a coder writing
  `tests/test_store.py` is told to use `test_store.py`.
- *Allow helper modules store.py imports.* No run needed one; the store is ~10 lines. Ruling: reject, the note
  says where to write. Cost if wrong: one wasted round.
- *Stray files already on disk* (written before the skeleton applied): out of scope; run 36's came from the
  build loop. Cost if wrong: a stray from an earlier plan ships (the owner reads the file list).

## Review Focus

1. Path tricks: `./store.py`, `STORE.PY`, `store.py/`, `sub/../store.py`, absolute paths, backslashes.
2. A reply where every file is rejected must not read as "unchanged" in a way that stalls the loop wrongly.
3. write_units (first round) and build (fix rounds) both go through `_write`.
4. Deletes of tower-owned files still refused.
5. Non-skeleton jobs: no change.

## Tasks

- [x] RED: tests/test_skeleton.py — only store.py/test_store.py written; stray delete allowed; no-skeleton path
      unchanged. GREEN: devfloor._write allowlist.
- [ ] 3 opus review rounds (security), merge `--no-ff`, tag `phase-7c`, runs 37-39 (+ a fresh todo for 36).
