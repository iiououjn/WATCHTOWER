# Phase 6q — pytest idioms the unittest runner silently mishandled

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 15 (job 3329c286c571, 2026-10-13) failed F2 in all 16 rounds. The 7B wrote pytest-style tests, and
the tower's unittest runner mishandled three pytest idioms without saying so:
1. `def test_updated_list(client):` and three more like it (a Flask/pytest fixture argument) were skipped as
   "helpers", so 4 of its 7 tests never ran and the coder never knew.
2. `setup_module` / `teardown_module` (pytest names) never ran; unittest only knows `setUpModule`.
3. `@patch('app.add_todo')` and then calling the test's own imported `add_todo`: the patch replaced `app.add_todo`,
   so the real function wrote `todos.txt` ("Called 0 times"), and that file broke `test_get_todos_empty`.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F2 coder loop driven by real Sandbox output).

## Global Constraints
- $0 local; deterministic; static (ast) notes; the runner is the tower's own code in the sandbox. Tests first; 2 reviews.

## Critique of the first idea, and the counters
1. **"Run tests with real pytest"** — not in the sandbox image's standard library, and no network. Counter: honour
   pytest's module and function setup/teardown names in the runner; explain fixtures.
2. **"Note every test_* with arguments"** — helpers like `test_request(path)` are called by real tests (an existing
   runner test pins this). Counter: note only those never called anywhere in their file.
3. **"Fail tests that patch their own target"** — too strong. Counter: a note, only when the test fails, naming the
   test and the patched name.

## Rulings
1. setup_module/teardown_module are used only when setUpModule/tearDownModule are absent; each may take the module.
   setup_function/teardown_function wrap each function test; each may take the function.
2. Notes are non-blocking, at most 2, each ≤ 200 chars, and added only while the tests are not clean.

## Review Focus
1. A module with both setUpModule and setup_module; a setup_module that raises; a fixture-style test that is also
   called; the patch note when the test also imports the module (`import app; app.add_todo(...)` is correct use).

### Task 1: runner hooks; lint.test_notes; wiring
### Task 2: two review rounds; real run 16.
