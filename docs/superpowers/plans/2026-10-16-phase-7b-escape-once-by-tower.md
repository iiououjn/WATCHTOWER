# Phase 7b: the tower escapes once, model checks judge status only

**Goal:** end the escape bug class (runs 28-33) by structure, not prompts, and stop a wrong model-written
check from failing a correct app (run 35).

**Spec:** docs/superpowers/specs/2026-10-12-watchtower-design.md. Evidence: 7a scoreboard
(docs/superpowers/plans/2026-10-16-phase-7a-server-skeleton.md), runs 26-35.

## Diagnosis (runs 26-35: 4 pass, 6 fail)

- 5 of 6 failures were HTML escaping, swinging between too little and too much: 28 (quote_plus), 29 (double),
  30/31 (raw XSS), 33 (double). Each phase (6y, 6z, 7a) added prompt text; a 7B cannot keep "escape exactly
  once, in the right place". 7a moved rendering into the tower but kept the "html.escape" hint, so the run-33
  coder escaped in store.py and the server escaped again.
- Run 35 (tip calculator, no tower checks): the model-written check expected wrong maths ($11.56; real
  12.10) in exact prose. A wrong check fails a correct app on every attempt.
- All 4 passes needed the owner over false gate objections (deferred: the owner sign-off is the safety).

## Changes

1. **Skeleton renders with `show(text)`**: unescape until stable (max 5), then `html.escape` once. Whatever
   store.py did (raw, escaped once, twice), the page shows the text escaped exactly once.
2. **Coder hint is skeleton-aware**: under the skeleton the escape note says store.py keeps text exactly as
   given (no html.escape, no quote); `_store_purpose` says the same.
3. **No tower checks (`decide == 0`)**: a model check that got its expected status but not its text passes
   as *advisory* (status only). Not for `expect_escaped`/`expect_form` checks. Evidence names the count.
4. **Release note for skeleton apps**: says the tower wrote the server, a local AI wrote store.py, and data
   lives in memory (lost when the app stops) — run 34's spec said "permanently".

## Critique, counters, rulings

- *Unescaping rewrites user data* (typing `&lt;` shows `<`). Counter: todo/guestbook text; the output is
  always escaped. Ruling: accept — cost if wrong: a literal entity a user typed displays decoded.
- *Single unescape misses double escape.* Ruling: loop to a fixed point, capped at 5 (bounded work).
- *AST-rewriting store.py instead.* Rejected: touches AI code, bigger, and model variants evade it.
- *Status-only lets a wrong-maths calculator pass F4.* Counter: today a wrong check fails a right app every
  time and the coder cannot fix the check. Owner still signs off; evidence says how many checks were status
  only. Real numeric checks need tower-written checks (later). Cost if wrong: one wrong app reaches sign-off
  labelled.
- *Model URL-encodes in store.py (run-28 style).* The tower's app.py decodes the form; the hint now says
  "no quote". Not covered further — accept.
- *`&amp;&amp;` in the approve output.* Not a tower bug: the stored sign-off has `&&`, `_clean` keeps it;
  the chat display escaped the pasted output. Dropped.
- *Spec still promises persistence.* Ruling: tell the owner in the release note, don't change F1 (F1 runs
  before the skeleton decision). Cost if wrong: the gate/CEO may still object; the owner reads the note.

- *Status-only also passed an app that escapes its own markup* (test_escaped_markup… went green). Ruling:
  echo checks (expected text contains a posted value with a letter, 3+ chars) keep gating; only computed
  text is advisory, and at least one check must fully pass. Cost if wrong: a wrong-count counter app passes
  F4 (test_qa_pieces now asserts the check's own row).
- *Found:* `test_separate_form_page_and_two_fields_pass` is vacuous — GUEST's `/sign` is "destructive", so
  zero tower checks. Deferred (7b's guestbook test uses `/add`).

## Stop rule

7b is the last reliability phase. Runs 36-39 (todo, guestbook, todo, tip calc). If every remaining failure is
model variance (not a tower bug), move to the dashboard (spec Phase 7) even below 3/4.

## Review Focus

1. `show()` on text with entities that never were escapes (`&copy;`, `&#x3c;`) — output must stay one level.
2. Probe text with `<script>` stored raw, once, twice, three times: one level, never raw.
3. Status-only softening must never pass a check whose status differs, a timed-out run, or an incomplete
   result set; never applies when `decide > 0`.
4. `expect_escaped` / `expect_form` model checks keep gating.
5. Release note wording only on skeleton apps; non-skeleton note unchanged.

## Tasks (TDD: RED first)

- [ ] T1 `tests/test_skeleton.py`: run-33 store (html.escape in add) and a double-escaping store pass every
      tower check → `skeleton.py` TEMPLATE `show()`; `_store_purpose` says "no html.escape".
- [ ] T2 `tests/test_devfloor.py`: `_qa_block(..., store_only=True)` gives the store note, not ESCAPE_NOTE →
      `devfloor.py` both call sites pass `bool(self.owned)`.
- [ ] T3 `tests/test_qafloor.py`: decide=0, status matches, text wrong → pass, advisory; status wrong → fail;
      `expect_escaped` → fail; decide>0 unchanged → `qafloor.run_qa`; `evidence.py` names status-only count.
- [ ] T4 `tests/test_skeleton.py` app_tower: answer says tower wrote the server and data is in memory →
      `tower.py` answer.
- [ ] Full suite, 3 opus review rounds (security render), merge `--no-ff`, tag `phase-7b`, runs 36-39.
