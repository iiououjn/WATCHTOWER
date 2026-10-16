# Phase 8c: skeleton and store correctness (audit batch 3)

**Goal:** under the skeleton, the tower never tells the coder to write code its own checks then reject, and the
checks that guard store.py are real (each one has a test that fails when the guard is removed). Plus the
F2 correctness items of the 2026-10-16 audit that are not security or reliability.

**Evidence:** audit 2026-10-16 (`docs/superpowers/audit/2026-10-16/`): C-H1, C-H2, E-T1, C-M1, C-M3, C-M4,
C-M5, C-M6, C-M7, A-F6. Run 38's board shows the order bug directly: "coder unit 1/2 written: test_store.py",
then "unit 2/2 written: store.py"; store.py copied the tests' `get_items`.

**Failure classes (loop check):** store contract 38 (7d checks it after the fact); this batch removes the cause
(order, hints) instead of adding a third prompt. The tower contradicting itself (C-H2) is the loop pattern
inside the tower: each fix is a code change to the hint or the check, never a new prompt sentence.

## Diagnosis

1. **Order (C-H1).** `units()` puts the entry and the test files first. Under the skeleton the entry already
   exists, so unit 1 is test_store.py alone; the store writer then reads the tests and copies their names.
2. **Contradicting hints (C-H2).** "e.g. from app import ..." (app.py is the tower's server: rejected);
   idiom_notes' "`store._entries.clear()`" (test_store.py may not use `._x`: rejected); `repair_imports` adds
   `import os` / `tempfile` / `from html import escape` to store.py (rejected or forbidden by STORE_NOTE);
   "add test_*.py" (only test_store.py is accepted).
3. **Vacuous tests (E-T1).** Every EVASIONS/ALIASES snippet lacks `def add`/`def items`, so 7d's contract
   check flags each one whatever `_scan` decides: unbanning getattr, allowing os or dunders survives the suite.
4. **False positives (C-M1).** `re.compile` (attribute `compile`), `__all__`, `store._items` in tests are
   rejected; the message "test_store.py … only keeps data in memory" is wrong for a test and gives no fix.
5. **3.13 removals (C-M4).** The stdlib check uses the tower's `sys.stdlib_module_names` (3.12 or 3.13,
   whatever uv picked); the sandbox runs 3.14. `cgi` passes F2 on 3.12 and crashes in F3.
6. **Budgets (C-M5).** CODE_PROMPT keeps 1,500 chars of files even over budget; `json.dumps(plan)` turns
   non-ASCII into `\uXXXX` (6x); research and gate feedback in PLAN_PROMPT are uncapped after escaping;
   HR_PROMPT is unbudgeted. Probe: 14.6k chars vs PROMPT_CHARS 9k.
7. **parse_files (A-F6).** A file ends at the LAST closing fence before the next header, so a prose fence
   after the code ("Run it with:" + a fenced command) becomes part of app.py: a SyntaxError and a send-back.
8. **PASS/FAIL (C-M6).** After HR asks for changes, a garbled coder reply `continue`s with `passed=True` from
   the earlier round: the summary says PASS, the last check says FAIL, and HR's objection is lost.
9. **Rename (C-M7).** An invalid entry (`my-app.py`) falling back to `app.py` leaves `my-app.py` planned:
   two server files.
10. **Case (C-M3).** On a case-preserving disk, once `App.py` exists every write of `app.py` keeps the name
    `App.py`; `entry not in files` then loops "create app.py" until send-backs run out.

## Changes

- `f2_dev/unittest_runner.py` (new): TEST_RUNNER, TEST_COMMAND, `test_summary` move out of devfloor.py
  unchanged (devfloor.py is at 499 lines; every fix below adds lines). Re-exported from devfloor.
- `units(plan, owned)`: under the skeleton, store.py is its own unit before test_store.py; STORE_TESTS'
  purpose names the calls ("import store; call store.add(entry) and store.items()").
- Owned-mode test notes name test_store.py and `import store`; `_scan` allows single-underscore attributes in
  test_store.py only (dunders stay banned); `repair_imports(..., allowed=)` adds only modules the file may
  import (store.py: SAFE minus html; test_store.py: SAFE_TESTS).
- Tests: every bad snippet is appended to a valid store and must be rejected for its own reason
  (`"uses getattr" in p`), so only `_scan` can reject it.
- `_scan`: attribute `compile` allowed (`re.compile`); `__all__`/`__slots__` allowed; every problem ends in a
  fix ("store.py may import only: …", "rename it without the leading underscore", "call it directly").
- `stdlib_check.REMOVED_313`: the PEP 594 modules (+ lib2to3) are problems on any tower Python, with
  "removed in Python 3.13; the sandbox runs 3.14" and, for cgi, "use urllib.parse.parse_qs".
- `fit()` in devfloor: one budget routine for CODE/UNIT/HR prompts: trims the QA block, then notes, then
  plan purposes, then the spec, until the fixed part leaves room for files; `ensure_ascii=False`; research
  capped at 1,500 and gate feedback capped after escaping (`_capped`).
- `parse_files`: for a .py file, the last closing fence whose body parses wins (unchanged when the last one
  parses: ``` inside a string still works); other files end at the first bare fence not paired with an
  opening ```lang fence inside the body.
- `build`: a garbled reply re-judges the files on disk with the previous round's test result (files are
  unchanged); an HR objection still pending when rounds run out becomes `hr_question`.
- `plan`: the fallback to app.py drops the planned file that carried the invalid entry name.
- `_write`: a path that differs from the entry only by case is written as the entry (the old-case file is
  removed only after a write to it succeeded); any other case-only name keeps the existing file's name.

## Critique, counters, rulings

1. *Allow single-underscore attributes everywhere (C-M1's fix).* No: `collections._sys`, `threading._os` reach
   sys and os, and DANGER checks exact names only. Allowed in test_store.py only (it already may import os and
   sys; it never runs inside the tower's server). store.py's `self._items` gets a clear rename hint. Cost if
   wrong: a class-based store costs one round to rename a field.
2. *Allow `tempfile` in test_store.py.* No: a test that needs a temp file is testing a file-backed store, which
   7c forbids; the message now lists what is allowed. Cost if wrong: one round.
3. *Keep `from html import escape` auto-repair in store.py.* No: STORE_NOTE forbids escaping and show() would
   absorb it silently; the NameError in the coder's own tests is a clearer signal. Cost if wrong: one round.
4. *Pair fences for .py too (A-F6's first fix).* No: a bare ``` inside a Python string would cut the file.
   Parse-wins keeps today's behaviour whenever the last fence parses. For non-.py files the first unpaired
   bare fence closes the file. Review r2: not for text files (.md/.txt/.rst): a README's bare inner block
   cannot be told from a prose fence, and a cut README lost text without a note, so text files keep the
   last fence as before 8c. Cost if wrong: a README may end with the model's trailing prose (harmless text).
5. *Pin the sandbox image instead of a removed-modules list (C-M4).* Pinning is batch 1 (security). The list
   holds whatever the tower or sandbox Python is. Cost if wrong: a module removed in 3.15 slips by until listed.
6. *Split devfloor.py now.* Batch 4 does the split; this batch moves only the runner (no behaviour change) to
   stay under 500 lines honestly. Cost if wrong: batch 4 rebases one moved block.
7. *Garbled reply = FAIL (simplest).* No: the files did not change, so the last real verdict still holds;
   FAIL would send a passing app back. The HR objection is kept as an open question instead. Cost if wrong:
   a pending HR objection reaches the gate as a question it might have resolved.
8. Reviews: 2 rounds (not a security change; the 7c guard is only made testable, not widened for store.py).

Deferred minors (review r1): `fit()` cannot trim routes' `shows` or the one kept note, so a worst-case plan
(15 long non-ASCII paths, 8 big routes, big QA) still runs ~200 chars over PROMPT_CHARS; and notes are
trimmed before QA/plan/spec, not after QA as stated in C-M5. Both need a reworked trim order; batch 4.

Review r1: C-M3 case fix kept non-entry names (`Utils.py` no longer renames utils.py) and writes before it
deletes (a rejected write leaves App.py); test_store.py's private-import hint now says `store._entries`.
Two guards mutation-confirmed. Two minors deferred above.

Deferred minors (review r2): routes in `fit()` (same as r1's, batch 4; worst case ~9.8k chars with 8 maximal
routes); pinning the sandbox image stays batch 1, so ADDED_314 is hand-kept like REMOVED_313.

Review r2: text files keep their last fence (README fix); E-T1 snippets for `.__class__` and `._sys` now fail
their own mutations; store.py hints drop html; `super().__init__()` is allowed and dunder hints say to use plain
functions; `annotationlib`/`compression` count as standard library. All new guards mutation-confirmed.

Review r3: under the skeleton the coder gets a store-only system prompt (store.py with add(entry) and items(),
test_store.py doing `import store`; no PORT, app.py, test_*.py or add_todo), same role id; the no-files retry
note shows the file the role's own prompt shows (store.py). Minors fixed: a dunder in test_store.py gets a
test fix, a long module name is cut before the allowed list, and `threading._os` says "remove it" (rename only
for `self` or the file's own names). All five guards mutation-confirmed.

## Review Focus

1. Store-first unit order and every owned-mode hint: can any tower sentence still produce rejected code?
2. `_scan` mutations: getattr/os/`__class__`/`._sys` allowed → a test fails; test_store.py `._x` cannot reach
   anything store.py could not.
3. `fit()`: worst-case prompt (15 non-ASCII files, 4 big notes, 1.6k QA) stays ≤ PROMPT_CHARS + files floor.
4. parse_files: ``` inside a Python string still kept; prose fences after code dropped; notes unchanged.
5. Garbled-reply and rename paths: summary, last check and handoff agree.

## Tasks (TDD: RED, watch it fail, GREEN; one commit each)

1. Move the unittest runner out of devfloor.py (refactor, suite green).
2. C-H1: store-first units; STORE_TESTS purpose names the calls.
3. C-H2: owned test notes; test_store.py `._x`; repair_imports allowlist.
4. E-T1: specific-reason store-safety tests; mutation-confirmed.
5. C-M1: false positives and fix hints.
6. C-M4: modules removed in 3.13.
7. C-M5: prompt budgets.
8. A-F6: prose fences after code.
9. C-M6: garbled reply after HR.
10. C-M7: renamed entry; C-M3: case-only names.
