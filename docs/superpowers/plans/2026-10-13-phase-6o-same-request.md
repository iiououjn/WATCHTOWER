# Phase 6o — Checks that send the same request

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Real run 13 (job 2ebba1a76051, 2026-10-13): F2 and F3 passed, and F4 passed 3 of its 4 test-first checks.
Two of those checks sent the very same request (`POST /add_item` with `item=""`), but one expected "Welcome to Todo
List" and the other "Confirmation that the item has been added.". One response can pass both only by showing both
texts. Nothing said so: the coder saw one failure at a time and kept switching between the two texts.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` §5 (F4 QA).

## Global Constraints
- $0 local; deterministic; no new model calls. Nothing weakens a passable check (6g ruling). Tests first; two reviews.

## Critique of the first idea, and the counters
1. **"Drop the later check with the same request"** — texts that differ can both be on one page (GET / shows the title
   and the list), and dropping them weakens QA. Counter: keep both, and tell the coder that one response must show both.
2. **Different expected statuses for the same request** can never both pass. Counter: keep the first, drop the later
   one when the checks are parsed (the check can never pass, so dropping it weakens nothing).
3. **A stateful app** may answer the same request differently the second time (a duplicate add). Counter: the hint
   says "if both are right, show both texts" and keeps both checks, so a correct app can still pass.

## Rulings (after review 1)
0. No status drop: a stateful app may rightly answer GET /item/1 with 404, then 200 after a POST. Hint only.
1. Same request = same method, path and form (form compared as sorted key/value pairs).
2. The hint is added to the failing check's line, ≤ 120 chars, naming the other check.

## Review Focus
1. Forms with the same fields in a different order; the GET form `{}`; names with odd characters.
2. The status rule: _check already maps 3xx to 200 (redirects are followed), so only real differences (404 vs 200) conflict.

### Task 1: parse_checks drops same-request status conflicts; run_qa adds the same-request hint
### Task 2: two review rounds; real run 14.
