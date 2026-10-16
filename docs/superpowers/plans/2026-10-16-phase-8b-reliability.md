# Phase 8b: reliability (audit batch 2)

**Goal:** a killed, crashed or paused app job loses at most one attempt, resumes without owner tricks, and a
flaky Ollama no longer pauses the job on the first reset. Audit 2026-10-16 items 4, 5, 6 and the reliability
Mediums: A-F1, A-F2/B-M6/E-A2, A-F3, A-F4, A-F5, A-F8, A-F9, A-F10, A-F11.

**Evidence:** run 38 (job 14738bba5de2): the process died during a 7B call (likely jetsam at 9 % free RAM).
The job stayed `running`; `resume` refused without `--force`; resume re-ran all of `dev` (about 14 minutes,
10 sandbox runs), re-planned and reset the send-back counter.

## Diagnosis

- `_drive` catches `Exception` and `KeyboardInterrupt` only: SIGTERM/SIGHUP/SIGKILL and a failing cleanup leave
  `running`. `resume` checks the status before it takes the job lock, so it cannot use the one fact that proves
  the process is gone: the kernel dropped its flock.
- `Workflow` is a straight chain; `dev` (F2→F5, up to 4 attempts) is one node, so it is one checkpoint, and
  `should_pause` is checked only at node entry.
- `ModelSocket.ask` turns any completion error into `ModelUnavailable` at once (no retry); the call timeout is
  the whole remaining job time; a failed call is never charged; a reply that overshoots the budget is
  discarded by `charge` raising `BudgetExceeded`.
- Any other exception marks the job `failed`, which nothing can resume.
- `SchedulerBusy` is an advisory error, so a second job silently skips HR/QA-office/memo roles after 30 s;
  `memory.save`/`bus.publish` in the scheduler's `finally` can replace the real error.

## Changes

1. **Dead owner.** `resume` takes the job lock first, then checks the status: `running` under a free lock means
   the owner died, so it resumes without `--force` and records `job.recovered`. SIGTERM/SIGHUP during a run
   pause the job (`Terminated`, a pause error). `start` records `running` inside the guarded drive. `watchtower
   status` shows `running (process gone; resume it)` when the lock is free.
2. **Per-attempt checkpoint.** `Step(resumable=True)` steps get a `Progress`: `state` (what the step saved) and
   `save(state)`, written to `step_progress` in the checkpoint DB, then the owner's pause request is honoured.
   Progress is cleared when the step finishes and on a fresh run. `_dev` saves after planning and after each
   failed attempt: plan, next attempt, feedback, model_heard, units_due, owned paths, QA round, expect text,
   docs, focus and the memo context. On resume it restores them: no re-plan, no skeleton re-apply, counter kept.
   When the send-backs run out, progress is cleared before `NeedsOwner`, so an owner's resume starts a fresh
   round on purpose.
3. **Retry.** Around the socket's own call boundary (`self._complete`), transient errors (builtin
   `ConnectionError`/`TimeoutError`, any `status_code` 5xx, or a known transient class name in the MRO:
   litellm's and httpx's connection, timeout and server errors) are retried with backoff 2 s, 4 s; the budget
   is re-checked before each retry. Other errors are not retried. Each failure is audited (`model_error` with
   `attempt`).
4. **Timeout and charging.** `Settings.call_timeout_s = 600`; a call gets `min(call_timeout_s, remaining)`.
   Every failed call is charged its elapsed seconds (tokens 0).
5. **Overshoot.** The socket records usage without enforcing (`Budget.record`) and returns the reply; the next
   `check` stops the job.
6. **Unexpected errors pause.** `_drive` maps any other `Exception` to `paused` with the error type, message and
   the raising frame recorded (`job.error` event), so `resume` can retry it.
7. **Concurrency and cleanup.** `SchedulerBusy` leaves `ADVISORY_ERRORS` (it pauses, it never silently skips);
   the slot wait defaults to `Settings.slot_wait_s = 600` (longer than the longest observed call, 327 s).
   Scheduler cleanup errors are reported (`agent.cleanup_failed`, best effort) and never replace an in-flight
   error.

## Critique, counters, rulings

- *Make `dev` a real LangGraph loop node.* Cleaner, but rewrites the 133-line `_dev` that batch 4 splits
  anyway. Ruling: `Progress` side table now; the loop node can come with the split. Cost if wrong: one more
  migration of the progress keys in batch 4.
- *Checkpoint per floor inside an attempt.* Needs every WorkPackage serialised. Ruling: per attempt. Cost if
  wrong: a crash loses at most the attempt in flight (about 3-5 minutes on 8 GB).
- *Resume after the send-backs ran out keeps the counter* (strict reading of "do not reset"). Then a resume can
  never do anything but fail again. Ruling: clear progress at exhaustion only; crashes and pauses keep it. Cost
  if wrong: an owner resume buys up to 4 more attempts of model time.
- *Retry timeouts?* A wedged Ollama could cost 3 x 600 s. Ruling: retry them (task scope), but every retry
  re-checks the budget and the per-call cap is 600 s. Cost if wrong: up to 20 extra minutes before a pause.
- *Classify by litellm exception types.* Batch 4 swaps litellm for httpx. Ruling: classify by builtins,
  `status_code` and class names in the MRO, so both libraries match without importing either. Cost if wrong: a
  new transient type pauses as before (no worse than today).
- *Refuse a call up front from a chars/4 prompt estimate.* The estimate is wrong for code and would fail jobs
  that fit. Ruling: keep the reply, enforce at the next check. Cost if wrong: one call's tokens over the cap.
- *Let `resume --force` accept `failed`.* Rejections and budget fails would re-raise anyway. Ruling: no; the
  fix is that unexpected errors pause. Cost if wrong: an old job failed by an unexpected error stays failed.
- *A bug that raises every time now pauses forever instead of failing.* Ruling: acceptable; the reason and the
  frame are recorded and the owner sees them. Cost if wrong: an owner resumes once more before reading.
- *SIGTERM handler outside the main thread.* `signal.signal` raises there. Ruling: install only in the main
  thread; elsewhere the lock check still recovers the job.
- Reviews: 2 rounds (not a security change).

## Review Focus

1. Resume restores exactly the attempt state: no architect, CTO, QA-office or focus call on resume; counter kept.
2. A free lock is the only proof of a dead owner: never resume a job whose lock is held.
3. Retry only transient errors, re-check the budget each time, never retry `BudgetExceeded` or a bad reply.
4. Cleanup and charging paths can never replace the error that is already in flight.
5. Pause between attempts takes effect after the attempt's progress is saved, not before.

## Tasks

1. Dead owner: lock-first resume, `job.recovered`, SIGTERM/SIGHUP pause, guarded start, status mark.
2. Workflow `Progress` (resumable steps, save/clear, pause on save).
3. `_dev` saves and restores attempt state; clear at exhaustion.
4. Socket retry with backoff on transient errors.
5. Per-call timeout cap; charge failed calls.
6. Overshoot keeps the reply (`Budget.record`).
7. Unexpected errors pause with the error recorded.
8. `SchedulerBusy` not advisory; slot wait 600 s; cleanup never masks the error.

## Existing tests whose expectations changed (on purpose)

- `resume` of a `running` job with a free lock no longer needs `--force` (test_runner, test_cli).
- A `ConnectionError` is tried three times before the pause: three `model_error` rows, `answer` called 4 times.
- An overshooting reply is returned; the next call raises `BudgetExceeded` (test_budget_exceeded_stops).
- An unexpected `RuntimeError` pauses (exit 3) instead of failing (test_unexpected_error_never_leaves_job_running).
- Tests keep the retries but not the backoff seconds (conftest `no_retry_waits`); test_model_retry checks 2 s, 4 s.

Every new guard was mutation-checked: removing it makes its test fail.

## Review r1

- Fixed: `transient()` reads class names before the status code, so `litellm.Timeout` (408) is retried; a test
  uses real litellm exceptions behind `importorskip`. A local retry runs `_swap_to` again, so RAM and the
  resident list are re-read after an Ollama crash. `_end` guards its publish like `_record_error`. The pause
  message names the dev attempt.
- Deferred minors: (1) `owner_alive()` takes a brief exclusive probe lock, so a `start`/`resume` racing a
  `status` can fail with "running in another process"; `LOCK_SH` does not help (start's `LOCK_EX` still
  conflicts), the fix is a retry-once in the start/resume probe. (2) `dev` clears its progress row before
  LangGraph writes the node checkpoint; a crash in that window re-runs dev from scratch. Move the clear to
  the next node or to `_invoke` after a done result.
