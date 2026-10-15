# Phase 7a — The tower writes the web server; the coder writes only the store

**Goal:** Todo failed 4 runs in a row (26, 28, 30, 31), each on different HTTP plumbing: a missing import,
quote_plus on display, XSS, items not shown. 6x/6y/6z each worked, but the coder fixes one thing per attempt
and runs out. For the add-and-list apps the tower already understands (contract_checks), the tower writes the
server itself; the 7B writes plain Python: `store.add(entry)` and `store.items()`.

**Spec:** §5 (F2 builds the app). F2–F5 checks unchanged; only who writes the server changes.

## Rulings
1. `skeleton.apply(plan, title, ws) -> (plan, owned)` in `floors/f2_dev/skeleton.py`. Applies only when
   contract_checks is non-empty AND every route is the list GET, the add-form GET, or the adding POST
   (a delete/toggle/detail route keeps today's path: no lost features).
2. The tower writes the entry (stdlib http.server): GET list page (form if same page) + items escaped once
   per field; GET form page; POST parse_qs -> 400 if a field is blank -> store.add -> 303 to the list page.
   Exceptions print a traceback (F4 app_error hints keep working) and return 500.
3. Plan files become: entry ("written by the tower"), `store.py` (add/items contract), `test_store.py`.
4. DevFloor refuses coder writes/deletes of owned paths with a note naming store.py.
5. Called at the end of `_approved_plan`, so a re-plan re-decides (owned cleared when not applicable).

## Critique, counters
1. **Overfit to add-and-list.** Yes, deliberately: only where the tower already writes the deciding checks.
   Everything else is unchanged.
2. **The coder overwrites app.py anyway.** Owned-path guard (ruling 4).
3. **Generic page look.** Title in <h1>; acceptable for MVP; spec extras route-gated (ruling 1).
4. **"The tower writes code: is that AI-written?"** No: it's a fixed tower template, tested on the host.
5. **Store returns strings, not dicts.** Template renders `str(item)` escaped.

## Review rounds: 3 (generates the server that faces user input), opus.

## Review Focus
1. Template: XSS in every output (title, field names, values, paths), 100KB body cap, blank fields, unicode.
2. Route gating: extra routes, form page == list page, add path == form page (GET+POST same path).
3. Owned guard: delete, case variants (App.py), ./app.py, path normalisation.
4. Re-plan to a non-skeleton plan; tower checks still pass against the template with a correct store.
5. Coder prompt: store contract visible in the first unit prompt.

## Reviews: r1 6 fixed; r2 (flow) 5 of 7 fixed; r3 (security) 5 of 6 fixed.
Deferred:
- No CSRF token / Host check (local app on 127.0.0.1; owner-only).
- Unit order: test_store.py is written before store.py (F2 rounds fix it).
- No cap on items rendered (memory bound only).
- F3 smoke test flake seen once in a full-suite run; did not reproduce.
