# Audit C — Floor 2 (src/watchtower/floors/f2_dev/)

Scope: devfloor.py (499), skeleton.py (283), repair.py (373), lint.py (248), feedback.py (124), handoff.py (49),
stdlib_check.py (34). Every line read. Baseline: `uv run pytest -q` → `1097 passed in 67.79s`.
Probes (tower code only, plus fixture store.py I wrote): `/private/tmp/claude-501/-Users-rishi-Desktop-Watch-tower/b28739af-e7a5-42d2-a1ca-4dea09c5530b/scratchpad/p_static.py, p_sizes.py, p_loop.py, p_notes.py, mk_srv.py`.
TEMPLATE server attacked on 127.0.0.1:18731 with a tower-written app.py + my own store.py; process killed afterwards.
Not run: any AI-written code under ~/.watchtower-runs (read only: run38 files and DB rows); Ollama; Docker (only `docker image inspect`).

Legend: [RUN] verified by running, [READ] verified by reading.

---

## HIGH

### H1. Under the skeleton the test file is written BEFORE store.py — the store then copies the tests' names (root cause of run 38)  [RUN + run38 artifacts]
- devfloor.py:195-204 `units()`: unit 1 = entry + test files, rest after. With the skeleton plan
  (skeleton.py:280-282: app.py, store.py, test_store.py) and app.py already written by the tower, `write_units`
  (devfloor.py:256-258) produces `[['test_store.py'], ['store.py']]` (probe p_static.py).
- run38 board: "coder unit 1/2 written: test_store.py", then "unit 2/2 written: store.py". test_store.py imported
  `get_items`; store.py followed the tests and defined `get_items` + a list named `items` — exactly the contract break
  7d now catches after the fact (costing F2 rounds / a send-back).
- Fix: when `self.owned`, order units store-first (store.py unit, then test_store.py), or write both in one unit; also
  put "def add(entry)" / "def items()" verbatim in the STORE_TESTS purpose ("tests call store.add(entry) and
  store.items()"), since the test writer never sees `_store_purpose`.

### H2. Owned mode: the tower's own hints tell the coder to write code its own checks then block  [RUN]
All three end as `problems` → f2_handoff blocks → send-back.
1. devfloor.py:353-355: "Your tests import nothing from the app … (e.g. from app import ...)". app.py is the tower's
   server; following the hint gives `test_store.py imports app: …` (store_problems). Probe p_notes.py.
2. lint.py:244-247 `idiom_notes`: for `global _entries` it recommends "`store._entries.clear()`"; skeleton.py:183
   flags any `._x` attribute → "test_store.py uses ._entries". Probe p_notes.py / p_static.py.
3. devfloor.py:473-474 → repair.py:155 `repair_imports` adds `import os`/`import tempfile`/`from urllib.parse import
   parse_qs` to store.py/test_store.py; same round, `_scan` reports "store.py imports os". The coder hears
   "Auto-repaired: added the missing `import os`" and "store.py imports os: …" together. `from html import escape`
   is also auto-added to store.py, endorsing the escaping STORE_NOTE forbids.
- Also: devfloor.py:347-350 "add test_*.py" / "name test files test_*.py" → any name but test_store.py is rejected.
- Fix: when owned, (1) say "import store in test_store.py"; (2) `idiom_notes` must not suggest underscore names, or
  `_scan` must allow `store._x` in STORE_TESTS; (3) pass the allowlist (SAFE / SAFE_TESTS) to `repair_imports` and
  only add allowed modules; (4) name test_store.py in the test notes.

---

## MEDIUM

### M1. store_problems false positives on ordinary code, with a message that gives no fix  [RUN]
skeleton.py:183-188. Each of these is rejected (probe p_static.py):
- `self._items = []` in a class-based store / `store._items.clear()` in tests → "uses ._items"
- `re.compile(...)` (BANNED has `compile`, checked as an attribute too) → "uses .compile"
- `__all__ = [...]` → "uses __all__"; `import tempfile` in test_store.py → "imports tempfile"
- The message "test_store.py … only keeps data in memory" is wrong for a test file, and none says what to use instead.
  Note: runs 32-38 used none of these (store/test files read), so it is latent, but it blocks handoff when hit.
- Fix: apply BANNED to attributes only for `__import__`/`exec`/`eval`/`open`/`compile` on non-`re` receivers (or
  drop attribute `compile`); allow single-underscore attributes, block only dunders; whitelist `__all__`; per-file
  message: "test_store.py may import only unittest, store, …: remove X".

### M2. F2 HR judges code it cannot see, in owned mode  [READ]
devfloor.py:394-404 / HR_PROMPT 108-112: HR is asked whether "the code meets the spec and follows the routes
contract", but the snapshot shows the server as a stub ("rest of the tower's web server not shown",
workspace.py:84-86) and the prompt never says the tower owns it. A plausible verdict "no HTTP routes" becomes
"Floor 2 HR … asked for changes" (devfloor.py:343) for a coder only allowed to write store.py, wastes up to
2 rounds, then `hr_question` reaches the gate as an open question. Probe p_loop.py shows the relay path.
- Fix: in owned mode use a store-only HR prompt ("does store.py keep entries as given and return them oldest first;
  do the tests test that?"), or skip HR.

### M3. Legacy mode: case-preserving disk turns the entry check into an endless loop  [RUN]
handoff.py:11 and tower.py:170 compare `entry not in files` exactly. If the coder once writes `App.py`, every later
write of `app.py` updates the same file but keeps the name `App.py` (macOS is case-preserving):
`ws.files() == ['App.py']` → "planned entry file app.py missing; create it" on every attempt until send-backs run out.
- Fix: compare case-folded (`entry.lower() in {f.lower() for f in files}`), and in `_write` rename to the planned case
  (delete then write) when a case-only match exists.

### M4. stdlib check uses the tower's 3.12 list; the sandbox runs Python 3.14  [READ + image env]
stdlib_check.py:32 `sys.stdlib_module_names` (3.12: `cgi` is stdlib) vs sandbox `python:latest` = PYTHON_VERSION 3.14.8
(config.py:28). `cgi`, `cgitb`, `imghdr`, `telnetlib`, `pipes`, `uu`, `audioop`, … were removed in 3.13: a 7B's
classic `cgi.FieldStorage` app passes F2 static checks and crashes in F3 with ModuleNotFoundError — a confusing
round trip. `python:latest` is also unpinned (next major silently changes behaviour).
- Fix: pin the sandbox image (e.g. python:3.12-slim matching the tower) or add a REMOVED_SINCE_313 set to
  import_problems with "cgi was removed in Python 3.13: use parse_qs".

### M5. Prompt budgets are not enforced where it matters  [RUN]
- PLAN_PROMPT (devfloor.py:226-233) has no budget: research is uncapped, feedback is cut to 600 chars *then*
  `untrusted` turns each `<` into `&lt;` (up to 4x). Probe: 12,511 chars.
- CODE_PROMPT (devfloor.py:301-304): notes are trimmed only down to one, then `room = max(1500, …)` forces 1,500
  chars of files even when over budget. `json.dumps(plan)` escapes non-ASCII as `\uXXXX` (6x; a Hindi/CJK purpose
  is 80 chars → 480). Probe with a 15-file non-ASCII plan: 14,127-14,560 chars vs PROMPT_CHARS 9,000.
  ASCII worst case ≈ 10.1k chars (spec 1k + plan 3.7k + QA 1.6k + one 2k note + 1.5k files).
- HR_PROMPT: snapshot(4500) + plan + spec, unbudgeted (~9k+).
- Owned mode stays at 9,019 chars (probe) — fine.
- With num_ctx 6144 and 2048 output, overflow makes Ollama drop the head of the prompt (the spec) silently.
- Fix: one `fit(template, parts, order_of_trim)` helper used by all four prompts; `ensure_ascii=False`; trim plan
  purposes / QA JSON before dropping the last note; cap research at ~1.5k; cap *after* escaping (as `_capped` does).

### M6. After an HR rejection, a garbled reply makes the package say PASS while the check says FAIL  [RUN]
devfloor.py:311-317 `continue` leaves `passed=True` from the earlier round. Probe p_loop.py: summary "Tests: PASS",
open_questions `[]`, last check `pass: False`, handoff "coder's own unit tests fail (advisory)", board "unit tests
still fail", and the owner's answer gains "the coder's own unit tests fail" — while the HR objection is lost entirely.
- Fix: on BadModelOutput set `passed = False` only if files changed (they did not), i.e. re-use the previous round's
  check result; if HR had objected and rounds run out, still set `hr_question`.

### M7. Renaming an invalid entry leaves the old planned file as a second "server"  [RUN]
devfloor.py:240-249: entry `my-app.py` → `fixed` is still invalid → entry `app.py`, but `my-app.py` stays in the plan
(probe: `['my-app.py', 'test_x.py', 'app.py']`). Units then write two server files; QA starts only app.py.
- Fix: when falling back to `app.py`, drop or rename the planned file whose path was the old entry.

---

## LOW

L1. skeleton.py:56-64 `show()` unescapes up to 5 times: a user who types `&amp;` or `&lt;b&gt;` sees `&` / `<b>`
(stored text altered on display). [RUN: POST `caf%C3%A9 %26amp%3B %26lt%3Bb%26gt%3B` → `café &amp; &lt;b&gt;`.]
Safe (escaped once), but not "as given". Fix: since 7c forbids store.py escaping and STORE_NOTE says so, show
`html.escape(str(text))` only, and let the F4 escape-once check catch a store that escapes (trade-off: run 33's
double-escape returns as a QA failure instead of being silently absorbed). Or accept and document.

L2. TEMPLATE HTTP robustness [RUN]: `timeout = 15` is per recv, so slowloris (1 byte/10 s) held a thread for 41 s+
(indefinitely); ThreadingHTTPServer spawns one thread per connection: 300 idle sockets → 301 threads. Bound to
127.0.0.1 (and the deploy edge publishes on 127.0.0.1 only), so local-only. Fix: a BoundedSemaphore in
`process_request` (e.g. 32) and a whole-request deadline.

L3. skeleton.py:69-70,123-124: store calls run under LOCK with no time limit: a slow `add` (my fixture: sleep 20)
made a concurrent GET wait 19.5 s [RUN]. Accident guard only; note it in OWNED_NOTE or time-box.

L4. skeleton.py:118: Content-Length 100 with 10 bytes sent → silent close after 15 s, no 400/408 [RUN].

L5. skeleton.py:33 `HERE = sys.path.pop(0)` assumes sys.path[0] is the script dir. Under `python -P` /
PYTHONSAFEPATH=1 it pops the stdlib zip entry and `import store` fails [READ]. Fix: compute HERE from `__file__`
(os is preloaded) and remove matching entries.

L6. devfloor.py:76-87 `test_summary` takes the FIRST `WATCHTOWER_TESTS` line; a test printing a fake one first wins
[RUN]. Advisory only (tests never block), but use the last match.

L7. skeleton.py:24-26 DANGER lacks `types`: `dataclasses.types` passes `_scan` [RUN] (CodeType/FunctionType reachable).
Ruled an accident guard, not a sandbox; listed for completeness.

L8. devfloor.py:305-306 test_first round 0 sets `notes = []`, dropping unit notes (format notes, "outside your unit",
auto-repair notes); devfloor.py:294 labels every unit note "Reviewer feedback to address" [READ].

L9. devfloor.py:323-366: `result.timed_out` is never told to the coder; it sees a cut output tail only [READ].
Fix: "the test run hit the 90 s limit: a test waits forever (serve_forever, input, sleep)".

L10. skeleton.py:251-257 `_fits` allows an entry named `test_*.py`: the tower's server is then discovered as a test
module and satisfies `has_tests` / `app_is_tested` by itself [READ]. Fix: reject `fnmatch(entry, "test*.py")`.

L11. feedback.py:63-72: subTest failures appear once per subtest (probe: `test_sub` twice) and eat the 5-row cap
[RUN]. Dedupe by (id, line).

L12. devfloor.py:441 silently drops files beyond 8 in a reply; devfloor.py:276 reports an in-unit DELETE as
"outside your unit" [READ].

L13. devfloor.py:406-426 `_link_entry` runs `repair_names` on the tower-owned entry every round and may rewrite it
(no-op today: the TEMPLATE has no unbound names [RUN]); skip when `entry in self.owned`.

L14. feedback.py:116-119 STUCK_NOTE tells a store-only coder to reset "a database file"; under 7c store.py must never
use files [READ].

L15. In owned mode, `_qa_block` still spends up to 1,500 chars on HTTP check JSON the coder cannot affect
(devfloor.py:259,295), incl. `expect_text` shown as `&lt;&>` [READ]. Replace with one line: "the server calls
add({'name': str, 'message': str}) and shows items() oldest first".

---

## Dead code / duplication
- skeleton.py:8 `PurePosixPath` unused (ruff F401).
- skeleton.py:16 SHADOWS: since 7c every path except store.py/test_store.py is rejected (devfloor.py:449), so the
  SHADOWS entries never decide anything; only `entry` in `owned` matters.
- handoff.py:23 `ITEM = 600` duplicates devfloor.FEEDBACK_ITEM (a test pins them equal instead of importing).
- devfloor.py:15-17 re-export block exists only so tests import feedback helpers via devfloor.
- Prompt sizing (`room = max(1500, min(6000, PROMPT_CHARS - len(...)))`) is duplicated at devfloor.py:267 and 304.
- ESCAPE_NOTE (devfloor.py:128) is reachable only in legacy mode; F4/F5 html.escape hints (qafloor.py:118-120,
  probe.py:117) cannot fire under the skeleton because show() always escapes once — correct, not contradictory.

## devfloor.py: the 500-line squeeze, and a real split
The file passes the rule by deleting blank lines (E305 at :88, missing separators at :131-132, 5 lines >120 chars,
:295 and :365 >140). `build()` is 91 lines with 11 loop variables and four exits. Proposed modules:
| module | contents | ~lines |
|---|---|---|
| `runner.py` | TEST_RUNNER, TEST_COMMAND, test_summary (last match) | 70 |
| `prompts.py` | PLAN/CODE/UNIT/HR/DIAGNOSE prompts, budgets, `_compact_checks`, `_qa_block`, `_spec_text`, one `fit_prompt()` | 90 |
| `planning.py` | `_plan_path`, `_SAFE_ENTRY`, `normalise_plan(raw)` (body of `plan()` after the ask), `units()` (store-first when owned) | 90 |
| `writer.py` | `FileWriter(ws, owned)`: one `allowed(path)` policy (strip, PurePosixPath, casefold), repair pipeline, `_ensure_packages`, `_link_entry` | 140 |
| `lint.py` (+) | `_is_test_file`, `app_is_tested` | +35 |
| `devfloor.py` | DevFloor.plan/write_units/build/_problems/_hr_review/_diagnose; `build` split into `_run_round()` and a pure `round_notes(result, problems, state) -> (notes, carry)` with a `RoundState` dataclass | ~200 |
Keep thin re-exports (or update the ~20 test imports listed by `grep "from watchtower.floors.f2_dev.devfloor import" tests`).

## Verified OK (briefly)
- Loop termination: build bounded by max_rounds; HR asks ≤2; diagnoses ≤2; repair loops bounded (MAX_REPAIRS,
  MAX_SPAN); `_capped` shrinks to empty; call-graph BFS in repair_main/lint terminates [READ].
- Repairs are idempotent (repair_imports twice, repair_strings twice: no change) and only run on writes the allowlist
  accepted; owned entry writes are rejected before any repair [RUN]. store_problems scans the repaired text, so a
  repair cannot hide a banned construct.
- Owned-file / allowlist enforcement: `./store.py`, ` store.py`, `store.py/` normalise to store.py; `Store.py`,
  `App.py`, `store/x.py`, deletes of the entry are rejected (case-folded) [READ].
- TEMPLATE: Location is a validated route path (qafloor `_PATH`: no CR/LF) → no header injection; negative / huge
  Content-Length → 413; chunked → 400; invalid UTF-8 → U+FFFD; TITLE with quotes/`</title>` is a repr literal and
  html-escaped [RUN]. items() result is copied inside LOCK.
- `_contract`: second def, async def, class, assignment, import, global, walrus, match, del, type alias all count as
  rebinding; deep nesting is a problem, not a crash [READ + existing tests].
- feedback.failures parses 3.10 and 3.12 unittest formats incl. docstring lines and subtests [RUN].
- Escape hints: STORE_NOTE replaces ESCAPE_NOTE when owned; `_store_purpose` agrees [READ].
