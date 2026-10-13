# Phase 6n — Data kept on the request handler is lost

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 12 (job ee05d1cab2b7, 2026-10-13): F2 and F3 passed, and F4 passed 3 of its 4 checks. The app kept
its list on the handler (`self.todo_list = []` in `__init__`, `self.todo_list = add_todo(...)` in `do_POST`,
`list_todos(self.todo_list)` in `do_GET`). http.server makes a new handler for every request, so every item was lost,
and GET / always showed an empty page. F4 said so accurately ("got 200: " with an empty body), but never said why.
The coder did not find it in 4 attempts. The unit tests called `add_todo`/`list_todos` directly, so they passed.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F2 problems before handoff).

## Global Constraints
- $0 local; deterministic; static (ast) only; no new model calls. Files < 500 lines. Tests first; two reviews.

## Critique of the first idea, and the counters
1. **"Make F4 explain an empty page"** — F4 sees only HTTP, not why. Counter: catch the cause in the code, statically.
2. **"Flag every `self.x =` in a handler"** — per-request values (`self.data = parse(...)` read by a helper in the same
   request) are fine. Counter: flag only an attribute one `do_*` method writes and a *different* `do_*` method reads.
3. **Class-level shared lists** (`items = []` in the class body, `self.items.append(x)`) do work across requests.
   Counter: no problem when the class body defines it and no `do_*`/`__init__` method rebinds it on self.
4. **A problem blocks F2** — a false positive would block forever. Counter: only `*RequestHandler` subclasses,
   only the cross-method pattern; the note names the attribute and the fix.

## Rulings
1. Writes = `self.X = …`, `self.X += …`, `self.X[…] = …`, `self.X.append/extend/insert/update/add/setdefault/pop/
   remove/clear/discard(…)`, and `self.X = …` in `__init__`. Reads = `self.X` loaded in a different `do_*` method.

## Review Focus
1. Mixins and helpers (`do_POST` calls `self._save()`, which writes `self.items`): a false negative is acceptable,
   a false positive is not.
2. A handler that stores data in a module global via `global` (fine), `self.server.items` (fine: the server lives on).
3. Names such as `self.path`, `self.headers` and `self.wfile` (never written).

### Task 1: lint.handler_state_problems + wiring into F2 problems
### Task 2: two review rounds; real run 13.
