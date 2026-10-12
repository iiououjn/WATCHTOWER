# Phase 6a — Office on Every Floor, Tower Board, Memos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Every floor works like an office (Lead → Workers → HR), every agent sees a short tower brief (what is done, what is happening on its floor, what is coming), and leads/coder can send bounded memos to other floors. QA writes its checks before coding from an architect routes contract (test-first across floors).

**Architecture:** `board.py` stores notes as bus events and renders a deterministic ≤600-char brief. `TowerPipeline._call` is the single choke point for every agent call: it appends the brief (untrusted) and routes memos to the target floor's lead (answers posted to the board). `office.py` holds the F4 QA office (lead → workers → HR) and the F3 office (lead expectation, HR diagnosis). DevFloor gets an F2 HR review after tests pass. Optional roles degrade gracefully (skip + note), never pause a job.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` (floors staffed like an office; F5 cross-checks; owner 2026-10-12: "5 floors fully criss-cross agentic, everyone knows what's happening and what's coming").

## Global Constraints
- $0, local Ollama only; one model in RAM; num_ctx 6144 — brief ≤600 chars.
- All model-derived text crossing to another agent is `untrusted(...)`-wrapped; memo answers cannot send memos.
- Memo caps: 3 per sending floor per job; only Leads, Architect and Coder may send; target ≠ sender floor.
- Files < 500 lines; tests first; no Co-Authored-By trailer.
- Tower job budget 300k tokens.

## Rulings
1. Free agent chat (option D) stays off — 3B drift, injection spread. Memos are structured and capped.
2. F3 Lead's home-page expectation is a soft check (open question for the gate), not a hard fail — a wrong 3B guess must not block a working app.
3. Optional roles (F2 HR, F3 Lead/HR) skip on BadModelOutput; QA office falls back to the single QA writer after code exists.

## Review Focus
1. Memo loops / cap bypass (answer containing a memo, sender floor = target, unknown floor).
2. Injection via board notes or memo text reaching other agents unwrapped.
3. Brief overflowing context (many notes, long text).
4. Routes contract with hostile paths reaching QA/coder unvalidated.
5. HR rejecting forever (round budget) or crashing the job.

### Task 1: Board
- Create `src/watchtower/engine/board.py`: `Board(bus).note(job_id, floor, kind, text)`, `.notes(job_id)`, `.brief(job_id, floor, max_chars=600) -> str` ("" when no notes). Text control-char stripped, ≤300 chars. Sections: Done (latest note per other floor), On this floor (last 2), Coming next (fixed floor order text + QA plan names), Memo answers (last 2).
- Tests: `tests/test_board.py`.

### Task 2: `_call` choke point + memos
- `TowerPipeline._call(role, data, prompt)`: brief appended as `untrusted("board", brief)` when non-empty; reply `memo` handled per constraints; answer by target lead via raw ask with MEMO_PROMPT; note kind `memo`. All pipeline asks use `_call`.
- Role prompts of leads/architect/coder mention the memo option.
- Tests in `tests/test_runner.py` + `tests/test_memos.py`.

### Task 3: Routes contract + test-first QA office
- Architect plan adds `routes` (validated: method GET/POST, path like QA paths, ≤6 field names, shows ≤100 chars, cap 8).
- `office.QAOffice(lead, worker, hr, ask).plan_checks(spec, routes) -> list[dict]`: lead splits acceptance into ≤3 areas, worker writes checks per area (`parse_checks`), HR drops named checks; trivial GET checks without expect_text dropped; cap 8.
- `_dev`: checks written right after each plan, shown to the coder (untrusted), board note `qa.plan`; run after smoke; fallback to `QAFloor.write_checks` if empty.
- New roles `f4.lead`, `f4.hr` (small tier).

### Task 4: F2 HR + F3 office
- DevFloor optional `hr` role: after tests pass, review vs spec/plan/routes; reject → coder note, continue rounds; last round → open question; BadModelOutput → skip.
- `office.F3Office(lead, hr, ask)`: `expect(spec, routes) -> str` (soft text for GET /), `diagnose(log) -> str` on smoke failure (fed to coder). Smoke script reports whether body contains the expectation.
- New roles `f2.hr`, `f3.lead`, `f3.hr` (small tier).

### Task 5: Budget + real run + reviews
- `tower_max_tokens` 300k. Real `build --app` run on the Mac. Fresh review → fix → second fresh review (owner asked for two rounds).
