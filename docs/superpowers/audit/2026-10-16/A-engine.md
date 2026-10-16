# Audit A: engine/, config.py, guardrails.py(+yaml), roles/

Scope: every line of `src/watchtower/engine/**` (incl. governor/, tools/), `config.py`, `guardrails.py`, `guardrails.yaml`, `roles/**`.
Baseline: `uv run pytest -q -p no:cacheprovider` → `1097 passed in 68.31s`.
Probes (scratchpad, not committed): `probe1.py` (socket/budget/knowledge/roles/config), `probe2.py` (crash/resume via real signals on the demo pipeline with a fake model). Real run DBs were copied to the scratchpad and read there; nothing under `~/.watchtower-runs/*/workspaces` was executed.
Tags: **[RUN]** means I reproduced it with a probe or real data. **[READ]** means I found it by reading only.

## Forensics: run38 job `14738bba5de2` stuck in `running`

- The last audit row is seq 141 at `02:15:03Z`, `model_call` to `ollama/qwen2.5-coder:7b`. It has no `model_reply`, no `model_error` and no `job.*` row after it. A Python exception (including KeyboardInterrupt) would have produced either `model_error` or `job.paused`/`job.failed`. So the process was killed by a signal during a 7B call: SIGKILL/jetsam, SIGTERM or SIGHUP. Free RAM was 9 % at seq 119 while qwen was resident, which points to jetsam, but that is not proven.
- The last checkpoint is step 3 (`research`). The `dev` step ran from about 02:01 to 02:15: 10 sandbox runs and about 20 model calls. All of it was lost, because `dev` is a single node (see F2).
- Budget used is 829 s of 3600 s. Recovery needs owner action: `WATCHTOWER_HOME=~/.watchtower-runs/run38 watchtower resume 14738bba5de2 --force`. This re-runs `dev` from scratch.

## Findings (by severity)

### High

**F1. Signals and BaseException leave a job `running` forever, and `resume` refuses even though the job lock proves the process is dead.** [RUN]
- Where: `engine/runner.py:80-83`, `95-99`, `121-131`, `91-94`.
- Cause: `_drive` catches `Exception` and `KeyboardInterrupt` only. SIGTERM and SIGHUP (closing the terminal, `kill`, launchd stop) and `SystemExit` skip `_end`.
- Scenario (`probe2.py sigterm|sighup|sysexit`): the answer step receives SIGTERM. Status stays `running`. `resume` prints "only paused jobs can be resumed (use --force…)". `resume --force` works and skips the finished `plan` step.
- Same result when the cleanup itself fails: `_end`'s `set_status` raising (sqlite busy) at `runner.py:138`, or `bus.publish("job.started")` at `runner.py:82`, which runs before `_drive`'s try block.
- Fix:
  - Install SIGTERM/SIGHUP handlers that raise `KeyboardInterrupt` (or a `Terminated` added to `PAUSE_ERRORS`).
  - Move `set_status`/`publish` inside `_drive`'s try.
  - In `resume` (and `status`), try `flock(LOCK_NB)` on `jobs/<id>.lock`. If the lock is free and the status is `running`, treat the job as crashed and resume without `--force`. The docstring at `runner.py:107-108` already states this invariant.

**F2. The workflow engine is linear only, so the whole F2→F5 loop is one checkpoint.** [RUN] on run38 data.
- Where: `engine/workflow.py:49-55` (only `add_edge` in a straight chain; no loops or conditional edges) forces `tower.py:113` `Step("dev", …)` to hold every attempt, sandbox run and gate.
- Scenario (run38): about 14 minutes of dev work and 10 sandbox runs were lost when the process died. On resume, all of `dev` re-runs and the budget keeps the seconds already spent.
- `pause` (`workflow.py:71`) is checked only at node entry, so `watchtower pause` during `dev` has no effect until the entire loop ends.
- This contradicts the spec ("Every step writes a checkpoint"; goal 4 "never loses work").
- Fix: let `Workflow` support a loop node (a conditional edge back to itself, with the attempt counter, feedback and workspace hash in `data`), so each attempt is a checkpoint, and check `should_pause` per attempt. As a minimum, add a `checkpoint(data)` callback that the step can call between attempts.

**F3. There is no retry or backoff for transient model failures.** [READ]
- Where: `engine/model_socket.py:206-214`.
- Scenario: one connection reset or 5xx from Ollama raises `ModelUnavailable`, which is in `PAUSE_ERRORS` and pauses the job. Because of F2, a reset inside `dev` throws away every attempt so far.
- This contradicts the spec §10: "Retries with exponential backoff for transient failures", and "resumes automatically".
- Fix: retry 2–3 times with backoff on connection or HTTP 5xx errors, re-checking the budget each time; do not retry on timeouts that consumed the budget.

### Medium

**F4. A single call's timeout is the whole remaining job time.** [RUN] P5b
- Where: `model_socket.py:198`.
- Scenario: with a fresh tower budget, `timeout=3600.0` is sent on every call. A hung Ollama call (after a wedged load, or swap thrash at 9 % free RAM) blocks the CLI for up to an hour. Observed real replies maxed at 327 s.
- Fix: add `Settings.call_timeout_s` (for example 600) and pass `min(call_timeout, remaining)`.

**F5. Failed or timed-out calls are never charged.** [RUN] P4
- Where: `model_socket.py:205-225`. `charge` runs only on success.
- Scenario: three calls each hang 90 s and then time out. Wall time burnt is 270 s; `used_seconds` is 0.0. The seconds cap never moves for a model that keeps timing out, so every resume can burn another full timeout.
- Fix: charge the elapsed seconds in a `finally` (tokens 0) before raising `ModelUnavailable`.

**F6. `parse_files` swallows prose fences that come after a file into the file body.** [RUN] P1/P1b
- Where: `model_socket.py:109-118`. It uses the LAST closing fence before the next header.
- Scenario: the model replies `### FILE: app.py` / ```` ```python ```` / code / ```` ``` ```` / "Run it with:" / ```` ``` ```` / `python app.py` / ```` ``` ````. The `app.py` content becomes `'print("hi")\n```\nRun it with:\n```\npython app.py\n'`, which is a SyntaxError. The same happens to the last file in a multi-file reply. This is a very common LLM reply shape, and each occurrence costs an F3 send-back.
- Fix: pair fences. A bare closing fence closes the block unless an unclosed *opening* fence with an info string (```` ```lang ````) is pending inside the body. Alternatively, take the first closing fence followed only by blank lines, a header or EOF.

**F7. Model names without a tag cause an unload and reload on every call.** [RUN] P3
- Where: `model_socket.py:274-278` compares `ollama/<name>` with `/api/ps` names verbatim (`:329`); `config.py:45-49` accepts tagless names.
- Scenario: `WATCHTOWER_WORK_MODEL=qwen2.5-coder`, while Ollama reports `qwen2.5-coder:latest`. The probe shows that every `ask` unloads the very model it is about to use: three calls, three unloads. Each reload of the 7B takes seconds plus a RAM-settle wait, and may hit `LowMemory`.
- Fix: normalise both sides (append `:latest` when there is no tag) in `_resident_ollama` and `load_settings`.

**F8. Budget overshoot is detected only after the reply is produced; the reply is discarded and the job fails for good.** [RUN] P5
- Where: `model_socket.py:188-197`, `budget.py:28-36`, `runner.py:36`.
- Scenario: 990/1000 tokens are used. The call is allowed with `max_tokens=10`, the prompt is 5000 tokens, so `charge` raises `BudgetExceeded`. The good reply is thrown away and the job becomes `failed`, which is terminal. There is no CLI to raise a budget, and `resume` rejects `failed`.
- Fix: estimate prompt tokens (chars/4) before the call and refuse up front; return the reply and enforce at the next `check`; add `budget raise <job>` and allow resuming a budget-failed job.

**F9. Any unexpected exception makes a job permanently `failed`, even though a checkpoint exists.** [READ]
- Where: `runner.py:130-131`, `91`.
- Scenario: two processes share `watchtower.db`, and `busy_timeout` (10 s) expires during a long audit burst, raising `sqlite3.OperationalError: database is locked`. Or an `OSError` occurs in the workspace. Either way the status is `failed` with "unexpected error…", and the job cannot be resumed by any command.
- Fix: map `sqlite3.OperationalError` and `OSError` to pause, and let `resume --force` accept `failed`.

**F10. Concurrent jobs: the scheduler waits 30 s, model calls take 78–327 s, and advisory roles are skipped silently.** [READ] plus [RUN] (call durations from the run DBs)
- Where: `scheduler.py:48`, `advisory.py:6`, `tower.py:180,343,356`.
- Scenario: job B starts while job A's coder call holds the only slot (`agent_slots=1`). B's required roles hit `SchedulerBusy`, which pauses B. B's HR/QA-office/memo roles count `SchedulerBusy` as advisory and are *skipped*, so B gets a quietly lower-quality run with no signal to the owner.
- Fix: drop `SchedulerBusy` from `ADVISORY_ERRORS`; wait longer for required roles, or refuse to start a second job while a slot holder is alive.

**F11. Errors in cleanup mask the real error.** [READ]
- Where: `scheduler.py:55-57` (`memory.save` and `bus.publish` in `finally`).
- Scenario: the model raises `LowMemory`, which should pause. Then `memory.save` hits "database is locked", so `OperationalError` replaces `LowMemory` and the job is marked `failed` (F9) instead of `paused`.
- Fix: wrap the cleanup in try/except and log it; never let it replace an in-flight exception.

### Low

**F12. The sandbox mislabels its own in-container timeout.** [RUN]
- Where: `sandbox.py:80`, `92-94`.
- `timeout -s KILL` exits 137, not 124 (checked on the host: `timeout -s KILL 1 sleep 5` → 137). If the inner timeout fires, the result is `exit_code=137, timed_out=False`, which is the same signature as a `--memory 512m` OOM kill. In practice the host timeout, which is the same number, usually fires first, which makes the inner guard mostly dead.
- Fix: set the host timeout to inner + 10 s; treat 137 as `timed_out` when elapsed ≥ timeout.

**F13. The `ask_files` JSON fallback returns unvalidated entries.** [RUN] P2
- Where: `model_socket.py:241-245`.
- `{"files": ["app.py", {"path": 5, "content": null}]}` is returned as-is, and `Workspace.write` raises `AttributeError`, not `WorkspaceError`. This is currently guarded by the caller (`floors/f2_dev/devfloor.py:443-461`), but it is a contract leak.
- Fix: filter to dicts with a `str` path, and a `str` content or `delete: true`, inside the socket.

**F14. The role loader does not type-check its fields.** [RUN] P8
- Where: `roles/__init__.py:45-48`.
- `tools: web.search` (a string) becomes `('w','e','b',…)`.
- `floor` is unvalidated: `roles/csuite/cpo.yaml:3` says `c-suite` while ceo/cto say `csuite`. `tower.py:318` keys board briefs by floor, so a typo silently drops the brief.
- Fix: require `tools` to be a list of str and `floor` to be in a known set.

**F15. Config is not validated.** [RUN] P9
- Where: `config.py:53-55`.
- `WATCHTOWER_MIN_FREE_RAM_PCT=150` is accepted, so every model load raises `LowMemory` and every job pauses. `-5` is accepted and disables the RAM guard. `abc` errors with a message that does not name the variable.
- A relative `WATCHTOWER_HOME` is accepted and created relative to the cwd.
- `sandbox_image` is unvalidated and the default `python:latest` is unpinned: about 1 GB, not reproducible, and drifts with every pull.
- Fix: range-check to 0–90, resolve home to an absolute path, and pin a slim digest.

**F16. `Knowledge.add` is check-then-insert.** [RUN] P7
- Where: `knowledge.py:59-78`.
- A second process that passed the SELECT gets `IntegrityError: UNIQUE constraint failed` instead of the existing id.
- Fix: run the SELECT inside `BEGIN IMMEDIATE`, or `INSERT … ON CONFLICT DO NOTHING` followed by a SELECT.

**F17. `Knowledge.search` silently drops document ids, and FTS titles are inconsistent.** [READ]
- Where: `knowledge.py:85` keeps the 50 lowest ids, so the newest accepted pages are the ones dropped.
- Where: `knowledge.py:73` stores the raw `title` in FTS (possibly `""`), while `knowledge_docs.title` falls back to the source (`:69`), so a title search misses those documents.

**F18. bandit B608 at `knowledge.py:90-97` is a FALSE POSITIVE.** [RUN] P6
- Only `?` placeholders are interpolated, the ids are `int()`-cast (`"1); DROP TABLE jobs; --"` raises `ValueError`), and MATCH terms are `\w+` tokens wrapped in quotes.
- `'" OR 1=1 --'`, `NEAR(a b)`, `*`, a 100 KB query, unicode and empty input all behave safely.
- Fix: add `# nosec B608` with a one-line justification.

**F19. Dead or unwired code versus the spec's claims.** [READ]
- `engine/tools/hub.py` (`ToolHub`) and `engine/governor/secrets.py` (`SecretStore`) are referenced only by tests.
- `Role.tools` is never enforced, so spec §9 "per-role tool permissions" and "Keychain scoped handles" are not live.
- The `review` tier (`config.py:11`) is used by no role.
- `ContextStore` restore-on-wake (`scheduler.py:51`) is always overwritten (`runner.py:161,166`), yet every call writes 10–20 KB of prompts to `agent_context`, which is never pruned and never read.
- Fix: delete these, or wire them up and say so in the spec.

**F20. `_swap_to` unloads every resident model, including models used by other processes or by the owner's own Ollama session.** [READ]
- Where: `model_socket.py:270-277`.
- This contradicts `unload_all`'s docstring "never another process's" (`:306`). It matches the one-model rule, but the docstring is wrong.
- When `/api/ps` fails (`_resident_safe` returns `[]`), a model that is already resident is treated as not loaded, so RAM is checked again and `LowMemory` can be raised spuriously.

**F21. The audit hash chain has no key or anchor.** [READ]
- Where: `audit.py:25-27`, `80-88`.
- Anyone with file access can `DROP TRIGGER`, edit a row and recompute every later hash, and `verify()` still passes.
- Acceptable for a single-owner local tool, but "tamper-evident" overstates it. Fix: periodically anchor the head hash outside the DB (git note or file), or use an HMAC with a Keychain key.

**F22. The `seconds` budget counts model time only.** [RUN] run DBs
- Where: `budget.py` (docstring says "wall-clock"); `config.py:22` says the "time cap bounds a job".
- Sandbox runs, the RAM-settle sleeps (up to 5 s) and scheduler waits (up to 30 s) are not counted. Measured: run39 used 758 s of model time against 840 s of wall time.
- Fix: rename the field to "model seconds", or charge sandbox time too.

**F23. `runner.start` does not require status `queued`.** [READ]
- Where: `runner.py:74-83`.
- Calling it on a paused job re-invokes the graph with fresh input on the same `thread_id`, restarting from START and overwriting `data`. Only the CLI calls it today, and only for new jobs, so this is latent.
- Fix: guard on `queued`.

**F24. `Workflow` opens one checkpoint connection per pipeline.** [READ]
- Where: `workflow.py:48`. That is three connections per runner, with the default 5 s timeout and no `busy_timeout` pragma. The SqliteSaver puts the file in WAL (confirmed for run38), so the risk is low.
- Fix: share one connection and set `busy_timeout`.

## Verified OK (brief)

- **db.py migrations:** atomic (schema change and `user_version` bump in one `BEGIN IMMEDIATE`), serialised across processes with flock, WAL on, `busy_timeout` 10 s. [READ]
- **AuditLog.append:** atomic under `BEGIN IMMEDIATE`. UPDATE/DELETE triggers present. `verify()` is correct. [READ]
- **Approvals.decide:** race-safe through `WHERE status='pending'`. [READ]
- **Job lock:** the flock is released by the kernel when the process dies; probe2 showed that `--force` resume works and skips finished steps. [RUN]
- **Workflow resume:** resumes from the last finished step; a crashed step re-runs (only `answer` was re-called). [RUN]
- **Workspace path checks:** `..`, absolute paths, backslash, control characters, hidden files, symlinked target, suffix allowlist, 100 KB and 30-file caps, parent re-check after mkdir. [READ]
- **Sandbox argv:** no network, read-only rootfs, read-only `/src`, tmpfs scratch, memory/cpu/pids limits, cap-drop ALL, no-new-privileges, non-root, `--pull never`, container named and killed on timeout. [READ]
- **guardrails.py:** strict types, unknown keys rejected, size cap, dangling-link and directory cases raise, per-key override of the packaged defaults. [READ]
- **parse_json:** tolerant of fences and prose; rejects arrays and control characters. [RUN]
- **free_ram_pct:** `memory_pressure` returns in 0.006 s; returns None on failure. [RUN]
- **Ollama keep_alive=0 unload and make_room:** behave as designed (run38 seq 119/128 show `make_room` firing). [RUN]
- **Test suite:** `uv run pytest -q` → 1097 passed in 68.31s. Not run: anything against a live Ollama or Docker.
