# Phase 6t — QA text glued from page pieces; a board line that names failures

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Runs 18 (todo, job 4f995f1c4e27) and 19 (guestbook, job d85195126d2a) on 6s: all 8 attempts passed
F2 and F3 and reached F4 (6s worked). F4 failed every attempt. Two tower faults, one app fault:
- A QA check expected text glued from several page pieces: run 18 whole-page HTML
  (`<h1>Todo List</h1><ul>…`), run 19 entries joined by a newline (`Bob: Hi\nCharlie…`). Raw HTML never holds
  that exact string (tags, whitespace, order), so a correct app fails.
- The board and logs showed only "QA checks FAILED:" — the failing checks and why were invisible to the owner.
- (App, not tower) run 19's coder split the POST body by hand (`split('&name=')`): every add failed.

**Spec:** §5 (F4: HTTP checks from the spec, run in the sandbox).

## Critique, counters
1. **"Reduce glued text to its longest piece."** Weakens the check: after adding "milk", the piece "Todo List"
   passes a broken add. Counter: require *every* piece.
2. **"Pieces ignore markup, so a page escaping its own tags passes."** Counter: also fail when any of the
   expected tags appears escaped in the body (6p's rule kept).
3. **"Order matters for lists."** Rarely in the spec; order checks are not what the 7B means. Accepted.
4. **"Fix the coder's form parsing."** That is one more coder lint (whack-a-mole). Not in this phase; see
   the recommendation in the report (tower-provided app scaffold).

## Rulings
1. QA_SCRIPT: pass when the whole text matches (as before) or, for text with ≥2 pieces split on tags and
   newlines (real or written `\n`), every piece is shown (escape-tolerant) and no expected tag shows escaped.
2. `qa_headline(results)`: "QA checks FAILED (k/n): name: detail; …" ≤300 chars, used for the F4 board note.

## Review Focus
1. Comments or escapes inside the QA_SCRIPT string literal (two SyntaxErrors in history).
2. A single piece plus markup (`<li>milk</li>`) keeps 6p behaviour exactly.
3. Pieces that are empty or whitespace; a want of only tags; very many pieces.
4. qa_headline with names/details containing newlines or untrusted text (board is wrapped as untrusted?).
5. Forged WATCHTOWER_QA output is unchanged by this phase.
