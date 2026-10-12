# Phase 6c-2 — Guardrails, Gate per Handoff, CTO/CEO, `run` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Close the spec gaps found in the 2026-10-12 alignment audit: an owner-editable `guardrails.yaml` that F5 enforces, an F5 gate at every floor handoff, the missing C-suite (CTO approves the tech plan, CEO gives the final recommendation before the owner), `watchtower run "<idea>"` running the full tower, and spec text that matches what was built.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (C-suite, gate), §6 (guardrails), §8 (CLI), success criteria 1–2.

## Global Constraints
- $0 local; 8 GB; one model in RAM. Deterministic checks before model checks (spec §2).
- Files < 500 lines (tower.py is 366: C-suite logic goes to `src/watchtower/csuite/`).
- Model-derived text crossing agents is wrapped; advisory roles never pause a job.
- Tests first; two review rounds; no Co-Authored-By trailer.

## Rulings
1. Gates per handoff: F2→F3, F3→F4, F4→F5 are deterministic F5 gates (the floor's own reality checks, recorded as `gate.verdict` events and board notes); the cross-family model gate runs once at the end over everything. A model gate at every handoff would triple model calls on 8 GB for checks a machine already does better.
2. CTO reviews the architect's plan once per plan (approve or list changes → one re-plan). CEO reviews the finished job and gives the owner a recommendation; a CEO "reject" stops `--yes` auto sign-off (the owner must look).
3. `run` = full app tower; `research` = Floor 1 brief only (old `build` without `--app`); `ask` = the quick single-model demo (old `run`). `build` is removed.
4. `guardrails.yaml` ships in the package; an owner copy at `$WATCHTOWER_HOME/guardrails.yaml` overrides it. Invalid file → clear error, `doctor` reports it.
5. Coder model is configurable (`WATCHTOWER_WORK_MODEL`); default decided after the real 7B run.

## Review Focus
1. Malformed / hostile guardrails file (types, unknown keys, huge values).
2. CTO/CEO garbage or loops (bounded re-plan, advisory).
3. CEO reject with `--yes` really pauses; resume path after owner approves.
4. CLI rename leaves no dead path (`approve` → resume of an app job, `research`, `ask`).
5. Gate events per floor recorded exactly once per attempt.

### Task 1: guardrails.yaml + loader + doctor + work-model env
`src/watchtower/guardrails.yaml`; `src/watchtower/guardrails.py`: `Guardrails` dataclass (`stdlib_only: bool`, `security_fail_on: tuple[str,...]` ⊆ {HIGH, MEDIUM, LOW}, `min_source_domains: int` 0–5, `max_send_backs: int` 1–5, `rules: tuple[str,...]` ≤ 12 lines ≤ 200 chars) + `load_guardrails(home) -> Guardrails`. Wired: F1 min_domains, security fail-on, send-back limit, stdlib check toggle, rule text in every gate prompt.

### Task 2: Gate at every handoff
In `_dev`: after each floor package, `self._gate_event(data, floor, package)` publishes `gate.verdict` {floor, attempt, passed, reasons} and a board note; the final model gate stays.

### Task 3: CTO
`csuite/cto.py` `CTO(role, ask).review(spec, plan, guardrails) -> (approved, changes)`; role `roles/csuite/cto.yaml` (small tier, other family than architect). `_dev`: after each plan, CTO review; not approved → one re-plan with the changes as feedback.

### Task 4: CEO
`csuite/ceo.py` `CEO(role, ask).recommend(spec, evidence, audit) -> (approve, note)`; role `roles/csuite/ceo.yaml`. Before sign-off: recommendation added to the sign-off summary; reject + `--yes` → sign-off is requested from the owner anyway.

### Task 5: CLI `run` / `research` / `ask` + spec text
Rename commands; update tests; spec §6 (Aider → own coder loop), F5 row (Bandit + secret patterns), §7 (DuckDuckGo search; SearXNG optional), §8 CLI list.

### Task 6: Real run (7B coder) + two review rounds.
