# Phase 6y — The URL-encoded hint names the real mistake

**Goal:** Run 28 (job e0fd74af5b32, todo) failed F4 in 4/4 attempts: form and POST passed, but the list showed
"2409400+240940". The coder already used parse_qs, then wrapped the text in quote_plus() on save and display.
The tower's hint said only "decode form data with parse_qs", which it already did.

**Spec:** §5 (F4 feedback). No row change.

## Critique, counters
1. **"Add an F2 lint for quote_plus instead."** idiom_notes only reach the coder when its own tests fail
   (devfloor.py:360); run 28's did not. The F4 summary head always reaches it. Lint deferred unless it recurs.
2. **"Tell it html.escape: is that safe?"** Yes: escaped text renders the same; F4 already accepts escaped
   text (qafloor.py:56) and F5 probes XSS.
3. **Whack-a-mole?** It's a wording fix on an existing deterministic detector, not a new rule.

## Review rounds: 2 (small diff), opus.

## Scoreboard (hardening exit rule: >=3 of 4 runs pass across 2 prompts, then dashboard)
| run | prompt | result | floor | cause |
|---|---|---|---|---|
| 26 | todo | FAIL | F3/F4 | parse_qs NameError (fixed 6x) |
| 27 | guestbook | PASS (approved) | — | — |
| 28 | todo | FAIL | F4 | quote_plus on display (6y) |

## Deferred minors (r2)
- Hint always names quote_plus even for the %20 (quote) form.
- Encoded value split by tags, written as an entity, or only in textarea/input value: no hint.
