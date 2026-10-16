# Audit E — Tests, tech stack, architecture (HEAD d07c5e3, 2026-10-16)

Method: scratch `git worktree` (removed afterwards), baseline `uv run pytest -q` = **1097 passed in 84s**
(68–72s on later full runs). 52 hand-written mutations; targeted test files first, every survivor
re-run against the **full suite**. Import graph and dead-code scripts over `src/` via `ast`. `uvx ruff`
(ephemeral cache, nothing installed). Not run: anything with Docker or Ollama, any AI-written workspace code,
the GitHub Actions workflow itself, an order-randomised suite.

---

## 1. Mutation table

"Killed by" is the first failing test. Survivors were re-run on all 1097 tests.

| ID | Behaviour | Mutation | Result | Killed by |
|---|---|---|---|---|
| M01 | escape-once `show()` | drop the unescape loop (store-escaped text double-escaped) | killed | test_skeleton::test_a_store_that_escapes_on_save_still_shows_text_once |
| M02 | escape-once `show()` | `return text` (raw, XSS) | killed | test_skeleton::test_template_with_a_correct_store_passes_every_tower_check |
| M03 | status-only softening | `expect_escaped` checks may be softened | killed | test_contract::test_status_only_never_passes_a_wrong_status_or_an_escape_or_form_check |
| M04 | status-only softening | echo checks may be softened | killed | test_contract::test_an_echo_check_keeps_gating |
| M05 | status-only softening | drop "one text check must really pass" | killed | test_qafloor::test_qa_script_ignores_an_app_that_prints_a_fake_pass |
| M06 | owner sign-off gating | `pending` counts as approved | killed | test_runner_app::test_deleted_file_before_sign_off_fails_cleanly |
| M07 | sign-off gating | `--yes` auto-signs despite a gate objection | killed | test_contract::test_a_lone_model_objection_goes_to_the_owner_not_the_coder |
| M08 | sign-off gating | `--yes` auto-signs despite CEO reject | killed | test_runner_app::test_ceo_reject_stops_auto_sign_off |
| M09 | release pinning | changed file hash not detected | killed | test_releases::test_verify_reports_changed_missing_and_extra_files |
| M10 | write allowlist | suffix check removed | killed | test_workspace::test_rejects_unsafe_paths[x.exe] |
| **M11** | write allowlist | `target.is_symlink()` escape check removed (workspace.py:38) | **SURVIVED** | — |
| M12 | write allowlist | 100 KB cap removed | killed | test_workspace::test_rejects_huge_file |
| **M13** | store_problems | `getattr` no longer banned | **SURVIVED** | — |
| **M14** | store_problems | `os` added to the store import allowlist | **SURVIVED** | — |
| **M15** | store_problems | dunder-attribute (`x.__class__`) check removed | **SURVIVED** | — |
| M16 | store_problems | DevFloor never calls it | killed | test_skeleton::test_a_server_inside_the_store_is_a_problem (via test_store.py only) |
| M49 | store_problems | whole `_scan` off for store.py (still on for test_store.py) | killed | test_skeleton::test_store_problems_come_first (the **only** test that pins it) |
| M17 | sandbox flags | `--network none` removed | killed | test_sandbox::test_runs_command_with_hardening_flags |
| M18 | sandbox flags | workspace mounted rw | killed | same |
| M19 | sandbox flags | `--cap-drop ALL` removed | killed | same |
| M20 | sandbox flags | in-container `timeout -s KILL` removed | killed | test_sandbox::test_container_has_hard_in_container_time_limit |
| M21 | budget | at-cap pre-call check removed | killed | test_budget::test_check_blocks_when_exactly_at_token_cap |
| **M22** | budget | `ModelSocket.ask` never calls `budget.check()` (model_socket.py:186) | **SURVIVED** | — |
| M23 | budget | over-cap after `charge()` not enforced | killed | test_budget::test_token_limit_exceeded_raises_and_records |
| M24 | `untrusted()` | `<` not escaped | killed | test_floor::test_untrusted_wrapper_cannot_be_closed_or_spoofed |
| M25 | `untrusted_code()` | closing tag not escaped | killed | test_floor::test_untrusted_code_keeps_angle_brackets_but_escapes_tags |
| M26 | `untrusted()` | source attribute not sanitised | killed | test_floor::test_untrusted_wrapper_cannot_be_closed_or_spoofed |
| M27 | checkpoint resume | in-memory checkpointer | killed | test_workflow::test_resume_in_a_new_process_uses_checkpoint |
| M28 | checkpoint resume | resume restarts from the first step | killed | test_workflow::test_crash_then_resume_skips_finished_steps |
| M48 | pause | pause check removed from nodes | killed | test_workflow::test_pause_between_steps_then_resume |
| M29 | netguard | only loopback blocked | killed | test_netguard::test_non_public_addresses_blocked[10.0.0.5] |
| M30 | netguard | IPv4-mapped unwrap removed | SURVIVED (equivalent) | stdlib 3.12.4+ already returns `is_global=False` for `::ffff:127.0.0.1` |
| M31 | audit chain | `prev_hash` column check removed | SURVIVED (equivalent) | the digest already chains on the running `prev` |
| M32 | F4 fresh token | F4 reuses the coder's token | killed | test_contract::test_f4_runs_a_fresh_token_the_coder_never_saw |
| M33 | escape-once QA | `expect_escaped` never set | killed | test_contract::test_values_carry_markup_and_the_list_checks_expect_it_escaped |
| M34 | F2 handoff | tower static problems no longer block | killed | test_handoff::test_tower_problems_still_block |
| **M35** | QA anti-forgery | accept the first of several `WATCHTOWER_QA` lines (qafloor.py:338) | **SURVIVED** | — |
| M36 | XSS probe | an empty or unanswered probe counts as clean | killed | test_probe::test_an_app_that_answers_nothing_is_incomplete_not_clean |
| M37 | security fail_on | MEDIUM-confidence findings ignored | killed | test_oversight::test_guardrails_choose_which_severities_fail |
| M38 | deploy | edge port on 0.0.0.0 | killed | test_deploy::test_deploy_builds_offline_and_runs_isolated_on_localhost |
| M39 | deploy | app network not `--internal` | killed | same |
| M40 | cloud off | cloud-disabled check removed | killed | test_model_socket::test_cloud_model_blocked_by_default |
| M41 | one model in RAM | others never unloaded | killed | test_model_socket::test_only_one_local_model_loaded |
| M42 | glass injection | regex matches nothing | killed | test_glass::test_injection_paragraph_stripped_with_note |
| M43 | owned-path guard | coder may overwrite the tower server | killed | test_skeleton::test_coder_cannot_overwrite_or_delete_an_owned_file |
| M44 | 7c write rule | skeleton coder may write any file | killed | test_skeleton::test_a_skeleton_coder_writes_only_the_store_and_its_tests |
| M45 | F2 test bar | ≥2 real tests → ≥1 | killed | test_devfloor::test_one_test_or_tests_that_ignore_the_app_do_not_pass |
| M46 | retro injection filter | removed | killed | test_runner_app::test_retro_lessons_never_reach_cpo_or_floor_1_and_injections_are_dropped |
| M47 | memo cap | removed | killed | test_memos::test_memos_are_capped_per_floor_and_answers_cannot_send_memos |
| M50 | approvals | a decision can be overturned | killed | test_approvals::test_cannot_decide_twice |
| M51 | stdlib_only | import check disabled | killed | test_devfloor::test_third_party_import_is_not_a_pass |
| M52 | Lookout scoping | returns pages this lookup's glass did not pass | killed | test_lookout::test_lookout_returns_only_pages_this_lookup_accepted |

**Score:** 52 mutants: 44 killed, 2 equivalent, **6 real survivors** (M11, M13, M14, M15, M22, M35).
The suite is strong on the pipeline's decision logic. It is weak exactly where the code is security-only and
tests were written as lists of bad inputs (see T1).

---

## 2. Tests

### T1 — High — 7d made the 7c store-security tests vacuous
- Where: tests/test_skeleton.py:345-413 (`EVASIONS`, `ALIASES`), checked by
  `test_the_store_may_import_only_safe_modules` and `test_allowed_modules_cannot_reach_dangerous_ones`.
- Evidence: every one of the 25 snippets lacks `def add`/`def items`, so `_contract()` (7d, skeleton.py:194)
  flags each one whatever `_scan()` decides. I checked each with `_scan` against `_contract`: all 25 are flagged
  by both. That is why M13 (`getattr` unbanned), M14 (`os` allowed) and M15 (dunder attributes allowed)
  survive all 1097 tests. Only M49 (the whole scan off) is caught, and only by `test_store_problems_come_first`.
- Fix: assert the specific reason, not "any problem mentions store.py". For example, append `STORE` to each
  snippet and assert `"imports os" in p` / `"uses getattr" in p`, or test `_scan()` directly.

### T2 — Medium — the QA result anti-forgery guard is untested (M35)
- Where: qafloor.py:338 (`len(found) == 1`); the same pattern is in probe.py (`len(found) == 1`).
- Evidence: M35 (take the first result line) survives the full suite. The guard's comment says "a second line
  means someone forged one", but no test prints two lines. `test_qa_script_ignores_an_app_that_prints_a_fake_pass`
  covers app stdout, which the script already JSON-encodes into the log line.
- Fix: a unit test that feeds `run_qa` a `SandboxResult` with two `WATCHTOWER_QA` lines and asserts FAIL. Do the
  same for `xss_probe`. See also A8 for the design gap behind it.

### T3 — Medium — the socket never pins its own budget pre-check (M22)
- Where: model_socket.py:186 `self._budget.check(job_id)`.
- Evidence: deleting the line survives all 1097 tests. `test_budget.py` tests `Budget.check` itself, but no
  socket test starts at the cap. A job at exactly its cap gets one more model call (`max_tokens=max(1, 0)` = 1,
  `timeout=max(1.0, …)` = 1 s).
- Fix: `budget.open(max_tokens=5); charge(5); with raises(BudgetExceeded): sock.ask(...)`, and assert that the
  completion function was never called.

### T4 — Low — dangling-symlink write escape is untested (M11)
- Where: workspace.py:38 `or target.is_symlink()`.
- Evidence: M11 survives. A dangling symlink `ws/a.py -> /tmp/outside.py` makes `probe` walk up to the parent,
  which resolves inside the root, so only `is_symlink()` stops `write_text` from following the link out.
  Exposure is low: nothing in the pipeline creates symlinks (the Sandbox never writes back).
- Fix: add a test with `os.symlink("/tmp/x.py", ws/"a.py")` and expect `WorkspaceError`.

### T5 — Medium — integration tests never run the real QA or probe scripts against the tower's own server
- Where: tests/conftest.py `FakeSandbox.run` (around line 95-125). It returns scripted pass/fail for
  `WATCHTOWER_QA`/`XSS`/`PROBE` regardless of the files on disk. `test_runner_app.py`, `test_contract.py` and
  `test_runner.py` all use it.
- Evidence: the template plus `QA_SCRIPT` is exercised only piecewise in test_skeleton.py `_qa()`. No test drives
  `TowerPipeline._dev` with a host-subprocess runner over the skeleton (no Docker needed). Spec §11's "golden
  jobs" and "load check" tests do not exist.
- Fix: one golden test. Use `RoleModel` replies plus a `run` that executes `QA_SCRIPT`/`XSS_SCRIPT`/`build_check`
  in a tmp dir with `sys.executable -I` (tower code plus a fixture `store.py`; no AI code), and assert
  `released`.

### T6 — Medium — ~17 s of the 68-84 s suite (about 20%) is spent on dead or trivial code
- Evidence (`--durations`):
  - `test_model_socket::test_default_completion_silences_litellm_banner` takes 8.67 s, all of it `import litellm`,
    to check one boolean.
  - `test_tool_hub.py` takes ~8.2 s across 4 tests that spawn real MCP stdio servers for `ToolHub`, which has
    zero production callers (A3).
  - `test_probe::test_a_hanging_route…` sleeps 5 s on purpose.
- Fix: delete ToolHub and its tests (A3). Mark the litellm test `slow`, or remove it together with litellm (S1).

### T7 — Low — port TOCTOU in subprocess tests
- Where: test_skeleton.py:30 `_port()` binds port 0, closes it, then the app binds it later. The same pattern is
  in test_qafloor, test_probe and test_deploy.
- Evidence: the 7a plan doc already records "F3 smoke test flake seen once in a full-suite run; did not reproduce".
- Fix: pass port 0 to the app and have it print the bound port, or retry on `EADDRINUSE`.

### T8 — Low — weak or vacuous asserts
- test_devfloor.py:356: `== ['App.py','store.py'] or == ['app.py','store.py']`. A disjunction hides which
  behaviour is intended; pin the case-insensitive rule.
- test_devfloor_loop.py:307: `'IsolatedAsyncioTestCase' in err or 'not run' in err`.
- test_db.py:63: a `try/except: pass` around `connect()`. The test passes if the migration never raises.
- No-assert smoke tests: test_budget.py:52, test_scheduler.py:70, test_knowledge.py:34, test_db.py:14.
  Acceptable as smoke tests, but test_scheduler.py:70 should at least assert two sessions were live together.

### T9 — Low — tests are coupled to private internals
- 15 distinct `_private` names are imported by tests, plus 18 private-method calls (e.g. `floor._problems()`).
- Production keeps re-exports alive only for tests:
  - tower.py:24 `# noqa: F401 — re-export` of `_evidence`, `_reference`, …
  - devfloor.py:15 `# noqa: F401 (re-export)` of feedback privates.
- Test-only production API: `Releases.record`, `WorkPackage.from_dict`, `SecretHandle.reveal`, and the `WT_PORT`
  env hook in `QA_SCRIPT`/`XSS_SCRIPT` (the sandbox always uses 8000).
- Fix: import from the owning module and drop the re-exports.

### T10 — Low — test hygiene
- 8 test files use `from *_kit import *` (ruff F405 ×100+). Ruff also reports F811 redefinitions:
  test_contract.py:236 and :247, test_skeleton.py:116 and :238 (fixture shadowing).

Network, Docker and Ollama: none are touched by the tests (the sandbox, deploy, socket and search are all
injected fakes). Host subprocesses run only tower-written scripts and fixtures. `test_tool_hub` spawns
`tests/fixtures/echo_mcp_server.py`.

---

## 3. Tech stack

### S1 — High — litellm is about a third of the install and ~4.4 s of import, used for one call
- Where: model_socket.py:138-148. The only uses are `litellm.completion(**kw)` and `litellm.completion_cost()`,
  and the cost path runs only for cloud models, which are disabled (config.py:20).
- Measured:
  - `site-packages/litellm` is 109 MB of a 322 MB venv (130 packages). It also pulls boto3/botocore (25 MB),
    tokenizers, tiktoken, openai and huggingface_hub.
  - `import litellm` takes 4.4-5.3 s and adds ~180 MB RSS: CLI alone 115 MB, CLI plus litellm 295 MB. On
    8 GB that is RAM taken from the 7B model at every model call.
- README claims it provides "retries, JSON extraction, and token counting" (README.md:36 and :256). False: retries
  and JSON parsing are the tower's own code (`ask_json`, `parse_files`), and token counts come from Ollama's
  `usage`.
- Version bound `litellm>=1.50` has no upper bound on a package that releases almost daily. The lock pins
  1.105.0.
- Fix: replace it with ~40 lines of `httpx.post(f"{ollama_url}/api/chat", json={model, messages, stream: False,
  format: "json"?, options: {num_ctx, num_predict}})`, reading `prompt_eval_count`/`eval_count`. Keep a
  `completion_fn` seam so an optional `watchtower[cloud]` extra can bring litellm back.

### S2 — High — mcp and keyring are production dependencies with zero production callers
- `mcp>=2.3,<3`: used only by engine/tools/hub.py (`ToolHub`, 93 lines), which nothing in `src/` imports. It
  pulls pydantic, starlette, uvicorn, pyjwt[crypto] and cryptography (11 MB).
- `keyring>=25`: used only by engine/governor/secrets.py (`SecretStore`, 44 lines), which nothing in `src/`
  imports.
- README.md:39 and :61 advertise both as working features.
- Fix: delete both modules and dependencies, or move them to an extra until a floor actually uses them.

### S3 — Medium — langgraph (+ langchain_core) is ~1.1 s of CLI import and used as a for-loop
- Where: workflow.py:8-9, 49-56.
- The graph is a strictly linear chain of 2-6 named steps, with no branches, no interrupts and no state
  reducers. CLI import is 1.66-1.97 s total, of which `watchtower.engine.workflow` is 1.14 s: langgraph 0.79 s
  plus langchain_core tracers.
- The tower needs about 30 lines: a stdlib `sqlite3` table `(job_id, step_index, data_json)`, written
  synchronously after each step. That is all `durability="sync"` and `SqliteSaver` are used for.
- Fix: replace it after the checkpoint-granularity question (A2) is settled. Today langgraph checkpoints a
  130-line `_dev` loop as one node, so its value is small.

### S4 — Low — remaining dependencies are justified
- trafilatura (fetcher.py:12): justified. It brings babel (32 MB via courlan) and lxml (19 MB).
- ddgs (search.py:22): justified, lazy-imported. It brings `primp` (13 MB native).
- httpx: justified.
- typer: justified, though stdlib argparse would do for 16 commands.
- pyyaml: justified (roles, guardrails, glass rules).
- bandit (oversight.py:25): justified; it runs as `python -m bandit` in the host venv on AI files (read-only
  analysis, not execution).
- click is imported directly (cli.py:7) but not declared; it arrives only transitively through typer. Declare
  it.

### S5 — Medium — the Python version is not pinned anywhere
- There is no `.python-version`, and `requires-python = ">=3.12"`. The real `.venv` is 3.12.12; a fresh
  `uv run` in the scratch worktree resolved **3.13**.
- CI (`astral-sh/setup-uv@v5`, no `python-version`) is therefore on whatever uv picks, and README says 3.12.
- Fix: commit `.python-version` (3.12), and use `python-version: "3.12"` plus `uv sync --locked` in CI.

### S6 — Medium — CI checks only "pytest passes"
- Where: .github/workflows/tests.yml.
- No `--locked`/`--frozen`, so lock drift is not caught. No ruff, no type check (none configured in
  pyproject, though `.ruff_cache` exists locally and the code carries `noqa` codes). No test of the built wheel
  (YAML roles and guardrails are package data). No `--durations`. It runs on `macos-latest` (10× minute
  cost) while every test is platform-neutral except Keychain, and Keychain is dead code (S2).
- `uvx ruff check` today:
  - src: 1 F401 (skeleton.py:8 unused `PurePosixPath`)
  - 2 B023 loop-variable closures: tower.py:152 (`on_unit` captures `written`, harmless here) and lint.py:70
  - 2 B905
  - 10 B904
  - 11 C901, worst `tower._dev` at complexity 19 with 101 statements
  - tests: 4 F811 plus F405 noise
- Fix: add `[tool.ruff]` (`select = ["F","B","E9","C901"]`) and `uv run ruff check` to CI, and switch the runner
  to `ubuntu-latest`. mypy is optional: the code is hint-heavy but untyped-checked; start with `--strict` on
  `engine/`.

### S7 — Medium — sandbox and deploy image is `python:latest`
- Where: config.py:28 and :54; README.md:234.
- Unpinned: the QA/test environment changes under the tower with every Docker pull. `--pull never` only
  freezes whatever was last pulled.
- Fix: pin `python:3.12-slim@sha256:…` and have `doctor` check the digest.

---

## 4. Architecture

Import graph (ast, 63 modules): no cycles. Layer edges that point the wrong way:
- `engine.runner` → `tower`, `beacon`, `floors.f4_qa_deploy.releases`: the engine depends on the application.
- `floors.f2_dev.devfloor` → `floors.f4_qa_deploy.qafloor` (`parse_routes`), and `floors.f2_dev.skeleton` →
  `floors.f4_qa_deploy.contract` (`contract_checks`): F2 depends on F4.
- `evidence` (top level) → `floors.f5_oversight`.
- `tower.py` imports 31 internal modules.

### A1 — High — `tower.py` is the god object; the 500-line rule was met by compression
- `TowerPipeline._dev` (tower.py:119-251) is one 133-line method: complexity 19, 101 statements (ruff C901,
  PLR0915). It owns F2 units, the F2 build, the F2→F3, F3→F4 and F4→F5 handoffs, the model gate, objection
  routing, CEO, retro, the release payload, feedback assembly per floor, re-plan and QA re-plan.
- The 500-line limit comes from the unrelated Ruflo template at ~/CLAUDE.md:12 ("Keep files under
  500 lines"). It was met by squeezing:
  - devfloor.py has 499 lines with constants glued to function ends (line 88 `MAX_FILES_PER_ROUND` directly after
    `return`) and tuple-packed constants (107 `MAX_UNITS, UNIT_FILES = 4, 3`).
  - tower.py:67-68: a class with no blank line before it.
  - skeleton.py:16: two comments on one line.
  - 34 lines over 120 chars, 8 in tower.py.
- Real splits:
  1. `tower/dev_loop.py`: a `DevAttempt` object with `build() → f3() → f4() → f5() → gate() → feedback()`, each
     returning a typed result. `_dev` becomes a 20-line loop.
  2. `tower/memos.py`: `_call` and `_route_memo` (with `MEMO_*` constants), or move them into `floors/board.py`.
  3. `csuite/cpo.py`: `questions`, `_spec`, `_app_spec`, `QUESTIONS_PROMPT`, `SPEC_PROMPT`. The prompts belong in
     the CPO role YAML; inline prompts contradict "roles as config".
  4. `tower/signoff.py`: `_signoff_request`, `_signoff`, `OWNED_NOTE` and the release text.
  5. `floors/f1_research`: move `_f1` and `_context` there.
  6. `devfloor.py`:
     - `TEST_RUNNER` (devfloor.py:25-74, a 50-line program inside a string) → `f2_dev/test_runner_script.py`,
       shipped as a file and run as `python -I <file>`, so ruff and tests can see it.
     - `_write` (complexity 18) → `f2_dev/writer.py`.
     - `app_is_tested` → lint.py.
  7. `qafloor.py`: `QA_SCRIPT` (qafloor.py:27-137) → `f4_qa_deploy/qa_script.py`, the same way. probe.py
     `XSS_SCRIPT` likewise.
  8. `cli.py`: doctor checks (cli.py:204-270) → `interface/doctor.py`; deploy commands (436-485) →
     `interface/deploy_cmds.py`.
  9. Move `engine/runner.py` to the top level (`watchtower/app.py`), so `engine` stops importing `tower`.
  10. Move `parse_routes` and `contract_checks` into `floors/contract.py` (shared), so F2 stops importing F4.

### A2 — High — checkpointing granularity does not match spec §4 ("Every step writes a checkpoint")
- Where: tower.py:111-114, runner.py:67-72.
- The app workflow has 6 steps, and all of F2, F3, F4 and F5, across up to 4 attempts and dozens of model calls,
  are **one** node (`dev`).
- A crash, kill or LowMemory in attempt 3 resumes from the start of `_dev`:
  - The architect re-plans (new model calls).
  - `apply_skeleton` deletes non-owned files.
  - The attempt counter resets to 0, so `max_send_backs` is unbounded across resumes.
- Run 38 ("process died mid-attempt 3") is this case.
- Fix: persist `(plan, attempt, feedback, model_heard, units_due)` in the step data at the end of each attempt.
  Either make each attempt a resumable sub-step (a loop node keyed by attempt) or store an attempt record in
  SQLite that `_dev` reads on entry.

### A3 — High — spec components that exist only as dead code or not at all
- Tool Hub (spec §4) is dead code: engine/tools/hub.py:37 `ToolHub` has no production import. Every role has
  `tools: []`, and `Role.tools` is never read. The spec's "per-role tool permissions" are implemented by having
  no tools.
- Governor secrets (spec §4, §9) are dead code: governor/secrets.py:22 `SecretStore` has no production import.
  README.md:271 also mislabels the file "Secret detection patterns"; detection is `beacon/glass.py:31 SECRET`.
- Memory is write-only:
  - Scheduler.agent restores `session.context` (scheduler.py:51), but `JobRunner._ask_role` overwrites
    `session.context["messages"]` on every call (runner.py:161).
  - `_ask` does the same (runner.py:166).
  - So `ContextStore.load` feeds nothing, and every model call costs two SQLite context writes plus
    `agent.wake`/`agent.idle` audit rows.
  - Long-term memory is in fact the retro lessons in Knowledge.
- The `review` model tier (config.py:11) is used by **no** role (all roles are `small` or `work`). README.md:83
  says review runs "Audit, security review, CEO/CTO recommendations"; they run on `small`. Cross-family review
  happens only because `small` is llama and `work` is qwen.
- Spec items not built:
  - Dashboard/API (FastAPI, WebSocket) and auth (spec §8), apart from `user_id`/`workspace_id` columns.
  - launchd health check and auto-restart, and auto-resume on restart (§4).
  - Retries with exponential backoff (§10); no backoff exists anywhere.
  - Automatic resume after a model limit (§10).
  - Golden-job and RAM load tests (§11).
- Fix:
  1. Delete ToolHub, SecretStore and ContextStore, or wire them. Deleting is cheaper: the scheduler can keep slots
     without memory.
  2. Remove the `review` tier, or point `f5.dev_gate`/`f5.auditor`/`ceo` at it.
  3. Mark the unbuilt items "not built" in the spec.

### A4 — Medium — every floor handoff passes through F5 in name only
- README.md:184 says "Every floor handoff passes through a Floor 5 gate (deterministic rules + model review)".
- In code, the F2→F3, F3→F4 and F4→F5 "gates" are `_handoff()` (tower.py:364), which only publishes the floor's
  own boolean to the bus. There is one model gate per attempt, on tier `small` (dev_gate.yaml).
- That design is fine, but the docs overclaim. Fix the README and spec §5 wording.

### A5 — Medium — the audit log is "tamper-evident" only against naive edits
- Where: audit.py:80-88.
- The chain is an unkeyed SHA-256. Anyone with write access to `~/.watchtower/watchtower.db` can drop the
  triggers and rewrite the whole chain consistently, and `logs`/`doctor` will say "ok".
- M31 shows the `prev_hash` column check is redundant (equivalent mutant).
- Fix: either say "detects accidental or partial edits", or anchor the head hash outside the DB (an HMAC key in
  Keychain would finally give SecretStore a caller).

### A6 — Medium — test and QA results share the container with the app under test
- Where: qafloor.py:27-137, probe.py:13-72.
- `QA_SCRIPT` starts the AI-written app as a child process: same uid, same PID namespace, `/proc` readable, and
  the checks JSON is in the parent's argv. The app can:
  1. Read the expected names from `/proc/<ppid>/cmdline`.
  2. Write a forged `WATCHTOWER_QA` line to `/proc/<ppid>/fd/1`.
  3. Kill the parent.
- The parser then sees exactly one line and accepts it. Not exploited or tested (I did not run AI code). The
  threat is low with a local model, but it is the injection path spec §1.3 rules out, and T2 shows the
  one-line guard is untested.
- Fix: run the app and the checker in separate containers (checker on a shared internal network). Or at least
  run the app as a different uid with `hidepid`, and pass the checks via stdin rather than argv.

### A7 — Low — the "demo" pipeline behind `ask` is vestigial
- runner.py:68 and 171-176: spec §8 says `ask` is "one model". It is a two-step plan→answer checkpointed
  workflow with its own `PLAN_PROMPT`/`ANSWER_PROMPT` in the engine.
- Fix: make `ask` a single `socket.ask`.

### A8 — Low — `Sandbox.run` calls `check()` on every run
- sandbox.py:68: `docker info` plus `docker image inspect` (2 extra docker CLI round-trips) precede each of the
  ~10-20 sandbox runs per attempt.
- Fix: check once per job.

### A9 — Low — naming and duplication
- Two different `_PATH` regexes: qafloor.py:13 and probe.py:75.
- Three near-identical "start app, poll `/` for 10 s" preambles: QA_SCRIPT, XSS_SCRIPT and buildfloor.
- `untrusted`/`untrusted_code` duplicate the source sanitiser (framework.py:12 and :22).
- `_evidence`, `_finding_query` and `_status_query` are "private" yet imported across modules.
- `devfloor.test_summary` is a production function named `test_*`. pytest only skips it because it lives in
  src.
- Fix: one `app_harness.py` shared by the three scripts.

### Docs and CLAUDE.md accuracy

**D1 — Medium — README is wrong in these places:**
- :19 "Every agent runs … inside a sandboxed Docker container". Agents run on the host; only agent-written code
  runs in Docker.
- :36 and :256: litellm "retries, JSON extraction, token counting" (S1).
- :39: MCP (dead, S2).
- :61: Keyring (dead, S2).
- :83: the review tier (unused, A3).
- :184: "every handoff … model review" (A4).
- :271: secrets.py "Secret detection patterns" (it is a keyring store).
- :27: "type-hinted throughout", with no checker.
- :46: Click is "Typer's backend", yet it is imported directly and undeclared.

**D2 — Medium — CONTRIBUTING.md:**
- :17 says to pull `qwen2.5-coder:3b`, but the default work model is `qwen2.5-coder:7b`, so `doctor` will
  report a missing tier model.
- :13 says Docker is needed "for the sandbox tests"; none exist (all are faked), and :34 says so.
- :42 "each floor … owns its … tests"; all tests live in `tests/`.
- :48 Conventional Commits: 165 of 254 commits match. All recent phase commits ("Phase 7d: …", "7d review r2: …")
  do not.

**D3 — Medium — CLAUDE.md files:**
- ~/CLAUDE.md is a generic "Ruflo" swarm template:
  - It mandates `npm run build && npm test` (line 151) and `npx @claude-flow` memory hooks.
  - It is the source of the 500-line rule that caused A1's line-squeezing.
  - It applies to this Python repo because the repo sits under ~.
- The project CLAUDE.md is **untracked** (`?? CLAUDE.md`). It holds only the run-report template: no
  `uv run pytest`, no layout notes, no "never run workspace code on the host" rule.
- Fix:
  1. Move the Ruflo file out of the home directory, or scope it.
  2. Commit the project CLAUDE.md with test, lint and safety rules, and drop the 500-line rule in favour of
     complexity limits (C901).

**D4 — Low — the spec is still "Draft, awaiting owner review" (spec line 5)** after 45 phases. Phase 7
(dashboard) is next on the plan, yet no API layer exists to hang it on.

---

## 5. Accretion: code that exists to compensate for small models

Src LOC by merge:
- Phase 6d (5,175) → 6z (6,642): **+1,467 lines (21% of today's 6,991)**, almost all small-model compensation
  (6e-6z). Tests over the same span: +2,455.
- 7a-7d added +349 src lines.

Compensation inventory (today):

| Module or function | Lines | Phase / run | Still needed by skeleton apps (7a)? |
|---|---|---|---|
| repair.py `repair_main` (+helpers) | ~73 | 6l, run 10 (server never started) | **No**: the tower writes the entry |
| repair.py `repair_names` / devfloor `_link_entry` | ~75 | run 11 (entry missing sibling imports) | **No** |
| lint.py `handler_state_problems` (+`_writes`/`_reads`/`_self_*`) | ~90 | 6n, run 12 (state on the handler) | **No**: there is no handler |
| qafloor `_same_request_hints`, `_request` | 23 | 6o | **No**: tower checks are fixed |
| QA_SCRIPT URL-encoded and XSS / double-escape hints, `ESCAPE_NOTE` | ~25 | 6p, 6y, 6z | **No**: the server parses and escapes (`STORE_NOTE` replaces it) |
| qafloor `test_first_text`, `_unmarked`; QAOffice text heuristics | ~40 | 6g, 6t | **No** for deciding checks (contract_checks decide) |
| QA pieces / glued-text matching (QA_SCRIPT) | ~15 | 6t | **No** |
| repair.py `repair_strings` | ~55 | 6h | Yes (store.py is still coder-written) |
| repair.py `repair_imports` | ~70 | 6j, 6x | Yes |
| lint.py `idiom_notes`, `_global_resets`, `_test_file_notes` | ~85 | 6q, 6r | Yes (test_store.py) |
| devfloor `TEST_RUNNER` pytest shim | 50 | 6q | Yes |
| feedback.py | 124 | 6e, 6k | Yes |
| stdlib_check.py | 34 | — | Yes |
| contract.py, handoff.py, skeleton.py | 416 | 6s, 6u, 7a-7d | Yes (this *is* the new path) |

- **Verdict:** about **415 lines** (the "No" rows, measured by function spans) plus their ~600-800 test lines
  exist only for apps where the coder writes the HTTP server.
- None of that can be deleted while the non-skeleton path lives. Its record since 7a: run 35 FAIL, run 39 PASS
  with "label doubled, 500 on bad input, naive form parsing".
- Recommendation: add a second template family (form → compute → result page, covering the tip-calculator
  class) and refuse other app shapes with a clear owner message. Then delete the "No" rows (~415 lines plus
  tests), and with them most of devfloor's multi-file unit machinery (`units()`, `write_units`, `_SAFE_ENTRY`
  rewriting, `_ensure_packages`). Alternative: keep the coder path but freeze it (no new 6x-style patches),
  and accept that it is best-effort.

---

## 6. Ranked summary

1. **High** T1: the store allowlist security tests are vacuous since 7d. M13, M14 and M15 survive the full suite.
2. **High** S1: litellm (109 MB, 4.4 s import, +180 MB RSS) for one Ollama call. Replace with httpx.
3. **High** S2 / A3: mcp and keyring are shipped for dead code (ToolHub, SecretStore). Memory is write-only. The
   review tier is unused.
4. **High** A2: all of F2-F5 is one checkpoint. A resume re-plans and resets the send-back counter.
5. **High** A1: tower._dev is complexity 19; the 500-line rule (inherited from an unrelated template) was met by
   squeezing. 10 concrete splits are listed above.
6. **Medium**:
   - T2: untested QA anti-forgery guard (M35), plus A6, the shared-container forgery path.
   - T3: socket budget pre-check (M22).
   - T5: no golden end-to-end test.
   - T6: 17 s of the suite spent on dead or trivial code.
   - S3: langgraph used as a for-loop.
   - S5: Python version not pinned.
   - S6: CI is pytest only.
   - S7: `python:latest` image.
   - A4: handoff gates overclaimed.
   - A5: audit chain claim.
   - D1, D2, D3: docs and CLAUDE.md.
7. **Low**:
   - T4: symlink check (M11).
   - T7: port TOCTOU.
   - T8: weak asserts.
   - T9: tests coupled to privates.
   - T10: test hygiene.
   - A7: `ask` demo pipeline.
   - A8: per-run docker check.
   - A9: naming and duplication.
   - D4: spec still draft.
   - The S4 nit: click undeclared.
