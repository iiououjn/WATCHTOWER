# Phase 8d: structure and stack (audit batch 4)

**Goal:** the tower ships only what it uses, talks to Ollama directly, and its biggest files are split by job,
not squeezed under 500 lines. Audit 2026-10-16 items 10, 11 and 12, plus CI lint, docs and dead code:
E-S1, E-S2, E-S3 (noted), E-S6, E-A1, E-A3, E-D1, E-D2, E-D4, A-F19, D-M3 (the litellm half).

**Owner decisions (made):** (a) replace litellm with a small direct httpx client to Ollama, keeping the
`ModelSocket` interface, the tiers, one model in RAM and offline behaviour; nothing may reach the internet.
(b) remove the unused components: mcp + ToolHub, keyring + SecretStore, the write-only memory module and its
writes, the unused `review` tier; the spec says they are deferred, not built.

**Baseline:** `uv run pytest -q` on main after 8a-8c: 1259 passed (the 1097 in the audit predates 8a-8c).

## Diagnosis

- `model_socket.py` calls `litellm.completion` for one Ollama `/api/chat` request; `litellm.completion_cost`
  runs only for cloud models, which are off. litellm is 109 MB of the venv, 4.4 s of import, +180 MB RSS, and
  fetches a price file from GitHub on import (D-M3), even with `--offline`.
- `engine/tools/hub.py` (ToolHub, the only mcp user) and `engine/governor/secrets.py` (SecretStore, the only
  keyring user) have no production caller; every role has `tools: []` and `Role.tools` is never read.
- `engine/memory.py` (`ContextStore`): the scheduler restores `session.context` on wake, but every caller
  overwrites `session.context["messages"]` before reading it, so the restore feeds nothing; each model call
  still writes the whole prompt to `agent_context`, which is never pruned and never read.
- The `review` tier (`config.py`) is used by no role; the CLI's `ask --tier` help still offers it.
- `tower._dev` is one 133-line method (ruff C901: 24) that owns F2 to F5, the gate, objection routing, CEO,
  retro, the release payload and send-back feedback. tower.py (481), cli.py (486) and devfloor.py (491) met the
  500-line rule by gluing constants to function ends and dropping blank lines.
- CI runs pytest only; there is no ruff configuration although the code carries `noqa` codes.
- README, CONTRIBUTING and the spec claim litellm retries/JSON/token counting, MCP tools, Keychain secrets, a
  review tier, a model review at every handoff, and Docker for agents.

## Changes

1. **Ollama client.** `engine/ollama_client.py`: `chat(**kw)` posts one non-streaming `/api/chat` request
   (`model` without the `ollama/` prefix, `messages`, `format: "json"` for JSON mode, `options.num_ctx` and
   `options.num_predict`, the call's timeout) to `Settings.ollama_url`, and returns the same response shape the
   socket already reads (`choices[0].message.content`, `usage.prompt_tokens/completion_tokens` from
   `prompt_eval_count`/`eval_count`). It refuses any URL whose host is not loopback. The socket's default
   completion is this client; a model without the `ollama/` prefix has no client and raises `CloudDisabled`
   unless a `completion_fn` is injected. `usd` is always 0. litellm leaves pyproject and uv.lock.
2. **Dead components out.** Delete `engine/tools/` (ToolHub), `engine/governor/secrets.py`, `engine/memory.py`
   and their tests and fixture; `Role.tools` and every `tools: []` line; the scheduler keeps slots and the
   `agent.wake`/`agent.idle` events but no context; `connect()` stops creating `agent_context` (an existing
   table is left alone: no data is dropped); the `review` tier goes. mcp and keyring leave pyproject and uv.lock.
3. **tower.py → package `watchtower/tower/`.** `errors.py` (NeedsOwner, SpecRejected, AppRejected),
   `spec_steps.py` (CPO questions, spec, approval, F1, reference context), `memos.py` (the agent door and memo
   routing), `signoff.py` (release text, sign-off request and release), `dev_run.py` (`DevRun`: one app job's
   F2→F5 state with one method per floor), `pipeline.py` (`TowerPipeline`, the steps, the plan and QA plan,
   retro). `_dev` becomes a short loop over `DevRun.attempt`. Re-exports for tests go: tests import from the
   owning module (E-T9).
4. **devfloor.py split.** `planner.py` (plan prompt, path rules, `units`), `writer.py` (`write_files`, the old
   `_write`), `checks.py` (`app_is_tested`, `is_test_file`), `build_loop.py` helpers for the round notes; the
   `DevFloor` class stays the facade with the same methods. Feedback re-exports go.
5. **cli.py split.** `interface/shell.py` (the Typer app, `clean`, `open_db`, exit codes), `interface/checks.py`
   (doctor checks), `interface/deploy_cmds.py` (deploy, rollback, undeploy, deployments),
   `interface/knowledge_cmds.py` (knowledge add/search, beacon). `watchtower.interface.cli:app` stays the entry.
6. **Lint in CI.** `[tool.ruff]`: src `F, E9, B, C901` (max complexity 15); tests `F, E9` without F403/F405
   (star-imported kits) and F811 (pytest fixture parameters). ruff is a dev dependency; CI runs
   `uv run ruff check` before pytest, on ubuntu (no test needs macOS since Keychain is gone).
7. **Structure test.** `tests/test_structure.py`: every src file under 500 lines, and every top-level def or
   class preceded by two blank lines (no squeezing), and the dead modules and deps stay gone.
8. **Docs.** README, CONTRIBUTING and spec: what is built and what is deferred (Tool Hub, Keychain secrets,
   long-term memory, review tier, dashboard/API, launchd, golden/load tests), litellm → direct client.

## Critique, counters, rulings

- *Keep litellm behind an optional `watchtower[cloud]` extra.* Nothing uses cloud models and the owner chose
  $0 local-only. Ruling: no extra; `completion_fn` stays the seam. Cost if wrong: about 40 lines to add an
  extra later.
- *Return a plain `(text, prompt_tokens, completion_tokens)` from the client instead of the OpenAI shape.*
  Cleaner, but about 30 test fakes build the OpenAI shape. Ruling: keep the shape. Cost if wrong: one fake
  helper to change later.
- *Allow a remote Ollama URL.* `ollama_url` is not configurable today. Ruling: loopback only, so a future
  setting cannot send prompts off the Mac. Cost if wrong: an owner with Ollama on another machine edits one set.
- *Drop the `agent_context` table from existing DBs.* Irreversible data loss for no gain. Ruling: new DBs do
  not create it; old ones keep it unread. Cost if wrong: a few MB stay on disk.
- *Remove `agent.wake`/`agent.idle` too.* They record slot use, not memory. Ruling: kept. Cost if wrong: two
  audit rows per call.
- *Replace langgraph (E-S3).* Not in this batch's decisions and the 8b progress table depends on it. Ruling:
  noted, deferred. Cost if wrong: about 1.1 s of CLI import stays.
- *Move `engine/runner.py` to the top level and the F2→F4 imports to a shared module (E-A1 items 9, 10).* Layer
  moves, not god-object splits. Ruling: deferred. Cost if wrong: two wrong-way import edges stay.
- *Max complexity 10.* 13 functions exceed it; most are small-model compensation that batch 4 does not own.
  Ruling: 15 now, which forces `_dev`, `_write`, `build` and `ask` down; lower later. Cost if wrong: complex
  functions under 15 stay unflagged.
- *Lint tests with B too.* 30 `zip` without `strict` in assertions. Ruling: F and E9 only for tests. Cost if
  wrong: a test bug B would catch.
- *Project and home CLAUDE.md (E-D3).* The owner's own files, outside the repo. Ruling: not touched; noted.
- Reviews: 2 rounds (not a security change; the URL guard is defence in depth).
- Deferred minors (review r1): a one-blank-line check between methods in class bodies, and ruff E501 at 120
  for every file instead of the hand-made `SPLIT` subset. Both widen a style rule beyond this batch's splits.

## Review Focus

1. The client: request body, JSON mode, limits, timeout, error classes still retried, loopback guard.
2. Nothing removed is still imported, configured, documented as built, or locked in uv.lock.
3. `DevRun` keeps every behaviour of `_dev`: order of floors, posts, saves, objection routing, resume state.
4. Split modules: no blank-line squeezing, no re-export left only for tests, entry point unchanged.
5. CI: ruff runs before pytest with the locked environment; the rules match the tests' idioms.

## Tasks (TDD: RED, watch fail, GREEN; one commit each)

1. Ollama client replaces litellm (client tests; guard mutation; remove litellm tests and dependency).
2. Remove ToolHub + mcp and `Role.tools`.
3. Remove SecretStore + keyring.
4. Remove the write-only memory (ContextStore, session context, `agent_context` for new DBs).
5. Remove the `review` tier.
6. Split tower.py into the `tower` package; `_dev` under complexity 15.
7. Split devfloor.py.
8. Split cli.py.
9. Ruff config, dev dependency, CI lint step; fix the violations.
10. Structure test (file length, blank lines, removed modules and deps).
11. Docs: README, CONTRIBUTING, spec deferred list.
12. Dead code sweep; record what was removed and the before/after test count here.

## Removed (task 12 log)

- Modules: `engine/tools/` (ToolHub), `engine/governor/secrets.py` (SecretStore), `engine/memory.py`
  (ContextStore), `tower.py` (now the `tower/` package). Dependencies: litellm, mcp, keyring (and their locked
  transitive packages). Config: the `review` tier, `Role.tools` and every `tools: []` line.
- Dead code found by the sweep (no production caller): `Budget.charge` (production records, then `check`s; the
  `before_call` switch went with it), `WorkPackage.from_dict`, and the `tower` package's unused re-exports
  (`AppRejected`, `spec_text`).
- Tests removed with the code they tested (28 functions): `test_tool_hub.py` (10, with the `echo_mcp_server`
  fixture), `test_secrets.py` (5), `test_memory.py` (5), the scheduler's context save/restore tests (4), the
  runner's context-restore test (1), the litellm banner and error-classification tests (2), and
  `test_package_round_trip` (1).
  `test_charge_within_limits` became `test_record_within_limits`; the cap tests now `record` then `check`.
- Added: `test_ollama_client.py`, `test_structure.py` (file length and blank lines per src file, removed modules
  and deps, ruff in CI and clean, docs claims).
- Count: 1259 passed on main before 8d; 1336 passed after (`uv run pytest -q`). The rise is the per-file
  structure checks; 28 tests of removed code are gone.

## Review r1

- Important: the client honoured `HTTP_PROXY`/`ALL_PROXY` and the macOS system proxy (httpx `trust_env=True`),
  so a prompt for 127.0.0.1 could go to a proxy host. Every Ollama call now builds its client with
  `trust_env=False`, and doctor's `ollama_status` goes through the same client (and its loopback guard).
  Tests: a proxy in the environment, and the request must use the direct transport (chat, resident, unload,
  doctor); mutation (guard removed) fails both.
- Minor, fixed: a test drives `ModelSocket` with no `completion_fn` into the real client over a mock transport
  and checks num_ctx, num_predict, JSON format, URL and timeout (mutation: a renamed kwarg fails it).
- Minor, fixed: test files are held under 500 lines too; `test_qafloor.py` (511) split, its live-app escaping
  tests now in `test_qafloor_live.py` (49 tests before and after).
- Minor, fixed: `click>=8` declared (E-D1), lock updated.
