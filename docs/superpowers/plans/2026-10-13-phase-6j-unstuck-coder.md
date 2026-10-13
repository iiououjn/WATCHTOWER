# Phase 6j — Unstick the coder (missing imports, unchanged replies), F4 test-first text

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 8 (job 38c73d86d399, 2026-10-13) proved the file-block format: no escaping damage. It failed at F2
for 16 rounds on one line: `test_todo.py` used `os` without `import os`. The coder was told the exact error, the line,
and F2 HR's diagnosis ("import os"), and still sent the file back unchanged every round. Its test-first F4 checks also
expected route descriptions ("No direct response, but the page should update…") and escaped markup (`&lt;ul>`), which
no real page can show, so F4 would have blocked next.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F2 coder loop, F4 QA).

## Global Constraints
- $0 local; 8 GB. Deterministic fixes; no new model calls.
- AI-written code is never run on the host: repairs are static (ast/tokenize only).
- Files < 500 lines (`devfloor.py` is 594: the repair code moves to `floors/f2_dev/repair.py`).
- Tests first; two review rounds; no Co-Authored-By trailer.

## Critique of the first idea, and the counters
1. **"More rounds / louder notes"** — run 8 already had the exact error and an HR diagnosis; the 7B copied the snapshot.
   Counter: fix the commonest slip by code (a missing standard import), and tell the coder plainly when its reply
   changed nothing.
2. **Auto-import any unbound name that matches a stdlib module** — names like `code`, `string`, `token`, `types` are
   often ordinary variables; importing them turns a clear NameError into a confusing AttributeError. Counter: a short
   allow-list of modules apps really use, only for `name.attr` uses, only when the name is bound nowhere in the file.
3. **Unchanged detection by hash of the whole workspace** — a reply may legitimately leave some files as they are.
   Counter: note only when every file the reply wrote is byte-identical to what was there (and nothing was deleted).
4. **Drop test-first check text** — 6g ruled test-first text is kept as written ("nothing weakens a check"). A
   description or escaped markup can never appear on a real page, so keeping it does not make F4 stronger, only
   unpassable. Counter: apply the same rule the fallback checks already use (descriptions, >12 words, markup or
   escapes dropped), with only the spec title as known text. If no real text check is left, QARound already falls
   back to checks written from the code (6g), so F4 never gets weaker than main.

## Rulings
1. Import allow-list: os, sys, json, re, time, datetime, html, sqlite3, random, math, tempfile, shutil, uuid,
   unittest, io, string excluded; dotted: urllib.{parse,request,error}, http.{server,client,cookies}.
2. Markup in expected text = `<`, `>`, a backslash, or an HTML entity (`&lt;` …), unless the known text contains it.

## Review Focus
1. Import repair: names bound by function args, comprehensions, `with … as`, `except … as`, `global`, `del`, star
   imports (`from os import *` → never touch), a file that does not parse, a `__future__` import or docstring first.
2. Unchanged note: deletes, rejected files, a reply that only adds a new file, the test-first round.
3. F4 text rule: literal short page text kept; text the code really contains kept; fallback path unchanged.

### Task 1: repair.py — move string repair, add import repair
`floors/f2_dev/repair.py`: `repair_strings` (moved), `repair_imports(source) -> (text, [module])`. `devfloor._write`
runs both on .py files and names the added imports in a note. `devfloor` re-exports `repair_strings`.

### Task 2: Unchanged-reply note
`devfloor._write` reports files written byte-identical; when every written file is unchanged and nothing deleted, the
coder gets `UNCHANGED_NOTE` naming them.

### Task 3: F4 test-first text
`qafloor._page_text` drops markup/escapes; `QAOffice.plan_checks` parses worker checks with `known=spec title`.

### Task 4: two review rounds; real run 9.
