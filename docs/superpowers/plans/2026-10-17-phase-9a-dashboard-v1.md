# Phase 9a: Dashboard v1 (read-only lighthouse)

Spec: `docs/superpowers/specs/2026-10-12-watchtower-design.md` §Dashboard (deferred, now built in a smaller form).
Branch `phase-9a-dashboard`, tag `phase-9a-dashboard`.

## Goal
`watchtower dashboard` serves one local page that shows the tower live: a lighthouse with F1 at the bottom and F5 at the
top, the ground-engine strip under it, the job list, the approval queue, the audit log and the budget meters.
**Read-only.** No button changes any state. Approving stays in the CLI until v2.

## Scope
In: stdlib `http.server`, 127.0.0.1 only, JSON state endpoint, one HTML page that polls it every 3 s, a CLI command.
Out (v2, phase 9b): approve/reject buttons, login, CSRF, starting jobs, WebSocket, Next.js/FastAPI from the spec.

## Critique of the first idea, with counters and rulings
| Critique | Counter | Ruling |
|---|---|---|
| Spec says Next.js + FastAPI + WebSocket. | 8 GB Mac, `next start` costs 0.2 GB + a Node build; adds deps and attack surface for a read-only page. | Stdlib server, polling. Spec marks the stack as deferred; note it in the spec. |
| A dashboard shows model/app text: XSS. | Model output, spec text and audit `detail` are untrusted. | Page code never uses `innerHTML` with data: `textContent` only. Server also escapes in any HTML it builds. Strict CSP with a per-response nonce, `connect-src 'self'`. |
| DNS rebinding: a web page could read localhost. | Binding to 127.0.0.1 does not stop a browser tab reaching it through a rebinding name. | Reject any `Host` that is not `127.0.0.1:<port>` or `localhost:<port>` with 403. |
| A read-only page can still change the DB if the connection is writable. | A bug or a crafted path could write. | Open SQLite with `file:...?mode=ro` (uri) and `PRAGMA query_only=ON`. GET/HEAD only; every other method gets 405. |
| It could leak secrets or paths. | Audit detail can hold paths and app logs. | Reuse `clean()` (control and bidi characters). Cap every string at 2000 chars. Paths under the home folder are shown as `~/...`. No env, no tokens, no Colab URL. |
| Polling hammers SQLite on an 8 GB machine. | 3 s with a few small queries is nothing. | Fixed queries, `LIMIT`, no per-request writes, WAL readers do not block the tower. |
| "Which floor is a job on?" is not stored. | Audit has `floor` in `board.note` and `gate.verdict`; `agent.wake`/`agent.idle` carry the agent. | Derive: latest audit entry with a `floor` field = current floor; job status gives the state. Unknown floor shows the job as "planning". |
| Binding other hosts "for the phone". | Opens the tower to the LAN with no login. | `--host` is not offered. Only loopback. Remote view is a v2 question. |
| Port clash. | | Default 8765; `--port` option; clear error if busy. |

## Files (each under 500 lines)
- `src/watchtower/dashboard/data.py`: read-only queries that return plain dicts (`state(conn) -> dict`).
- `src/watchtower/dashboard/page.py`: the HTML/CSS/JS template (string constants; JS uses `textContent` only).
- `src/watchtower/dashboard/server.py`: `make_server(db_path, port)`, handler, Host check, headers.
- `src/watchtower/interface/dashboard_cmds.py`: `watchtower dashboard [--port]`, registered like `deploy_cmds`.
- `tests/test_dashboard.py` (+ `tests/test_dashboard_security.py` if over the line limit).

## State shape (`GET /api/state`)
`{"jobs":[{id,status,prompt,floor,error,updated_at,attempt?}], "approvals":[{id,job_id,kind,summary,created_at}],
"audit":[{seq,ts,job_id,actor,action,detail}], "budgets":[{job_id,used_tokens,max_tokens,used_seconds,max_seconds}],
"chain_ok":bool, "agents_awake":[...], "now":"..."}` with `LIMIT 20` jobs, 50 audit rows, pending approvals only.

## Tasks (TDD, RED first)
1. `data.state()` on a seeded temp DB: lists jobs, pending approvals, last audit rows, budgets, floor derivation,
   string cap, `~` path shortening, `chain_ok` false on a tampered chain. The connection is read-only: an INSERT through
   it raises.
2. `server`: `/api/state` JSON 200; `/` HTML 200; unknown path 404; POST/PUT/DELETE 405; bad Host 403; headers
   (`Content-Security-Policy` with nonce, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`,
   `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`); binds 127.0.0.1 only; HEAD works; busy port gives a clear error.
3. `page`: the template contains no `innerHTML`/`outerHTML`/`document.write`/`eval`/`insertAdjacentHTML`; script tag carries
   the nonce; a seeded job with `<script>alert(1)</script>` as its prompt never appears unescaped in any server output.
4. CLI: `watchtower dashboard --port N` starts the server in a thread in a test, answers `/api/state`, and refuses
   `--host`. Printing the URL only.
5. Real check: run it against `~/.watchtower-runs/run40`, open it in the browser pane, and screenshot.

## Review Focus (for the Opus reviewer; security, so 3 rounds)
- Any path where model, spec, audit or app-log text reaches the page without `textContent`/escaping.
- Host-header and DNS-rebinding handling, including `Host` with a port, uppercase, IPv6 `[::1]`, and missing.
- Any write path to the DB (the read-only URI, `query_only`, no `executescript`).
- Information the page could show that the CLI does not (secrets, env, full paths, the Colab URL or token).
- Behaviour with a missing/locked/empty DB, a huge audit table, and a non-UTF-8 or 1 MB `detail`.
- Slow-client / many-connection exhaustion of a threaded server (timeouts, daemon threads).

## Done when
Tests green, ruff clean, 3 review rounds with no Critical/Important left, merged `--no-ff`, tagged, one real screenshot.
