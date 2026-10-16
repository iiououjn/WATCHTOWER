# Phase 8a: security batch (audit 2026-10-16, batch 1)

**Goal:** close the audit's security items before more runs: sandbox evidence the app cannot forge, no host-run
line, a human sign-off on every release and deploy, bounded sandbox output, clean terminal output, no hidden
coder files, a pinned sandbox image and project Python.

**Evidence:** `docs/superpowers/audit/2026-10-16/` — B-H1, B-M1, B-M2 (pipeline); D-H1, D-M1, D-M2, D-M4, D-M5,
D-M7 (security); E-A6, E-T2, E-S5, E-S7 (tests/stack). Baseline `uv run pytest -q` → 1097 passed.

## Diagnosis

1. **Forgeable sandbox results.** QA, the XSS probe and the route probe accept one result line whatever the
   harness exit code; the app (same uid, same PID namespace) can write one line to `/proc/<ppid>/fd/1` and
   SIGKILL the harness. Smoke takes the *first* `SMOKE_STATUS`/`SMOKE_TEXT` match, and the app's raw log is
   printed after it, so the app does not even need to kill anything. The one-line guard is untested (E-T2).
2. **Host-run line.** `tower.py` ends every app answer with `Run it: cd <ws> && python <entry>`, including
   `--yes` jobs nobody read. `python app.py` puts the workspace on `sys.path[0]`: every AI-written module runs.
3. **`--yes` releases unseen.** `_signoff_request` skips the owner unless the CEO model says `False` or the gate
   objected; `Deployer.deploy` checks only that a release exists.
4. **Unbounded capture.** `Sandbox.run` uses `subprocess.run(capture_output=True)`: gigabytes of container
   output are held in host RAM before the 20 kB tail is cut (probe: 400 MB → 888 MB RSS).
5. **Terminal escapes.** `status` prints `j.prompt`/`j.error` raw (error holds gate reasons and app logs);
   `_report` prints a failed reason raw; the CPO error is raw; `logs` prints details raw. `_clean` keeps
   Unicode bidi/zero-width characters.
6. **Hidden coder files.** `Workspace.snapshot` stubs *any* file starting with the tower mark, so a coder file
   with that first line hides its body from the gate, HR, QA writer and auditor.
7. **Unpinned image and Python.** `python:latest` is the sandbox and deploy base; no `.python-version`, so a
   fresh `uv` picks 3.13 while the project says 3.12.

## Changes

1. Every harness parser (QA, XSS probe, route probe, smoke) requires `exit_code == 0`, not timed out, and
   exactly one result line. Smoke prints its app log JSON-encoded on one `SMOKE_LOG` line (as QA does) and its
   own three lines are matched anchored, each exactly once; the summary shows the decoded log.
2. The release answer drops the host-run line; it points to `watchtower deploy <job>` only.
3. `--yes` covers the CPO questions and the spec step only. Every app sign-off is an owner approval;
   `_signoff` also covers checkpoints saved before 8a (no `signoff_id`: reuse or request one).
   `Deployer.deploy` refuses a job without an approved `signoff` record (`Approvals.signed_off`).
4. `engine/sandbox.capped_run` replaces `subprocess.run` as the Sandbox default: `Popen` plus one reader
   thread per pipe keeping a bounded tail; output is decoded with `errors="replace"`.
5. `_clean` strips Unicode `Cc`/`Cf` except `\n`/`\t`; `status`, `logs`, the failed reason and the CPO error go
   through it.
6. `Workspace.write_tower` records the hash of what the tower wrote (shared per workspace root in this
   process: the tower re-opens the workspace per step); `snapshot` stubs only those paths, and only while the
   bytes still match. `skeleton.apply` writes the server through it.
7. `Settings.sandbox_image` = `python:3.14.8@sha256:b9767f56…` (the digest already local, so no pull and no
   behaviour change); `WATCHTOWER_SANDBOX_IMAGE` must be digest-pinned (`name[:tag]@sha256:<64 hex>`, which
   also keeps docker flags and Dockerfile lines out). `.python-version` = 3.12 (uv reads it); CI runs
   `uv sync --locked`.
8. litellm offline env (D-M3): skipped — batch 4 removes litellm.

## Critique, counters, rulings

- *A structural fix: the checker in its own uid or container.* Not feasible inside the current sandbox design:
  the container runs `--user 1000:1000 --cap-drop ALL --security-opt no-new-privileges`, so the harness cannot
  start the app under another uid, and `--network none` leaves no way for a checker container to reach the app.
  **Ruling:** do the now-fix (exit 0 + the result tag exactly once). It defeats the audited attack: killing the
  harness gives exit 137 (FAIL); not killing it gives two tags (FAIL). *Corrected in review r1:* "two lines" was
  wrong. A forged line plus one byte with no newline makes the real line start mid-line, and the anchored `^TAG`
  match then saw only the forgery. The tag is now counted as a substring anywhere in stdout+stderr
  (`sandbox.tagged`), every harness writes each line on a fresh line in one flushed write (`EMIT`), and every
  JSON value is written with `_` as `\u005f` so app text (log, page body, route path) can never hold a tag.
  *Corrected in review r2:* ptrace was not the only path left. The app can `setsid` out of the harness's
  `killpg` (a double-fork escapes the process group), write a forged tag to the harness's stderr, then flood its
  stdout until the real tag falls out of the kept 20 kB tail. `SandboxResult.truncated` now marks any cut-off
  output (`capped_run` dropped bytes, or a stream over `MAX_OUTPUT`) and `sandbox.result_tag` never reads a
  tag from it; every variable-size harness line is capped (`fit`) so honest runs stay under the limit.
  **Remaining path:** a same-uid app that can `ptrace` the harness or the container's PID 1 (`timeout`) can
  still rewrite them; an escaped setsid child can still write to the harness's streams, which now only fails
  the run (two tags or cut-off output). **Structural step (later phase):** run the app and the checker in separate containers on
  a per-run `--internal` network, the checker image holding only the harness. Cost if wrong: a hostile app with ptrace can still forge F3/F4/F5 evidence;
  Docker and the owner's read (now mandatory, change 3) remain the boundary.
- *Mark the harness non-dumpable (`PR_SET_DUMPABLE 0`) as a cheap step.* It blocks `/proc/<ppid>/fd` and ptrace
  of the harness but not of PID 1, so it does not close the remaining path. **Ruling:** not done here; part of
  the structural step. Cost if wrong: one more attack variant stays open until then.
- *The unit-test runner (`WATCHTOWER_TESTS`) has the same shape.* AI tests run inside that process, so no parser
  rule can make it honest; it is the coder's own advisory evidence and the tower's F3-F5 checks decide.
  **Ruling:** unchanged. Cost if wrong: a coder can fake its own unit-test pass, which decides nothing alone.
- *Smoke: keep the raw app log after the result lines.* An app line `SMOKE_STATUS 200` would then make two
  matches (FAIL) — safe but noisy for a genuine app that logs such text. **Ruling:** JSON-encode the log on one
  line (QA's pattern). Cost if wrong: none for honest apps; the coder still sees the decoded log.
- *Exit 0 might fail honest runs.* Every harness ends with `print` and exits 0; a harness crash was already a
  missing line. Cost if wrong: one more FAIL on a harness bug, visible in the summary.
- *`--yes` now pauses for sign-off.* The owner asked for `--yes` jobs to be read; the spec is shown in the
  sign-off when the owner never approved it. **Ruling:** `--yes` = no questions + spec auto-approved. Cost if
  wrong: unattended runs wait at sign-off (by design).
- *Deploy refusing pre-8a releases made under `--yes`.* Those have no approved sign-off and must not deploy.
  Cost if wrong: the owner re-runs or approves; no unread app ships.
- *Capping in the container (`| tail -c`)* loses the exit code (no `pipefail` in dash). **Ruling:** cap on
  the host with bounded reads. Cost if wrong: two short-lived threads per sandbox run.
- *Pin to `python:3.12-slim`* (the audit's suggestion) would need a pull and change the sandbox Python under
  every existing check (3.14 → 3.12). **Ruling:** pin the 3.14.8 digest already local; the 3.12 vs 3.14 stdlib
  mismatch is batch 3 (C-M4). Cost if wrong: the owner pulls once if the digest is missing (`doctor` says so).
- *Strip `Cf` everywhere* also drops soft hyphens and joiners from model text in the terminal. Cost: cosmetic.
- *`logs` was already safe* (the detail dict's repr escapes control characters); it goes through `_clean` too, so
  a later change to the detail format cannot reopen it. Its test is a regression guard, not RED-first.
- *`--yes` legacy path:* a checkpoint saved before 8a with no `signoff_id` reuses the job's latest sign-off row or
  requests one, then waits. The request step and this path each have their own test (either alone would hold).
- *Review r2: also require the real tag on stdout's last line and absent from stderr.* Not done: with the
  output uncut, a forged tag anywhere (stdout or stderr) makes two tags and fails; several harnesses emit more
  than one tower line, so "last line" would need per-harness ordering rules for no gain. **Ruling:** fail closed
  on `truncated` plus the existing count over both streams. Cost if wrong: an attack that forges a tag without
  leaving the real one or cutting the output stays open; none is known.
- *Review r2: a hostile app can now force a FAIL by flooding output.* It could already fail itself (crash,
  wrong answers). Cost if wrong: none; fail closed is the intended direction.
- Reviews: 3 rounds (security).
- *Review r1 (1 critical, 2 minor).* Critical: spliced-line forgery of the QA/XSS/probe/smoke result (ruling
  above corrected; four splice tests, a stray-byte test and an `EMIT` test, each guard mutation-checked).
  Minor: `rollback` skips targets whose job has no approved sign-off (same rule as `deploy`); the resume/approve
  `Error:` and `Beacon paused:` echoes go through `_clean`. Deferred minors: none.
- *Review r2 (1 critical, 2 minor).* Critical: tail-eviction forgery (the r1 ruling above corrected): `truncated`
  flag from `capped_run` and `Sandbox.run`, `result_tag` fails closed on it in QA/XSS/probe/smoke, harness
  lines capped with `fit` (QA details shrunk first). Minor: the sandbox image name must start with `[a-z0-9]`
  (no leading `-` reaching `docker run` as a flag); the app log in smoke/QA/probe is read exactly once
  (`result_log`), a second log line shows a note instead of a fake. Each guard mutation-checked. Deferred
  minors: none.

## Review Focus

1. Can an app still make QA/XSS/probe/smoke report PASS without the harness's own single line and exit 0?
2. Is there any path left to `released`/`deploy` without an owner `approved` sign-off row (old checkpoints too)?
3. `capped_run`: memory bound, timeout kill, no deadlock on a full pipe, decoding of broken UTF-8.
4. Every CLI echo of stored or model text goes through `_clean`; bidi/zero-width stripped.
5. Snapshot stubs only bytes the tower wrote in this process; a resumed job shows the server in full until
   `apply` rewrites it.

## Tasks

1. Sandbox result integrity: exit 0 + one line in QA, XSS probe, route probe; smoke one-line log and exact
   matches (tests: two lines, killed harness, first-match forgery).
2. Bounded sandbox capture (`capped_run`).
3. Release answer without the host-run line.
4. `--yes` spec only; sign-off always owner-approved (old checkpoints too); deploy requires it.
5. Terminal-safe CLI output.
6. Tower-mark stub only for tower-written bytes.
7. Pin the sandbox image (digest) and the project Python (`.python-version`, CI).

## Result

Seven task commits, each RED first; every new guard mutation-checked (removing it fails its test).
`uv run pytest -q` → 1132 passed (baseline 1097; +35 tests), on Python 3.12.12.
Review r1: `uv run pytest -q` → 1146 passed.
Review r2: `uv run pytest -q` → 1165 passed.
