# Phase 6z — One tower check catches XSS, double escaping and URL-encoding

**Goal:** Run 30 (job ad4caca22e57, todo): 6y's hint fixed URL-encoding by attempt 4, then F5 found XSS with
no attempts left. Run 29 shipped text escaped three times. Problems surface one per attempt.

**Spec:** §5 (F4 tower checks), §9 (XSS). F5's XSS probe stays; this moves the signal to F4, earlier.

## Rulings
1. Contract add values are `"<token><i> <&> <token>"`; the list checks carry `expect_escaped: true`.
2. QA_SCRIPT: with `expect_escaped`, only `html.escape(want, quote=False)` on the page passes (no glued
   pieces). Hints: raw text on page -> "unescaped (XSS)"; escaped twice -> "escaped twice".
3. The coder sees checks via untrusted(), which shows `<` as `&lt;`: a trusted ESCAPE_NOTE after the block
   says what the check means.

## Critique, counters
1. **An app that rejects `<` (400) fails.** Accepted: a todo app should store any text.
2. **`.title()` apps:** symbols and digits survive case changes.
3. **Hand-split parsers** still fail (`%3C%26%3E`), and the URL-encoded hint still fires.

## Review rounds: 3 (security-relevant), opus. r2 and r3 run in parallel with different angles.

## Review Focus
1. Apps escaping with `quote=True` vs `False` (no quotes in value: same output).
2. Text inside `<textarea>`/attributes; JSON responses; apps that strip tags.
3. `split_ok` disabled only for escaped checks; model checks unchanged.
4. Coder prompt budget (QA_CHARS) with the note.

## Scoreboard
| run | prompt | result | floor | cause |
|---|---|---|---|---|
| 30 | todo | FAIL | F5 | XSS after 6y fixed encoding on attempt 4 (6z) |

## Review r1 (8 findings): fixed 1,3,4,5,6. Deferred minors:
- Attribute XSS untested (value has no quotes); F5 probe still covers it.
- Tag-stripping app fails with only the generic detail (no "stripped" hint).
- Coder prompt: untrusted() escaping runs after the QA_CHARS cap; 4+ fields can cut model checks.
