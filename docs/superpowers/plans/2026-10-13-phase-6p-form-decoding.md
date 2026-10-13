# Phase 6p — Form values shown still URL-encoded; escaped text counts as shown

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 14 (job 4980d30f9f6e, 2026-10-13): F2 and F3 passed, and F4 passed 2 of its 4 checks.
- `do_POST` read the body with `post_data.decode().split('=')[1]` and never URL-decoded it, so the page showed
  `New+todo+item`. The check "Todo List Updated" expected `New todo item`. The coder saw a page with the item on it and did not
  see the difference in 4 attempts.
- One more check ("Updated List") expected `'Test item Todo list'`, which no page would show. Under the 6g ruling, a
  bad check that keeps failing uses up the send-backs and the owner decides. Left as is.

Also seen while designing: an app that escapes correctly (`html.escape`, as the F5 XSS probe demands) fails a check
whose text has `&`, `<` or quotes, because QA compares raw HTML.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F4 QA), §9 (security: escape user text).

## Global Constraints
- $0 local; deterministic; no new model calls. QA_SCRIPT is the tower's own code running in the sandbox.
- Nothing weakens a check: escaped text renders as the same text in a browser. Tests first; two reviews.

## Critique of the first idea, and the counters
1. **"Lint `split('=')` in the code"** — many correct ways parse forms. Counter: QA sees the proof, the expected text
   still URL-encoded on the page (quote_plus or quote form), and says so first on the check's line.
2. **"Unescape the body before matching"** — that would also accept raw `<script>` text. Counter: accept the expected
   text OR its html.escape form (with or without quotes). The body is not changed.

## Review Focus
1. Short or plain expected text (no characters to encode): no hint. Text whose encoded form appears by chance.
2. Escaped matching with quotes (`&#x27;`, `&quot;`), and text that already contains entities.
3. The hint's length and its place in the coder's 600-char view.

### Task 1: QA_SCRIPT — escaped match and URL-encoded hint
### Task 2: two review rounds; real run 15.
