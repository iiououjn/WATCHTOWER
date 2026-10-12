# Phase 6b — Floor 5 Oversight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Floor 5 becomes a full office: Oversight Lead sets the audit focus, workers run a security scan (Bandit + secret patterns) and a spec audit, the F5 gate (HR) gives the final verdict; every app job ends with a retrospective stored as lessons for later jobs, and an owner sign-off before a release exists.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` (F5 row; lifecycle `final_audit → owner_signoff → done`).

## Global Constraints
- $0 local. Bandit is a static scanner (reads code, never runs it); runs on the host with a timeout. Missing Bandit → open question, not a crash.
- All model-derived text crossing agents is `untrusted(...)`/`untrusted_code(...)`.
- Advisory roles (lead focus, auditor, retrospective) use ADVISORY_ERRORS: skip, never pause.
- Files < 500 lines; tests first; two review rounds; no Co-Authored-By trailer.

## Rulings
1. Semgrep/gitleaks/pip-audit/npm audit dropped: apps are stdlib-only (nothing to audit), Semgrep fetches rules online, gitleaks is another binary; Bandit + the Beacon's SECRET patterns cover the same risks offline.
2. Security HIGH/MEDIUM (confidence ≥ MEDIUM) fails the build and goes to the coder; LOW is a note.
3. The existing F5 gate is the office's HR (final verdict) — no second verdict model.
4. `--yes` auto-approves the sign-off as it does the spec.
5. Lessons are stored untrusted (they are derived from model work) and reach only the architect, wrapped.

## Review Focus
1. Hostile code making Bandit hang/crash or forging its JSON output.
2. Secrets in any workspace file (not only .py).
3. Sign-off resume paths: approve, reject, pending, re-run after resume; release only after sign-off.
4. Retro lessons as an injection channel into later jobs.
5. Security failure loop never ending (bounded by send-backs).

### Task 1: `oversight.py` security scan
`security_scan(root, files, run=subprocess.run) -> list[dict]` ({tool, id, severity, line, file, text}); Bandit on the .py files (`python -m bandit -q -f json <files>`, timeout 60, results parsed defensively), SECRET regex on every file. `security_package(findings) -> WorkPackage("f5", ..., checks=[{"check":"security","pass":bool,"findings":[...]}])`.

### Task 2: Oversight office in the dev loop
`OversightOffice(lead, auditor, ask)`: `focus(spec) -> list[str]` (≤3), `audit(spec, focus, code, evidence) -> str` (per-focus ok/note summary). In `_dev` after QA passes: security package (last check), audit summary appended for the gate; security failure → coder feedback with findings (untrusted). Roles `f5.lead`, `f5.auditor` (small tier).

### Task 3: Retrospective + lessons
`OversightOffice.retro(spec, notes) -> list[str]` (≤3 lessons ≤200 chars). Written when the app passes and before NeedsOwner after the last send-back. Stored via `Knowledge.add(..., source=f"watchtower://retro/{job}", trusted=False)`. Architect plan prompt gets past lessons (search filtered to retro sources, wrapped `untrusted("retro", ...)`).

### Task 4: Owner sign-off + CLI
App steps: `..., dev, signoff_request, signoff`. Release recorded only on sign-off approval. CLI `approve` handles kind `signoff` (reject → failed "app rejected by owner"); `_report` shows what is awaiting approval; `doctor` checks Bandit.

### Task 5: Real run + two review rounds.
