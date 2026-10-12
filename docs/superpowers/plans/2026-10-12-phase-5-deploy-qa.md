# Phase 5 — Floor 4 Deploy + QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every app that passes Floor 3 also passes black-box QA checks written from the spec by an independent model, is recorded as a release (file hashes), and the owner can deploy it to local Docker — isolated, no internet, localhost only — with health check and rollback.

**Architecture:** `qafloor.py` (QA role writes HTTP checks → deterministic runner in the sandbox) plugs into the existing `_dev` send-back loop after the smoke test. On gate pass, `releases.py` stores a sha256 manifest of the files. Deploying is a separate owner command (`watchtower deploy <job>`): `deploy.py` copies the manifest-verified files plus a fixed launcher into a temp build context, `docker build --network none`, runs the app on an `--internal` network (no egress) and a fixed edge proxy that publishes `127.0.0.1:<port>`. Failed health check → automatic rollback to the slot's previous image.

**Tech Stack:** Python 3.12 stdlib, docker CLI, SQLite migration, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-watchtower-design.md` (F4 row: "Playwright E2E pass; health check; rollback ready. Default deploy target: local Docker. Vercel optional").

## Global Constraints

- $0, local only; no new downloads (uses existing `python:latest` image; `--pull never` / `--pull=false`).
- Files < 500 lines; read before edit; no Co-Authored-By trailer; no secrets committed.
- AI-written code never runs on the host and never gets internet: sandbox `--network none`; deploy on `--internal` network.
- Published port binds `127.0.0.1` only.
- All model-derived text reaching another model is `untrusted(...)`-wrapped; all model-derived values reaching docker/HTTP are validated.

## Rulings vs spec (recorded in ledger)

1. Playwright → stdlib HTTP checks (form POST + GET + text match). Apps are stdlib server-rendered; Playwright image ≈1.5 GB + Chromium RAM on 8 GB Mac. Cost if wrong: JS-only behaviour untested; add Playwright later as opt-in.
2. Deploy is an owner command, not a pipeline step: no long-lived container starts without the owner asking.
3. Vercel deferred (needs token + publishing approval; outside $0-local scope now).

## Review Focus

1. QA model returns hostile/odd checks (absolute URLs, `..`, huge forms, non-int status) → dropped by `parse_checks`, never reach the runner unvalidated.
2. Workspace files changed after QA (resume, manual edit) → deploy refuses: manifest mismatch.
3. Health check fails on redeploy → previous release restored automatically, slot never left empty when a previous one existed.
4. Deploy name / port collisions and docker failures (build error, port in use) → clean error, no orphan containers/networks.
5. App binds 127.0.0.1 (coder rule) → still reachable through launcher forwarder.

---

### Task 1: QA floor (role + check parser + sandbox runner)

**Files:**
- Create: `src/watchtower/roles/f4_qa.yaml`, `src/watchtower/engine/qafloor.py`
- Test: `tests/test_qafloor.py`, `tests/test_roles.py` (cross-family assertion)

**Interfaces:**
- Produces: `parse_checks(raw) -> list[dict]` (each `{"name","method","path","form","expect_status","expect_text"}`), `QA_SCRIPT: str`, `run_qa(run, entry, checks) -> WorkPackage` (floor `"f4"`, one check entry `{"check":"qa","pass":bool,"results":[...]}`), `QAFloor(role, ask).write_checks(spec, snapshot) -> list[dict]` (raises `BadModelOutput` when no usable checks).

Rules for `parse_checks`: max 8 checks; method in {GET, POST}; path matches `^/[A-Za-z0-9_\-./?=&%+]*$`, ≤200 chars, no `..`, no `//`; form only for POST, dict of ≤10 str→str, keys ≤50, values ≤200; `expect_status` int 100–599 (default 200; bad → 200); `expect_text` str ≤200 (default ""); name ≤80 (default path).

QA_SCRIPT (runs in the sandbox, args: entry, checks-JSON): start app like `SMOKE_SCRIPT` (PORT 8000, log to /tmp/app.log, new session), wait ready (≤10 s), run checks in order with `urllib` (POST form urlencoded, redirects followed, 3 s timeout, read ≤200 KB, HTTPError → its code + body), compare status and `expect_text in body`, kill process group, print `WATCHTOWER_QA <json list of {name,pass,status,detail}>` then log tail.

`run_qa` parses the last `WATCHTOWER_QA` line; missing/garbled → single failing result `"QA runner produced no result"`. Pass = every result passes and not timed out.

- [ ] Step 1: tests — parse_checks drops absolute URL, `..`, `//`, bad method, form on GET, oversize; coerces bad status; caps 8. run_qa with fake run: all-pass, one fail, garbled output, timed_out. QAFloor raises BadModelOutput on zero checks; snapshot reaches QA prompt wrapped untrusted. Real-python test: execute QA_SCRIPT locally in tmp dir against a tiny stdlib app (POST /add then GET / contains item) — proves the script itself works.
- [ ] Step 2: run → FAIL (module missing).
- [ ] Step 3: implement.
- [ ] Step 4: run → PASS; full suite green.
- [ ] Step 5: commit `feat(qa): Floor 4 QA checks written from spec, run in sandbox`.

### Task 2: Releases + pipeline integration

**Files:**
- Modify: `src/watchtower/engine/db.py` (migration 5), `src/watchtower/engine/pipeline.py`, `src/watchtower/engine/runner.py` (role map if needed), `tests/conftest.py` (FakeSandbox QA reply, APP_REPLIES f4.qa)
- Create: `src/watchtower/engine/releases.py`
- Test: `tests/test_releases.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: Task 1 `QAFloor`, `run_qa`.
- Produces: `Releases(conn).record(job_id, entry, root) -> None`, `.get(job_id) -> Release | None` (`job_id, entry, manifest: dict[str,str], created_at`), `.verify(job_id, root) -> list[str]` (problems: missing/extra/changed files).

Migration 5:
```sql
CREATE TABLE releases(job_id TEXT PRIMARY KEY, entry TEXT NOT NULL, manifest TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE deployments(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, job_id TEXT NOT NULL,
  image TEXT NOT NULL, port INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, ended_at TEXT);
```

Pipeline `_dev`: after smoke passes, `checks = qa.write_checks(spec, ws.snapshot())`, `f4 = run_qa(run, entry, checks)`; package checks = dev + smoke + qa (qa last, so the reality rule sees it); summary appends QA results. On QA fail feedback to coder includes `untrusted("sandbox", f4.summary)`. On gate pass: `Releases.record(...)`, bus `app.released`, answer adds `Deploy it (isolated, no internet): watchtower deploy <job>`.

- [ ] Step 1: tests — record/verify (changed, missing, extra file); app pipeline runs QA after smoke and records release; QA failure routes to coder with QA detail, gate model not called; answer mentions `watchtower deploy`.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS + suite. Step 5: commit `feat(f4): QA in the dev loop and release manifests`.

### Task 3: Deployer

**Files:**
- Create: `src/watchtower/engine/deploy.py`
- Test: `tests/test_deploy.py`

**Interfaces:**
- Consumes: `Releases`, `Settings.sandbox_image`, `AuditLog`.
- Produces: `Deployer(settings, conn, audit, run=subprocess.run, health=http_ok, port_free=_port_free)` with `.deploy(job_id, name="app") -> Deployment`, `.rollback(name) -> Deployment`, `.undeploy(name) -> None`, `.list() -> list[Deployment]`; `DeployError(Exception)`.

Behaviour:
- `name` matches `[a-z0-9][a-z0-9-]{0,29}`; job must have a release and `verify()` must be empty, else `DeployError`.
- Build context in a temp dir: manifest files copied from workspace, `wt_launcher.py` (fixed: start entry with PORT=8000 exactly as QA did; forward 0.0.0.0:9000 → 127.0.0.1:8000), Dockerfile:
  `FROM <image>` / `COPY --chown=1000:1000 . /app` / `WORKDIR /app` / `USER 1000:1000` / `ENV PYTHONDONTWRITEBYTECODE=1` / `CMD ["python","wt_launcher.py","<entry>"]`.
- `docker build --pull=false --network none -q -t wt-app-<name>:<deploy_id> <ctx>`.
- Port: reuse slot's last port, else first free in 8100–8199 (`port_free`).
- Start: `docker network create --internal wt-dep-<name>` (ignore "already exists"), app container `wt-dep-<name>-app` (`--network wt-dep-<name> --network-alias app --read-only --tmpfs /tmp:rw,size=64m --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m --cpus 1 --restart unless-stopped`), edge `wt-dep-<name>-edge` from base image running fixed proxy code (`--read-only --cap-drop ALL --user 1000:1000 --memory 64m -p 127.0.0.1:<port>:8000 --restart unless-stopped`), then `docker network connect wt-dep-<name> wt-dep-<name>-edge`; edge forwards its :8000 → app:9000.
- Before starting: `docker rm -f` both containers of the slot (old ones), keep old image.
- Health: `health(port)` true within ~10 s → status `active`, previous active → `replaced`. False → new row `failed`, containers removed, previous release restarted (status back to `active`), raise `DeployError("health check failed; rolled back to deployment N")` (or "nothing to roll back to").
- `rollback(name)`: latest `replaced` row → restart its image, current → `rolled_back`.
- `undeploy(name)`: rm containers + network; active → `stopped`.
- Prune: keep newest 3 images per slot (`docker rmi` older, ignore errors).
- Every docker failure → `DeployError` with first stderr line; audit `deploy_*` events (no file contents).

- [ ] Step 1: tests with a recording fake `run` (argv list) — happy path argv contains `--internal`, `127.0.0.1:<port>:8000`, `--network none` on build, no `-p` on app container; manifest mismatch refused; bad name refused; health fail rolls back to previous; first-deploy health fail cleans up; rollback/undeploy statuses; build failure → DeployError and no `docker run`. Real-python test: launcher forwards to an app bound on 127.0.0.1.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS + suite. Step 5: commit `feat(deploy): isolated local Docker deploy with health check and rollback`.

### Task 4: CLI

**Files:**
- Modify: `src/watchtower/cli.py` (deploy, rollback, undeploy, deployments; `job_created` audit logs the real pipeline)
- Test: `tests/test_cli.py`

- [ ] Step 1: tests — `deploy` on unknown/undone job exits 2 with message; success prints URL `http://127.0.0.1:<port>`; `deployments` lists rows; DeployError → exit 1 with cleaned message.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS + suite. Step 5: commit `feat(cli): deploy, rollback, undeploy, deployments`.

### Task 5: Real cross-check on the Mac

- [ ] Known-good todo app workspace + release → real `Deployer.deploy` → curl 127.0.0.1:port 200; app has no egress; redeploy with broken app → auto rollback; `undeploy` leaves no containers/networks. Real QA_SCRIPT in real sandbox against the same app.
- [ ] Ledger results; final fresh review (opus); fix Important; report.
