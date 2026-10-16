# Phase 7d: the tower checks the store contract before F3

**Evidence:** run 38 (job 14738bba5de2). The coder wrote `items = []` and `def get_items()`; the tower's server
calls `store.items()` → TypeError → 500 at F3 on attempts 1 and 2. The F3 diagnosis model then advised "check if
the items method exists", so the coder never fixed the name. The job died mid-attempt 3 (process ended).

**Failure classes, last runs (loop check):** escaping 28-33 (structural fix 7b); stray files 36 (7c); store
contract 38 (first occurrence) → code check, not a prompt.

## Change

`skeleton._contract` (called from `store_problems` for store.py, so it blocks the F2 handoff): store.py must
define module-level `def add(entry)` (one positional argument; extra optional/varargs fine) and `def items()`
(no required arguments), and neither name may be rebound by an assignment, import or other binding. The
problem names the exact fix ("'items' is also assigned or imported: rename that").

## Critique, counters, rulings

- *Run the store and call it instead.* AI code never runs on the host; static is enough for names/arity.
- *Async defs / classes with add/items methods.* Not plain functions the server can call: flagged as missing.
- *A name rebound inside a function body* (local `items = ...`): local, harmless — not flagged.
- *Module-level `items = ...` inside `if __name__ == "__main__":`* is flagged. Cost: one round for an odd store.
- Reviews: 2 rounds (not a security change).

## Review Focus

1. Legit stores: decorators, type hints, defaults, `*args`, docstrings — must pass.
2. Shadowing via `global items` in a function, `del items`, `for items in`, walrus, `with ... as items`.
3. The problem reaches the coder ahead of other lint (store problems first, only 3 shown).
4. No change for non-skeleton apps.

## Review round 1 (fixed)

M1-M3, M5: scoped binding collector — module-level del, except-as, match names, imports, walrus, for/with
targets, a later class/async def/second def of the name, and `global` in any function count as rebinding;
class and function bodies stay local. Tests for each, plus legit decorated/hinted/class-attribute stores.
M4 deferred: with 4+ problems only 3 are shown, so a contract problem can wait one round (rare).
