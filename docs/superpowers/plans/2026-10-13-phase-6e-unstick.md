# Phase 6e — Unstick the coder, Docker pre-flight

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** The real 7B run of 2026-10-13 (job 22dfe51addc8) failed 16 coder rounds on the same two failures: its own tests were wrong (module state shared between tests; a whitespace-only mismatch in an expected string), and nothing told it so. Also the job spent model work before discovering Docker was down. Fix both, deterministically first, with one bounded advisory model call.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F2 row: coder loop driven by real Sandbox output; Dev HR).

## Global Constraints
- $0 local; 8 GB. Deterministic help first; at most one F2 HR diagnosis per build attempt, only when stuck.
- Files < 500 lines; tests first; two review rounds; no Co-Authored-By trailer.
- Sandbox output and model text reaching prompts stay wrapped (`untrusted`).

## Critique of the first idea, and the counters
1. **"Give the coder more rounds"** — 16 rounds already failed the same way; more rounds = more heat. Counter: change what the coder sees, not how often.
2. **"F2 HR diagnoses every failing round"** — a 3B call plus a model swap per round on 8 GB. Counter: only when the same failures repeat (stuck), once per attempt.
3. **"Detect shared state with AST analysis"** — brittle. Counter: say the general rule in the stuck note (tests run in alphabetical order and share module state; reset it in setUp; a test's own expectation can be wrong), and let HR read the real output.
4. **Raw output tail** (`output[-1200:]`) can cut the first failure. Counter: parse unittest's own FAIL/ERROR blocks into a compact list (name + assertion line + first diff lines), every failure visible, capped.
5. **Docker pre-flight** could block research-only jobs that never use Docker. Counter: only `run` (app jobs) checks Docker before the job is created; `research`/`ask` don't.

## Rulings
1. "Stuck" = the set of failing test names is identical to the previous round's (and non-empty).
2. Whitespace hint is deterministic: an AssertionError whose two sides are equal after removing all whitespace.

## Review Focus
1. Parser on odd unittest output (errors at import, setUpClass failures, subTest, very long diffs, non-ASCII), and output forged by the app's own tests printing FAIL lines.
2. Stuck detection across HR asks, garbled replies, and the test_first round.
3. Prompt budget (PROMPT_CHARS) with the failure list + stuck note + HR diagnosis.
4. Docker pre-flight when Docker is slow to answer, or `docker` is missing; no orphan job left behind.

### Task 1: Docker pre-flight for `run`
`interface/cli.py` `_tower_job`: for app jobs, `docker_status` must pass before the job is created; clear error, exit 2.

### Task 2: Failure list
`floors/f2_dev/devfloor.py` `failures(output) -> list[dict]` ({test, kind, line, diff}) from unittest's `FAIL:`/`ERROR:` blocks; `_failure_note(failures)` replaces the raw tail when parsing finds blocks (raw tail kept as fallback).

### Task 3: Stuck note + whitespace hint + F2 HR diagnosis
`devfloor.py` build loop: track failing names per round; repeated → stuck note; whitespace-only diff → hint; F2 HR `diagnose_tests(output)` (advisory, once per build) appended wrapped.

### Task 4: two review rounds; real run with the owner's OK.
