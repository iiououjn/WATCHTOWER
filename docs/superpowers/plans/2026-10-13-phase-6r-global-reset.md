# Phase 6r — A test that resets its own copy of the app's state

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 16 (job 5e24fe1b4f9f, 2026-10-13) failed F2 in all 16 rounds. The test's setUp did
`global todos; todos = []` after `from todo import add_todo, list_todos`. That made a new `todos` in the test module;
`todo.todos` was never reset, so items piled up across tests (`'test item<br>item1<br>item2' != 'item1<br>item2'`).
F2 HR guessed a newline problem. The stuck note's general advice ("reset module state in setUp") was what the
coder thought it was doing.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F2 coder loop).

## Global Constraints
- $0 local; static (ast) only; non-blocking note (6q's idiom_notes), ≤ 200 chars. Tests first; two reviews.

## Critique of the first idea, and the counters
1. **"Auto-rewrite the reset"** — editing tests changes what they mean. Counter: a precise note naming the module
   and the right line (`todo.todos.clear()` or `todo.todos = []`).
2. **False positives** — a test module can rightly keep its own global. Counter: only when the name is not bound at
   the test module's top level AND a non-test sibling module (one the test imports from) binds it at top level.

## Review Focus
1. `global x` with augmented assignment, `del`, a name the test file also defines, an app module the test does not
   import, packages (`from pkg.store import ...`).

### Task 1: lint — global-reset note in idiom_notes
### Task 2: two review rounds; real run 17.
