# Phase 6c-3 — Every Floor an Office, Glass 2–5, Beacon for Every Floor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Finish the realign from the 2026-10-12 alignment audit. F2 and F3 get the Floor 1 office pattern (Lead splits → N Workers → HR). F3 really goes MVP → full app. Glass 2–5 exist with their own rules, every floor can ask the Beacon through its own glass, and the glass pipeline gains its two missing steps (source credibility, consistency).

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §1 (floors, glass per floor), §5 (Lead → Workers → HR per floor; F2/F3 rows), §7 (Beacon, glass pipeline steps 1–5, per-floor rules).

**Split:** two sub-phases, each with its own two review rounds and merge: **6c-3a Offices** (Tasks 1–2), **6c-3b Glass + Beacon** (Tasks 3–5). Smaller diffs get sharper reviews.

## Global Constraints
- $0 local; 8 GB; one model in RAM. Every added model call costs time and heat on the owner's Mac. Prefer deterministic workers, and keep each new model call bounded and advisory.
- Files < 500 lines (`tower.py` is 406: new logic goes in floor modules and `beacon/lookout.py`).
- Model-derived and web text crossing agents is wrapped (`untrusted` / `untrusted_code`); advisory roles never pause a job.
- Web queries never carry code, file paths or secrets (spec §5 free-tier privacy rule).
- Tests first; two review rounds per sub-phase; no Co-Authored-By trailer.
- Real-model run only after the owner says OK (heat); suggest Docker Desktop memory 2 GB first.

## Critique of the first idea, and the counters (why the plan looks like this)
1. **"N workers on every floor" = N more model calls on an 8 GB fan-limited Mac.** Counter: the split is deterministic where a machine does it as well (F2 unit split from the architect's file plan; F3 route probes), so the new workers cost no extra model calls. The architect is already F2's Lead, so no extra Lead call either.
2. **F4 and F5 already are offices** (QA Lead → QA workers per area → QA HR; Oversight Lead → security scan + spec auditor → F5 gate). Adding more workers there would be decoration. Counter: leave them, and give them Beacon access through Glass 4/5 instead, which is what they lack.
3. **"MVP → full app" as two complete builds** would double the coder loop (the slowest, hottest part). Counter: MVP-first *order* plus staged *verification*. Unit 1 is always the entry file + its tests (the MVP). F3 checks the MVP first (GET / answers 200) and only then the full app (every GET route in the contract answers without 404/5xx). A failed MVP stops before the full probe and goes to the coder with the crash diagnosis.
4. **Model swaps heat the Mac** (coder 7B ↔ llama 3B). Counter: F2 workers run back-to-back on the coder model; nothing else runs between units.
5. **Beacon lookups from every floor make every job slow and online.** Counter: floors 2–5 ask the Beacon only when the owner passes `--research` (the existing opt-in), each at most twice per job, and a lookup is advisory (no result = carry on).
6. **Cross-floor cache leak:** today `Beacon.research` reuses any page already in Knowledge without re-judging it. A page Glass 1 accepted would then reach Floor 2 through Glass 2 unchecked. Counter: a cached page is reused only if the asking floor's glass allows its domain; context is always filtered by the asking floor's glass.
7. **Consistency check (glass step 5) as a model call on every page** costs a call per page. Counter: at most one check per task, only when Knowledge already holds a page on the same task from another domain. A contradiction becomes a note in the floor's context ("sources disagree: …"), never a reject, because Knowledge is never proof (spec §7).
8. **Credibility scoring by a model** would be guesswork from a 3B. Counter: deterministic domain tiers from the glass rules file (high / normal / low). Low is rejected; high is ranked first in context and marked.

## Rulings
1. F2 Lead = the Architect (plans files + routes, CTO approves). The unit split is deterministic: unit 1 = entry + test files, then the remaining planned files in groups of ≤3, at most 4 units, in plan order.
2. F2 workers = the Coder role, one call per unit, writing only that unit's files (other paths are refused with a note). Units run only when planned files are missing (first build, or after a re-plan). Then the existing test-and-fix loop runs unchanged. F2 HR keeps reviewing the integrated, passing code (one review, not per unit: a unit cannot be tested alone).
3. F3 workers = deterministic route probes (one sandbox run probes up to 8 GET routes). F3 Lead keeps the home-page expectation; F3 HR diagnoses MVP crashes and probe failures.
4. Glass 2 (Dev) passes only technical docs and API references; Glass 3 (Build) docs + Q&A for crash causes; Glass 4 (QA) HTTP references; Glass 5 (Oversight) security references. All four are allow-lists; Glass 1 stays open web with a deny list.
5. Lookout queries are built by code, not by models: F2 = "python standard library " + spec title; F3 = the exception line of a crash; F4 = the failing HTTP status text; F5 = "bandit <test id>". Each is scrubbed (SECRET patterns, paths, quotes) and capped at 120 characters.

## Review Focus
1. A page accepted through one glass reaching another floor whose glass would reject it (cache reuse, context filtering).
2. Lookout queries leaking code, paths or secrets from crash logs and Bandit findings.
3. Unit writing: a coder unit reply writing outside its unit, deleting files, or garbage JSON (costs the unit, never the job).
4. Route probes: hostile route paths from the architect (`//evil.com`, `..`, spaces, very long), apps that hang, redirect, or answer 404 for real routes.
5. Advisory everywhere: search down, glass model garbage, low memory → no pause, no failed job.

---

## 6c-3a — Offices

### Task 1: F2 coder workers (units)
**Files:** `floors/f2_dev/devfloor.py` (new `units(plan) -> list[list[dict]]`, `UNIT_PROMPT`, `DevFloor.write_units(spec, plan, on_unit)`), `tower.py` `_dev` (call `write_units` before `build` when planned files are missing; board note per unit), tests in `tests/test_devfloor.py`, `tests/test_runner.py`.
- `units(plan)`: entry + every planned `test*.py` first, then the remaining planned files in groups of ≤3; ≤4 units; a file appears once.
- `write_units`: per unit one coder call with the spec, the plan (wrapped), the unit's files and purposes, and a snapshot of what earlier units wrote. Only the unit's paths are written; others → note. `BadModelOutput` → the unit is skipped (the fix loop writes it later). Returns the notes.
- Tests: split order and caps; a reply writing outside the unit is refused; garbage reply skips one unit; the build after units starts with the files present; units are not rerun on a code send-back (files exist), rerun after a re-plan that adds files; one board note per unit.

### Task 2: F3 MVP → full app (route probes)
**Files:** `floors/f3_build/buildfloor.py` (`PROBE_SCRIPT`, `route_probe(run, entry, routes) -> WorkPackage`), `tower.py` `_dev` (probe after a passing smoke test; F3 handoff passes only if both pass; probe failure → coder feedback + F3 HR diagnosis), `tests/conftest.py` FakeSandbox probe support, tests.
- Probe: GET routes from the contract only, path must match `^/[A-Za-z0-9._~/-]{0,80}$` and must not contain `//` or `..`; ≤8 routes; 1 s timeout each; status ≥ 500, 404 or no answer = fail. Output parsed from a `PROBE_RESULT {json}` line (the app's own prints can't forge it: parse the last such line written by the script after the app is killed).
- Tests: all good → pass; 500 on one route → fail with that route named; hostile paths dropped; an app that never answers → fail, no hang; MVP failure skips the probe.

## 6c-3b — Glass 2–5 + Beacon for every floor

### Task 3: Glass rules f2–f5, credibility tiers
**Files:** `beacon/glass_rules/f2.yaml … f5.yaml`, `beacon/glass.py` (`GlassRules.credible_domains`, `low_credibility_domains`; `Glass.credibility(url) -> int` 2/1/0; `inspect` rejects 0), roles `roles/glass/f2.yaml … f5.yaml` (relevance prompt per floor), F1 `_context` ranks high-credibility hits first and marks them.
- Tests: each floor's allow list; low-credibility domain rejected with reason; `.gov`/`.edu` and listed docs rank high; old rules files without the new keys still load.

### Task 4: Lookout — floors ask the Beacon through their glass
**Files:** `beacon/lookout.py` (`Lookout(beacon_factory, knowledge, audit).ask(floor, query, job_id, ask_glass) -> str`, `scrub_query(text) -> str`), `beacon/beacon.py` (cached page reused only if this glass allows its domain), `engine/runner.py` (`beacon_factory(ask, floor)`), `tower.py` (F2 before planning, F3 on crash/probe failure into HR diagnosis, F4 on QA failure, F5 on security failure; each ≤2 per job, only with `--research`, advisory).
- Tests: no `--research` → no lookup; cache reuse refused across glasses; context filtered by the asking floor's glass; query scrubbing (secrets, `/Users/...` paths, file names, long text); search down / glass garbage / low memory → empty, job continues; lookup text reaches the right prompt wrapped `untrusted(...)`.

### Task 5: Consistency check (glass step 5) + spec text
**Files:** `beacon/glass.py` (`CONSISTENCY_PROMPT`, `Glass.consistent(text, other) -> str` note or ""), `beacon/beacon.py` (one check per task when Knowledge holds a same-task page from another domain), `tower.py` F1 context adds "sources disagree: …" wrapped; spec §5 rows F2/F3, §7 glass steps and per-floor rules.
- Tests: contradiction → note in context, page still accepted; no other page → no model call; garbage → no note.

### Task 6: Real run (owner OK first) + two review rounds per sub-phase.
