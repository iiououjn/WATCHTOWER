# Phase 6m — The app's own error reaches the coder; entry links its own module

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 11 (job 2cc948c23812, 2026-10-13): F2 and F3 passed on every attempt (6k and 6l worked). F4
failed 4 times. `__main__.py` called `list_items()` and `add_item()` but never imported them from `todo.py`:
- GET / sent 200 and its headers, then raised NameError, so the body was empty ("got 200: ").
- POST /add raised NameError, so the connection closed (RemoteDisconnected).
- The unit tests import `todo` directly, so they passed. F3 saw 200, so it passed.

The NameError traceback was at the end of the F4 summary, under "App output". The coder sees only the first 600
characters of each feedback item, so it got the check lines and none of the error.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F2 coder loop, F4 QA).

## Global Constraints
- $0 local; deterministic; no new model calls. AI-written code never runs on the host: repairs are static (ast).
- Files < 500 lines. Tests first; two review rounds.

## Critique of the first idea, and the counters
1. **"Raise FEEDBACK_ITEM"** — the prompt budget (num_ctx) is why it is 600. Counter: put the app's own error
   first in the F4 summary, as one short line: the exception and where it was raised.
2. **"A problem note for undefined names"** — run 8 showed the 7B ignores exact notes. Counter: a static repair like
   6j's `repair_imports`: import a missing name from the one sibling module that defines it, before each test run
   (the sibling may be written after the entry, as in run 11's unit 2).
3. **Risks of importing from a sibling** — a name with two owners, a sibling that imports the entry back
   (a circular import), a sibling named like a standard module, a star import. Counter: in each case, leave the file alone.

## Rulings
1. Only the plan's top-level entry file is linked. Siblings are top-level .py files except test*.py and __main__.
2. The F4 summary's first line stays "QA checks FAILED:" (the tower reads it), and the app error line comes next.

## Review Focus
1. Names bound only inside a function or a class body, comprehension variables, `del`, `global`, names used only in
   annotations or strings, `__name__`/`__file__`.
2. Logs with several tracebacks, chained exceptions ("During handling…"), a SyntaxError (no frame line), and app
   output that forges a traceback.
3. A sibling that defines a name only inside `if __name__ == "__main__":` or in a try block.

### Task 1: F4 app error first
### Task 2: repair_names + _link_entry before each test run
### Task 3: two review rounds; real run 12.
