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

## Review round 1 (fixed)

- I1 server moved into store.py: `store_problems` blocks store.py/test_store.py importing http, socket,
  socketserver, wsgiref, subprocess, multiprocessing, asyncio, ssl (also via import_module/__import__).
- I2 an earlier plan's AI files: `apply()` deletes every file but the entry, store.py, test_store.py
  (reverses the out-of-scope ruling: cheap, and they shipped).
- I3 the coder hears "Write only store.py and test_store.py" up front (ONLY_NOTE, outside untrusted).
- M4 exact names only (`Store.py` rejected). M5 a rejected file counts as a change (no UNCHANGED_NOTE).
- Not fixed (pre-existing): `_link_entry` may rewrite the tower's entry.

## Review round 2 (fixed)

- I1 the store check was a denylist (evaded by xmlrpc.server, os.system, exec, string-built imports,
  `__main__.show = str`). Now an import allowlist (json, copy, threading, collections, dataclasses, typing,
  datetime, time, uuid, itertools, functools, re, html, __future__; tests add unittest, store, importlib),
  banned calls (exec, eval, compile, open, __import__, import_module, breakpoint, input), no dunder names
  except `__name__`/`__init__`, no relative imports. Cost if wrong: a legit store using another module loses a
  round; the problem says why.
- M2 apply() deletes are guarded (a refused file never stops the job). M3 ONLY_NOTE precedence. M4 store
  problems listed first. M5 a plain store and its reload-style tests pass (false-positive guard).

## Review round 3 (fixed) and the boundary ruling

- C1 allowed modules re-export dangerous ones (`from uuid import os`, `typing.sys.modules`, `threading._os`):
  ImportFrom names and attributes in DANGER, any `_private` name, and `import *` are flagged.
- C2 banned builtins aliased (`e = exec`, `[eval][0]`, `getattr(..., '__subcl'+'asses__')`): BANNED names are
  flagged when referenced at all; getattr/setattr/delattr/globals/vars/locals added.
- I4 test_store.py may use sys, os and `__file__` (it runs in Docker; reload/sys.path idioms cost rounds).
- **Ruling:** `store_problems` is an accident guard against a 7B's mistakes, not a sandbox — static checks
  cannot contain hostile Python. The boundary stays: checks run in Docker, `watchtower deploy` runs isolated,
  and the release note tells the owner to read store.py before running it on the Mac. Cost if wrong: a
  deliberately obfuscated store.py passes the guard and is caught only by the owner's read.

## Review Focus

1. Path tricks: `./store.py`, `STORE.PY`, `store.py/`, `sub/../store.py`, absolute paths, backslashes.
2. A reply where every file is rejected must not read as "unchanged" in a way that stalls the loop wrongly.
3. write_units (first round) and build (fix rounds) both go through `_write`.
4. Deletes of tower-owned files still refused.
5. Non-skeleton jobs: no change.

## Tasks

- [x] RED: tests/test_skeleton.py — only store.py/test_store.py written; stray delete allowed; no-skeleton path
      unchanged. GREEN: devfloor._write allowlist.
- [x] 3 opus review rounds (security), merge `--no-ff`, tag `phase-7c`, runs 37-39 (+ a fresh todo for 36).
