# Phase 6k — Test notes the coder can act on

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 9 (job ae149eb2cff9, 2026-10-13) failed F2 for 16 rounds, 4 attempts. 6j worked: there was no
missing import, and the unchanged note fired. The coder's own tests were wrong in two ways:
- `list_todos()` returns a joined string, so `len(list_todos()) == 1` saw 8 (the length of "Buy milk").
- Both tests share one sqlite file in the working directory, so `test_list_todos` expected `""` after
  `test_add_todo` had already added a row.

The tower hid the two facts that would have helped:
1. `_failure_note` cut the stuck note at 250 characters. The sentence "a test's own expected value can be wrong —
   fix the test" never reached the coder ("…a test's own expe").
2. A plain `assert` (pytest-style, no diff lines) showed only "AssertionError: Expected 1 todo item but got 8".
   The source line `assert len(todos) == 1` that produced it was not shown.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F2 coder loop driven by real Sandbox output).

## Global Constraints
- $0 local; 8 GB; deterministic; no new model calls. AI-written code never runs on the host.
- Every note stays within NOTE_CAP after escaping. Files < 500 lines. Tests first; two review rounds.

## Critique of the first idea, and the counters
1. **"Give each test a fresh working directory"** changes what the app's own tests mean and costs a sandbox run per
   test. Counter: say plainly that files the app writes, like a database file, are shared state too.
2. **"Raise the stuck-note cap"** could push the note over NOTE_CAP. Counter: cap the test names (not the sentence),
   and give the failure rows 300 fewer characters when the coder is stuck, so the worst case stays ≤ NOTE_CAP.
3. **"Detect len() of a string"** is too clever and brittle. Counter: show the failing assert's own source line;
   "assert len(todos) == 1 … got 8" is enough for the coder, or for HR, to see the cause.

## Rulings
1. A FAIL with no diff lines shows where it was raised (file, line, function, source), the same as an ERROR.
2. The stuck note is never cut. The test names inside it are capped at 120 characters.

## Review Focus
1. Worst-case note length: 5 huge rows, 2 whitespace hints, stuck note, HR diagnosis, all escaped.
2. unittest `assertEqual` failures keep their diff lines (unchanged), and plain asserts gain the source line.
3. Chained or forged traceback text inside an assertion message.

### Task 1: feedback.py — assert source line, full stuck note, row budget
### Task 2: two review rounds; real run 10.
