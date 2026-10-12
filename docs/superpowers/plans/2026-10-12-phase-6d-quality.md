# Phase 6d — Quality: 7B default, real specs, real tests, XSS probe

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Close the three quality gaps the first real 7B run exposed (2026-10-12), and make the 7B coder the default: the CPO writes specs QA can test, F2's unit-test bar means something, and F5 catches HTML injection that Bandit cannot see.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §4 (tiers), §5 (CPO, F2/F4/F5 rows), §9 (security).

**Evidence (real run, job e0051fbc7bd5):** spec had 1 acceptance criterion; QA ran 1 check; F2 passed with one trivial test of a helper; `/list` wrote stored items into HTML with no escaping (safe only because the form data was never URL-decoded); Bandit + secrets scan passed.

## Global Constraints
- $0 local; 8 GB. New checks are deterministic (no extra model calls) except one bounded CPO re-ask.
- Files < 500 lines; tests first; two review rounds; no Co-Authored-By trailer.
- Model-derived text crossing agents is wrapped; advisory roles never pause a job.

## Critique of the first idea, and the counters
1. **"CPO must write ≥3 criteria"** — a 3B forced to pad writes filler ("app is good"). Counter: one re-ask with a concrete note only when there are fewer than 3; if still short, add tower defaults that QA can really check (home page shows the title; what a user adds appears on the list), marked `(tower default)` so the owner sees which ones the tower added. Never more than one extra call.
2. **Static XSS check (AST "writes variables into text/html without html.escape")** — false positives on numbers and false negatives on templates. Counter: a **dynamic probe** in the sandbox, no model: POST a marker `<i>wt-probe-N</i>` into every form field of every POST route in the contract, then GET every GET route; a page that returns the raw marker is a HIGH finding (reflected or stored HTML injection). It catches exactly what matters, with no false positives (the raw tag in the response is the proof).
3. **"Require more tests"** — a count alone is gamed by trivial asserts. Counter: real tests run ≥ 2 **and** at least one test file imports from an app module (not only `unittest`). Cheap, deterministic, and it rules out the run's empty test file case. F2 HR still judges substance.
4. **7B default heats the Mac** — mitigated by `make_room` (merged); the 3B stays one env var away (`WATCHTOWER_WORK_MODEL=qwen2.5-coder:3b`). `doctor` already reports a missing tier model.
5. **The XSS probe adds a sandbox run** — only when the contract has POST routes with fields; one run of ≤ 8 posts + ≤ 8 gets.

## Rulings
1. Probe findings join the security findings as `{"tool": "probe", "id": "XSS", "severity": "HIGH", "confidence": "HIGH"}` so `security_fail_on`, evidence and the coder feedback treat them like any HIGH finding; the coder gets the route and field, never the app's whole body.
2. Tower-default criteria are only added for app jobs (pipeline `app`); research briefs keep the CPO's own list (re-ask still applies).

## Review Focus
1. Probe forgery (app printing a fake result line), hanging apps, redirects after POST (303 → GET), apps that escape correctly (`&lt;i&gt;`) must pass.
2. CPO re-ask: garbage reply, duplicate criteria, criteria over 200 chars, prompt injection via the owner's idea text.
3. Test bar: `from app import *`, `import app`, tests in a folder, test files that import only `unittest`.
4. Old checkpoints / resume after the CPO change; old specs with 1 criterion resumed mid-dev.
5. Default model change: tests and README/spec text that still say 3B.

### Task 1: 7B default
`config.py` work tier → `ollama/qwen2.5-coder:7b`; README + spec tier text; tests updated.

### Task 2: CPO ≥ 3 testable criteria
`tower.py` `_spec`: < 3 → one re-ask (`SPEC_MORE_PROMPT`, the current spec wrapped); still < 3 on an app job → tower defaults; dedupe; cap 6.

### Task 3: F2 test bar
`devfloor.py`: `passed` also needs `real >= 2` and a test file that imports an app module (AST, not regex); notes tell the coder exactly what is missing.

### Task 4: F5 XSS probe
`floors/f5_oversight/probe.py`: `PROBE_SCRIPT`, `xss_probe(run, entry, routes) -> list[dict]` (findings); `tower.py`: after the security scan, add probe findings before `security_package`.

### Task 5: two review rounds, then a real run only with the owner's OK.
