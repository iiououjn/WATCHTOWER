# Phase 6v — When every tower check passes, the small gate's objection goes to the owner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Run 22 (todo, job b8dc06fb079b) built a correct app: parse_qs, html.escape, module-level list,
`__main__` start, even a remove button. It passed F3, the tower's F4 contract checks (2/2) and the F5 scan.
The F5 model gate (small tier, llama3.2:3b) rejected it on attempts 3–4 with "The user views all items in
the todo list." plus the tower's own advisory note echoed back. The coder cannot fix a phantom, so the
send-backs ran out. Run 23 (guestbook) was rejected correctly: the XSS probe found raw HTML.

**Spec:** §5 Gate ("one cross-family model gate then reviews the whole package"). Unchanged in kind: the
gate still reviews; this phase changes who settles a disagreement.

## Critique, counters
1. **"Move the gate to the 7B."** The spec wants it cross-family (the coder is qwen); the 3B llama is the
   only other family that fits 8 GB. Rejected.
2. **"Make the gate advisory."** Weakens a safety layer: tower checks cover only add-then-list. Rejected.
3. **Counter adopted:** when F3, the tower's deciding F4 checks and the F5 scan all pass and only the
   model objects, stop sending the app back. Finish the job with the CEO approve forced to False and the
   objection in the note, so sign-off goes to the owner even under `--yes`. A human settles it.
4. **"Then a junk objection costs the owner a look."** Yes: that is the price; it is one look, not four
   wasted attempts and a pause with no app.

## Rulings
1. `model_objection(verdict, package, f3, f4, sec) -> list[str]` (in `watchtower/evidence.py`): the gate's
   reasons when the verdict failed, the package itself validates, and F3, F4 (with tower checks deciding)
   and F5 all passed; else []. Without tower checks (decide == 0) nothing changes.
2. The objection is posted to the board, written into the CEO note ("F5 gate (small model) objected though
   every tower check passed: …; the owner decides") and forces `approve: False`.
3. `tower.py` helpers moved to `watchtower/evidence.py` first (495 → 438 lines), re-exported.

## Review Focus
1. Any path where a real failure (F3/F4/F5 fail, validate problems) is turned into an escalation.
2. Under `--yes`, the job pauses for owner sign-off with the objection visible; nothing is released before.
3. Retro/lessons and the gate.verdict event still record the rejection honestly.
4. Apps without tower checks keep today's send-back loop exactly.
5. Objection text is model output: wrapped/capped wherever it reaches the owner or other agents.
