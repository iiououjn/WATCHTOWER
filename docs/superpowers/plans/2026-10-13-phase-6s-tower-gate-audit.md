# Phase 6s — The tower's own checks decide; full audit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real runs 4–17 never shipped an app. Run 17 (job 8169deae2e86) shows the structural flaw:
- Attempt 2 passed F2 and F3, then failed F4 on a QA check that POSTs an **empty** item and expects
  "Todo item added successfully!". No correct app passes that check.
- Attempts 3–4 never reached F3/F4: the coder broke **its own** unit tests, and F2 blocks on them.

Both judges are 7B-written. Phases 6k–6r taught the coder one mistake at a time (whack-a-mole, tuned on
one prompt). Owner chose option A: the tower's own checks decide, not the coder's tests.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F2 row: "Unit tests pass in Sandbox").
This phase changes that row; the spec is updated in Task 2.

## Global Constraints
- $0 local; deterministic; no new model calls. AI-written code never runs on the host.
- Files < 500 lines (tests included). Tests first; two review rounds.

## Critique of option A, and the counters
1. **"Drop the coder's unit tests entirely."** They still give the coder fast, real feedback inside F2.
   Counter: keep them running and fed back; they stop *blocking* the handoff.
2. **"Then F2 lets garbage through to F3."** Counter: F2 still blocks on the planned entry file being
   present and on the tower's own static problems (stdlib-only imports, handler-state lint). F3 must start
   the app and get HTTP 200; F4 runs the spec-derived checks; F5 scans. Those are the tower's checks.
3. **"The QA checks are 7B-written too."** True: they were written by F4's model from the spec before the
   code exists, independent of the coder. Counter: validate them statically. A form value that is empty or
   whitespace while the check expects success (status < 400) is dropped: no correct app passes it, and an
   empty value expecting 4xx stays (a real validation check). Control characters in check names are dropped
   (deferred p5 M4).
4. **"The model gate may reject an app whose own unit tests fail."** Counter: the evidence line says
   the coder's tests are advisory; if the gate still rejects, the coder gets the reason, like today.
5. **"Overfit to one prompt."** Counter: after merge, run the todo prompt *and* one different prompt.

## Rulings
1. `f2_handoff(checks_run, entry, files) -> (go, reasons)` lives in `floors/f2_dev/handoff.py` (pure).
   go = entry present and the last F2 round has no blocking problems. A failing test run gives
   go=True with reason "coder's own unit tests fail (advisory)".
2. Each F2 `tests` check records `"problems": [...]` (tower static problems, ≤200 chars each).
3. `_evidence`: "- coder unit tests (advisory): pass|FAIL".
4. Result-line forgery by a deliberately hostile app (p6c3/p6d M6) stays deferred: the QA runner has the
   same exposure the F2 runner had; the threat is a 7B mistake, not a hostile app.

## Audit (bullet-train) findings folded in
- `test_devfloor.py` 1034, `test_runner.py` 1000, `test_cli.py` 534 lines → split (pure moves).
- `SECURITY.md` says "email the maintainer" with no address → GitHub private vulnerability reporting.
- `.github/` has no workflow: the PR template's "`uv run pytest` passes" is never checked → add CI.
- Lint (ruff F/B/PL): no real bugs in `src`; dead imports/vars in tests fixed; `config.py:53` int default.

## Review Focus
1. An F2 round whose coder reply was garbled (no `problems` key) with the entry present.
2. Stdlib-only violation + passing tests: must still block.
3. QA check `{"item": " "}` expecting 200 vs 400; a check whose only form value is empty.
4. All checks dropped by the validator → zero checks never pass (6g) and the QA office re-asks.
5. Split tests: same test count before and after.

### Task 1: QA check validator (empty success form values, control chars)
### Task 2: F2 handoff helper, tower wiring, evidence, spec row
### Task 3: split oversized test files; lint fixes
### Task 4: SECURITY.md, CI workflow
### Task 5: two review rounds; real runs 18 (todo) and 19 (different prompt)
