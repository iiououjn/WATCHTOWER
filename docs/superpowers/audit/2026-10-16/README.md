# Full audit — 2026-10-16 (after phase 7d, runs 36-39)

Five independent opus reviewers, one area each, read every line in their area and ran probe scripts against
tower code (never AI-written app code on the host). Baseline: `uv run pytest -q` → 1097 passed. Full
reports, with file:line, scenario, severity and fix for every finding:

| report | area | findings |
|---|---|---|
| [A-engine.md](A-engine.md) | engine, governor, model socket, workflow, config, roles | 3 High, 8 Medium, 13 Low |
| [B-pipeline.md](B-pipeline.md) | tower.py, evidence, gate, F1/F3/F4/F5 floors | 1 High, 7 Medium, 12 Low |
| [C-devfloor.md](C-devfloor.md) | F2 dev floor, skeleton, repair, lint | 2 High, 7 Medium, 15 Low |
| [D-security.md](D-security.md) | sandbox, deploy, beacon, CLI, secrets, supply chain | 1 High, 7 Medium, 12 Low, 1 Info |
| [E-tests-stack-arch.md](E-tests-stack-arch.md) | tests (52 mutations), dependencies, architecture, docs | 5 High, 11 Medium, 11 Low |

Spot-verified by the lead before merging: unit order (devfloor.py:195-204), the host "Run it" line
(tower.py:228), QA ignoring the harness exit code (qafloor.py:336). Bandit's B608/B108 flags: false positives
(two reviewers, probed).

## Merged ranking (duplicates folded; sources in brackets)

### High — security
1. **Sandbox results are forgeable.** The app under test runs in the same container and uid as the QA, XSS-probe
   and smoke harnesses; it can write a fake result line to the harness's stdout and kill it. Exit codes are
   ignored; smoke takes the first match. [B-H1, D-M4, E-A6, E-T2] Fix: exit 0 + exactly one result line
   everywhere (now); checker in its own uid/container (structural).
2. **The release tells the owner to run AI-written code on the host** (`cd … && python app.py`), even for
   `--yes` jobs nobody read. [D-H1] Fix: drop the line; `watchtower deploy` only.
3. **`--yes` releases with no human sign-off** unless the CEO model objects; `deploy` never checks that a person
   approved. Weak evidence (status-only checks, a scanner that did not run) auto-releases unseen. [D-M1, B-M1]
   Fix: `--yes` covers the spec only; release and deploy always need a human approval record.

### High — reliability
4. **A killed run is stuck `running` forever**; resume refuses without `--force` though the job lock is free
   (run 38: likely an OOM kill at 9% free RAM). [A-F1]
5. **All of F2→F5 (up to 4 attempts) is one checkpoint**: a crash loses every attempt (run 38: ~14 min), pause
   cannot act during dev, resume re-plans and resets the send-back counter. Contradicts spec §4. [A-F2, B-M6, E-A2]
6. **No retry/backoff on transient model errors**; one Ollama reset pauses the job and, with 5, discards dev
   work. Spec §10. [A-F3]

### High — correctness and quality
7. **Skeleton writes test_store.py before store.py**; the store copies the tests' names (root cause of run 38;
   7d only catches it later). [C-H1]
8. **The tower's own hints produce code its own checks reject** (`from app import`, `store._entries.clear()`,
   auto-added `import os`). The loop pattern again, inside the tower. [C-H2]
9. **The 7c store-safety tests are vacuous since 7d** — every bad snippet also fails the contract check; allowing
   getattr/os/`__class__` survives all 1097 tests. [E-T1]

### High — stack and architecture (owner decisions)
10. **litellm**: 109 MB of a 322 MB venv, 4.4 s import, +180 MB RAM, for one Ollama call; also fetches a price
    file from GitHub on every run, even `--offline`. [E-S1, D-M3] Options: replace with ~40 lines of httpx, or
    keep and set `LITELLM_LOCAL_MODEL_COST_MAP=True`.
11. **Dead spec components**: mcp + keyring ship only for ToolHub/SecretStore, which nothing calls; memory is
    write-only; the `review` tier is unused. [E-S2, E-A3, A-F19] Options: wire them or remove them.
12. **God objects**: `tower._dev` (133 lines, complexity 19), tower.py 455, cli.py 485, devfloor.py 499 — the
    500-line rule met by deleting blank lines. Splits are listed in B, C and E. [E-A1, C, B]

### Medium (grouped)
- Security: sandbox output buffered unbounded on the host (400 MB → 888 MB RSS) [D-M2]; terminal escapes via
  `watchtower status` [D-M5]; Glass regex bypassed, poisoned pages reused across jobs [D-M6]; `python:latest`
  unpinned, Docker Desktop shares /Users [D-M7, E-S7]; files starting with the tower mark hidden from every
  reviewer [B-M2].
- Reliability: per-call timeout = whole remaining job time; failed calls never charged [A-F4, F5]; budget
  overshoot discards a good reply [A-F8]; any unexpected exception = permanent fail [A-F9]; concurrent jobs
  silently skip advisory roles [A-F10]; cleanup errors mask the real error [A-F11].
- Correctness: `parse_files` turns trailing prose fences into SyntaxErrors [A-F6]; untagged model names reload
  every call [A-F7]; stale tower server survives a resume [B-M3]; a lone objection never escalates when all
  model checks passed [B-M4]; send-back feedback wrapped twice [B-M7]; store check false positives with no fix
  hint [C-M1]; HR reviews code it cannot see [C-M2]; `App.py` endless loop on case-blind disks [C-M3]; stdlib
  list 3.12 vs sandbox 3.14 [C-M4]; prompts exceed budget (14.6k vs 9k) [C-M5]; PASS/FAIL mismatch after a
  garbled reply [C-M6]; old entry file survives a rename [C-M7].
- Tests/stack: no golden end-to-end test [E-T5]; ~17 s of the suite on dead code [E-T6]; Python not pinned (a
  fresh uv picked 3.13) [E-S5]; CI runs pytest only [E-S6]; langgraph used as a for-loop [E-S3]; audit hash chain
  is not tamper-evident [A-F21, D, E-A5]; docs/CLAUDE.md inaccuracies [E].

### Low
~50 items across the five reports (server slowloris/thread growth, `&amp;`→`&` accepted ruling, port races,
weak asserts, naming, validation gaps). See each report's Low section.

## Proposed fix batches (tests first; review rounds per the workflow)

| batch | items | reviews |
|---|---|---|
| 1 security | 1, 2, 3, sandbox output cap, terminal escapes, tower-mark hiding, pin image + Python, litellm offline env | 3 |
| 2 reliability | 4, 5, 6, timeouts/charging, budget overshoot, unexpected-exception resume | 2 |
| 3 skeleton correctness | 7, 8, 9, store-check false positives, 3.14 stdlib, prompt budgets, parse_files | 2 |
| 4 structure and stack | 10, 11, 12 (owner decisions first), CI lint, docs, dead code | 2 |

Then the dashboard (spec Phase 7). Until batch 1 lands: never run a released app with `python app.py`; use
`watchtower deploy <job>`, and do not use `--yes` for jobs you will not read.
