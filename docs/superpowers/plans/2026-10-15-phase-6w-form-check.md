# Phase 6w — The list page must offer a real form; fields classified by name parts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Run 25 (guestbook, job 5ec97d8c6271) reached owner sign-off: F3, the tower's F4 checks and the F5
scan passed. But the app serves `text/plain` with no `<form>`: a visitor cannot leave a message from a
browser. The tower checks POST directly, so they passed a form-less app — a false pass. Run 24 (todo) got no
tower checks at all: its field was `new_item`, not in the exact-name allow-list, so the 3B checks decided.

**Spec:** §5 F4 (tower contract checks, phase 6u).

## Critique, counters
1. **"Check for `<form` text."** Quotes, attribute order and casing vary. Counter: parse the page with
   `html.parser` inside the sandbox; require a POST form whose action path is the add route and whose
   inputs (input/textarea/select) carry every contract field name.
2. **"Some apps add with fetch()/JSON, not a form."** Not for a form-encoded POST contract with field names in
   a stdlib app; and the tower only decides for add-and-list contracts. Accepted.
3. **"Name parts are still a heuristic."** Yes, but conservative both ways: a field is text only when some
   part is a known text word and no part is a typed/id/choice word; else the models decide, as before 6u.

## Rulings
1. A check may carry `expect_form: {action, fields}` (validated: local path, 1–6 field names). QA_SCRIPT
   fails the check unless the page has a matching POST form; the detail names what it found.
2. Contract checks: `[tower] GET <list> has the add form` first; decide = 3 (form, POST, first value).
3. Field classification by `_`/camelCase parts (`new_item`, `user_name`, `messageText` text;
   `item_count`, `dueDate`, `todo_id` not).

## Review Focus
1. A form whose action is relative/absolute/empty (posts to itself), `method="POST"` uppercase, a form on a
   different page than the list, nested or unclosed forms, inputs outside any form.
2. QA_SCRIPT escapes and the parser's behaviour on huge or broken HTML (exceptions must not kill the run).
3. Whether any correct app from runs 18–25 would now fail (run 22's app: form on `/`, action `/add`).
4. Model-written checks carrying `expect_form`: harmless or exploitable?
