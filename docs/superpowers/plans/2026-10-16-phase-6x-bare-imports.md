# Phase 6x — The tower adds missing bare stdlib imports

**Goal:** Run 26 (todo): the coder used `parse_qs(...)` bare, never imported it, and got a NameError in all
4 attempts. `repair_imports` only handled `module.attr` uses (`os.path`), not bare names.

**Spec:** §5 (F2 static repair). No row change: same deterministic repair, wider reach.

## Critique, counters
1. **"Importing hides the coder's mistake."** It removes a plumbing error the 7B never fixed in 4 tries;
   the Auto-repaired note still tells the coder what was added.
2. **"A bare name may be the coder's own variable."** Only the names in `BARE` (parse_qs, parse_qsl,
   urlparse, escape, HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler) and only when bound nowhere
   in the file (assign, def, class, arg, import, star import) and used as a load.
3. **"`quote`/`unquote`/`dedent` too?"** No: ambiguous names stay out; add on evidence.
4. **"F3 HR said use parse_qsl for a NameError."** Model text; not changed here. With the import repaired the
   NameError no longer reaches F3. Deferred unless it recurs.

## Review Focus
1. Bare name bound by comprehension target, `with ... as`, `for` target, `except as`, walrus, match.
2. `from x import *` present; name used only as attribute/keyword.
3. Existing `import os` repair output and notes unchanged.
4. File with a syntax error: untouched.
