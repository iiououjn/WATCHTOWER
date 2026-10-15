# Phase 6u — The tower writes the deciding QA checks from the routes contract

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Runs 18–21 (todo ×2, guestbook ×2, 16 attempts) all passed F2 and F3 and failed F4. 6t's board
line now shows why. The F4 checks are written by the **small tier (llama3.2:3b)** and are mostly unpassable:
- whole-document HTML: `'<html><body><h1>Todo List</h1></body></html>'` (run 20);
- an "empty list" check that runs after items were added (run 20);
- the architect's route description copied as page text: `'Guestbook form and all submitted messages'`
  (run 21; the copy filter missed it because the description ends with a period);
- placeholder text: `'Recent message goes here'` (run 21), unchanged across all 4 attempts.

Meanwhile the 7B architect wrote a clean routes contract in all 4 runs: `GET /` lists, `POST /add` or
`/submit` with `item` or `name`+`message`. The coder also hand-split form bodies in runs 19–20
(`split('=')[1]` → IndexError → RemoteDisconnected).

Option A said the tower owns the tests. 6s made the coder's tests advisory; this phase finishes it on F4.

**Spec:** §5 (F4: HTTP checks from the spec). Updated in Task 2.

## Critique, counters
1. **"Make QA use the 7B (work tier) instead."** Cheaper, but run 18's whole-page HTML came through as
   well, and every model swap costs RAM time on 8 GB. Counter: the deciding checks need no model.
2. **"Contract checks only test add-then-list; other specs need more."** True. Counter: model checks still
   run and reach the coder and the gate as advisory. The tower checks are the floor, not the ceiling.
3. **"A delete or toggle POST route would fail add-then-list."** Counter: skip POST routes whose path or
   fields look destructive (delete, remove, clear, done, toggle, edit, update, complete; a field named `id`
   or `*_id` or `index`). No eligible route → old rule (model checks decide).
4. **"Hand-split parsing passes a token like `wt123`."** Counter: each value has a space
   (`item k3f9a2`), so it travels as `item+k3f9a2`; hand-split apps fail and 6p's parse_qs hint fires.
5. **"Whack-a-mole again?"** No: this removes the 3B from the deciding path for every add-and-list app,
   whatever mistake it makes next.

## Rulings
1. `contract_checks(routes, token) -> list[dict]` (new `floors/f4_qa_deploy/contract.py`): for up to 2
   eligible POST routes with fields, one POST (each field = `"<field> <token>"`, expect 200), then for each
   field one GET of the list page (first GET route without fields, else `/`) expecting that value. Names start
   with `[tower] `. Normalised through `parse_checks`.
2. `run_qa(run, entry, checks, decide=0)`: when `decide > 0`, only the first `decide` checks decide; failing
   later checks are labelled `(advisory)` in the summary and counted in `checks_run[-1]["advisory_failed"]`.
   `decide == 0` keeps today's rule exactly.
3. Tower: the token is the job id's first 6 chars. The coder sees the tower checks first (test-first). When
   advisory checks fail but the tower checks pass, the gate gets a trusted Tower note saying so.
4. The description-copy filter ignores trailing punctuation.

## Review Focus
1. A routes contract with no POST, only destructive POSTs, a POST with no fields, or paths that 404.
2. `decide` with timed-out runs, forged/missing results, zero model checks, and names colliding with model
   checks (`[tower] …`).
3. The coder's first prompt: tower checks present, within the QA_CHARS budget.
4. An app that stores the value but renders it escaped (`&amp;`) or URL-encoded (`item+k3f9a2`).
5. Whether any app that failed F4 before can now pass with a broken add or list.

### Task 1: contract checks + description-copy fix
### Task 2: run_qa decide + tower wiring + spec row
### Task 3: two review rounds; real runs 22 (todo) and 23 (guestbook)
