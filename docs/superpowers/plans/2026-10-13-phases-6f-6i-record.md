# Phases 6f, 6g, 6h, 6i — record (written after the fact)

These four phases were each a quick follow-up to one failed real run. Each one had a ledger in
`.superpowers/sdd/p6f…p6i/progress.md`, test-first fixes, two review rounds (6g had three), and a merge with a tag.
They had **no plan file here**: that was a gap, because `.superpowers/` is git-ignored, so the repo held no record of
them except commits. This file is that record, copied from the ledgers.

| Phase | Tag | Came from | Problem | Fix |
|---|---|---|---|---|
| 6f | v0.9.7-phase-6f | run 4 (2783226225d8) | tests passed, but a syntax error in `__main__.py` stayed for 12+ rounds; the note naming it could be trimmed away and showed no code | `_problem_note`: says "this is the only thing left" (only when the full test bar is met), shows the error line with code around it, the newest note is never trimmed, every note is bounded |
| 6g | v0.9.8-phase-6g | run 5 (2958e367a382) | F2 and F3 passed; F4 failed 4 times on one check expecting a description ("The homepage with an empty input field…") | descriptions dropped only from checks written from code (unless the code contains them); empty / status-only / title-only suites never pass; the QA HR recheck/relax path was removed (it let a 3B judgement pass broken apps) |
| 6h | v0.9.9-phase-6h | run 6 (01e3c1d90608) | an f-string split by a real newline (JSON escaping slip); pytest-style tests ran 0 tests | `repair_strings`: rejoins a one-line string split by a lost line break, only when safe (fuzzed); the test runner also runs pytest-style `def test_x(): assert …` |
| 6i | v0.9.10-phase-6i | run 7 (0fec67155df8) | JSON escaping broke code both ways; files never parsed. Root cause of runs 4, 6, 7: code inside JSON strings | the coder replies in plain file blocks (`### FILE: path` + fence), with a JSON fallback, one retry, then a clean failure; `### DELETE:` and `### MEMO fN:` lines |

## Reviews (from the ledgers)
- **6f:** round 1 found 0 Critical, 3 Important, 3 Minor; round 2 found 0 Critical, 1 Important, 6 Minor. All Important fixed; suite 779.
- **6g:** round 1 found 1 Critical, 4 Important; round 2 found 3 Critical, 3 Important; round 3 (to verify the redesign) found 2 Critical, 2 Important. All fixed; suite 808. Ruling: a bad, non-descriptive check that keeps failing uses up the send-backs and the owner decides.
- **6h:** round 1 found 0 Critical, 5 Important; round 2 found 0 Critical, 3 Important (fuzzed: 0 wrong repairs). All fixed; suite 824.
- **6i:** round 1 found 0 Critical, 5 Important; round 2 found 0 Critical, 3 Important. All fixed; suite 854. Ruling: a literal `### FILE: x.py` + fence pair inside a code body starts a new file.

## Deferred minors
- **6f:** problem lines (with file names the coder chose) are not wrapped.
- **6g:** a renamed duplicate check "x #2" could collide with a check literally named "x #2"; the description exemption is case-blind while the runner is case-sensitive.
- **6h:** "long / message" written as two joined strings becomes one string with `\n`; 3.12 nested-quote f-strings are not repaired; no-argument `test_*` helpers run as empty tests; a forged result line plus `os._exit` (older issue).
- **6i:** a header with no path loses that block silently; the `bad_files` audit event has no detail.

## After these
6j (`2026-10-13-phase-6j-unstuck-coder.md`) came from run 8, the first run on file blocks.
