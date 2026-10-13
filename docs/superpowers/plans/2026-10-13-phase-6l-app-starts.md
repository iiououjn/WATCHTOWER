# Phase 6l — The app must start its server

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 10 (job fee4423300ab, 2026-10-13) was the first run where F2 passed (its unit tests passed after
4 rounds, so 6k worked). F3 then failed 4 attempts in a row: "App app.py did not answer HTTP 200 (got None)".
`app.py` defined `run()`, which calls `httpd.serve_forever()`, but nothing called `run()`: there was no
`if __name__ == "__main__":` block. The app exited with code 0 at once. F3 HR guessed "trying to connect to a service
that's not available" four times. The coder kept the file as it was.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F3 Build: start the app, require HTTP 200).

## Global Constraints
- $0 local; deterministic; no new model calls. AI-written code never runs on the host: the repair is static (ast).
- Files < 500 lines. Tests first; two review rounds.

## Critique of the first idea, and the counters
1. **"A better F3 HR prompt"** — a 3B guessing from "got None" will keep guessing. Counter: F3 already knows
   the process ended; print its exit code and say plainly "it exited before answering".
2. **"Always append `if __name__ == '__main__': run()`"** — that would start a server twice, or call a function
   that needs arguments. Counter: repair only the plan's entry file, only when nothing at top level runs code (no
   top-level call, no `__main__` block, no loop), and only when exactly one top-level function takes no required
   arguments and calls `.serve_forever()` inside it.
3. **"Tests would catch it"** — unit tests import the app, so a `__main__` block never runs under them. Only F3 can
   see it, so F3 must say it clearly.

## Rulings
1. F3 smoke prints `SMOKE_EXIT <code>` when the app stopped before answering. The summary names the exit code and
   says how an entry file starts its server.
2. `repair_main(source) -> (text, name | None)` lives in `repair.py`. `DevFloor._write(files, entry)` applies it to
   the entry file and adds the note "Auto-repaired: app.py never started its server; added
   `if __name__ == "__main__": run()`."

## Review Focus
1. A module with a top-level `run()` call, `main()` with required args, two serving functions, a class method that
   serves, `asyncio`, `serve_forever` behind `if`, a file that does not parse.
2. Forged `SMOKE_EXIT` printed by the app (the app log is printed after the tower's own lines).
3. The unchanged note when the only change is the repair.

### Task 1: F3 exit code and plain summary
### Task 2: repair_main + wiring for the entry file
### Task 3: two review rounds; real run 11.
