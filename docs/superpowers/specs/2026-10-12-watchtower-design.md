# THE WATCHTOWER — Master Design Spec

- **Date:** 2026-10-12
- **Owner:** Rishi
- **Status:** Draft, awaiting owner review
- **Type:** Architectural (master spec; each build phase gets its own spec → plan → build)

---

## 1. Intent

### What the owner said
- A full agentic ecosystem shaped like a lighthouse: a Ground Engine, five working floors, and a rotating Beacon with five Glass layers on top.
- Floors: F1 Research, F2 Development, F3 Build (MVP → full app), F4 Deploy + QA, F5 Oversight (cross-checks all floors against guardrails).
- Ground Engine powers and connects everything: models, connectors, MCPs, RAG, ML, memory.
- Beacon scans the internet for what is needed, filters out what is not, detects threats, and acts as the tower's NLP layer.
- Each Glass layer protects its floor from bogus or hallucinated input.
- Each floor works like an office: employees, team leads, managers, HR (orchestrator), C-suite.
- "Break" = agents are not all active at once; idle agents do no work. Context is never lost; it is saved to the Engine.
- Produces all kinds of work: web, mobile, CLI, API, ML, and non-software (research, plans, content).
- Personal project first (alongside Dip, Closet, Maps-for-flats); may become SaaS or open source later.
- Security, multi-user readiness, and interface quality must be SaaS-grade from day one.
- Runs locally on the owner's Mac first, hybrid cloud later.
- Must cost $0 to run. Paid models are optional, never required.

### Success criteria
1. The owner runs `watchtower run "<idea>"` on their Mac and the tower carries a **simple web app** (e.g. todo/notes app) through spec → research → dev → build → deploy/QA → oversight, with $0 spend, on local models only. Complex apps require larger hardware or optional cloud models.
2. Every floor handoff is gated by F5 Oversight; failed work is sent back, not restarted.
3. No web content can act as an instruction to any agent.
4. A crash or model-limit pause never loses work; jobs resume from the last checkpoint.
5. The owner sees and controls everything from a CLI and a live lighthouse dashboard.

### Assumptions (owner may correct)
- v1 targets web apps end to end; other output types are added later as toolkits.
- Owner is the sole user in v1, but auth and data model are multi-user ready.

---

## 2. Constraints

| Constraint | Value | Design impact |
|---|---|---|
| Hardware | Apple M2, **8 GB RAM**, ~64 GB free disk | One local model loaded at a time; small models (~3–4B); deterministic checks before LLM checks |
| Budget | **$0** by default | Local models via Ollama; free self-hosted search; paid providers off by default with hard caps |
| Available paid options | Anthropic API credits (~$100–200), Claude Pro plan | Optional plug-ins only; never required |
| Installed tools | Ollama, Docker, Claude Code, Node 25, Python 3.10 | Used directly; Python ≥3.11 recommended for the Engine (to install) |
| Runtime | Local Mac first → hybrid cloud → SaaS | All infra behind swappable adapters |

### RAM budget (8 GB)

| Component | Budget | Rule |
|---|---|---|
| macOS + apps | ~3–4 GB | Reserved |
| Ollama model | ~2.5 GB | One model loaded at a time; unload when idle |
| Docker (Sandbox; SearXNG optional) | ~1.5–2 GB | Started on demand, stopped when idle; Colima as lighter alternative to Docker Desktop |
| Engine (Python, SQLite, Chroma) | ~0.5 GB | Always on |
| Dashboard | ~0.2 GB | Production build only (`next start`), never dev mode while jobs run |

The Governor monitors free memory and defers starting a component that would exceed the budget. Search uses DuckDuckGo (no Docker); a SearXNG container is optional.

**Honest expectation:** on 8 GB with local models only, the tower works but produces simpler apps slowly. Quality scales with better hardware (swap in larger local models) or optional cloud models, with zero code changes.

---

## 3. Architecture overview

```
Owner ─▶ CLI / Dashboard  (FastAPI + WebSocket ⇄ Engine)
              │
        [Step 0: CPO writes spec ⇄ asks Owner questions]
              │
 Beacon ─▶ Glass1 ─▶ F1 Research   ─▶ ✓Gate
           Glass2 ─▶ F2 Dev        ─▶ ✓Gate   ◀── fail = send back (max 3), then Owner decides
           Glass3 ─▶ F3 Build      ─▶ ✓Gate
           Glass4 ─▶ F4 Deploy/QA  ─▶ ✓Gate
           Glass5 ─▶ F5 Oversight  (runs every ✓Gate + final audit)
              │
 ═════════════ GROUND ENGINE (under and around everything) ═════════════
```

Code layout mirrors the lighthouse:

```
src/watchtower/
  engine/      Ground Engine (model_socket, memory, knowledge, bus, scheduler, workflow, sandbox,
               workspace, tools/, governor/, db, jobs, runner)
  beacon/      Beacon (search, fetcher, netguard) + glass.py with per-floor rules in glass_rules/
  floors/      framework (work package, untrusted wrappers), gate, board,
               f1_research/ f2_dev/ f3_build/ f4_qa_deploy/ f5_oversight/  (each floor's office + tools)
  roles/       role YAML per floor: f1/ f2/ f3/ f4/ f5/ csuite/ glass/
  tower.py     wires the floors, gates, approvals and sign-off into the job workflow
  interface/   CLI (API + dashboard later)
```

Job lifecycle: `draft → spec_approved → F1 → F2 → F3 → F4 → final_audit → owner_signoff → done`, with backward transitions allowed on gate failure (bounded by retry limits).

---

## 4. Ground Engine

A single Python service on the Mac. Nine modules, each with one job and a narrow interface.

| Module | Responsibility | v1 implementation | Swap path |
|---|---|---|---|
| **Model Socket** | Single interface to any LLM; routes by task tier; enforces one-local-model-in-RAM | LiteLLM + Ollama | Add Claude/Gemini/etc. via config |
| **Memory** | Agent context save/restore on idle; long-term memory; post-job lessons | SQLite | Postgres |
| **Knowledge (RAG)** | Searchable store of Beacon findings and project files | SQLite FTS5 (BM25) with provenance; vectors later via Ollama embeddings (Chroma dropped: RAM) | pgvector / managed vector DB |
| **Bus** | Messages and events between floors/agents/UI | Topics written to the audit log (one ordered, tamper-evident stream any process can read) | Redis |
| **Scheduler** | Wakes/idles agents; concurrency limit across processes; pause/resume | Custom module (file-lock slots) | Distributed workers |
| **Workflow** | Floor-to-floor job graph, gates, send-backs, checkpoints | LangGraph + SQLite checkpointer | Postgres checkpointer |
| **Tool Hub** | MCP servers and tools (fs, git, browser, shell) with per-floor permissions | MCP client | Same |
| **Sandbox** | All agent-executed code runs isolated, never on owner's real files | Docker | Cloud runners |
| **Governor** | Budgets (tokens/time/$), approval queue, secrets, append-only audit log | SQLite + macOS Keychain | Postgres + cloud secret manager |

### Model tiers (default config, all local, $0)
- **tier-small** (glass filters, summarizing, classifying): ~3B local model (e.g. Llama 3.2 3B / Qwen 2.5 3B).
- **tier-work** (coding, planning): best local model that fits RAM — Qwen2.5-Coder 7B by default (the only local coder whose apps passed their own tests on 8 GB); the 3B is the cooler fallback (`WATCHTOWER_WORK_MODEL`). The model is unloaded before each Sandbox run when free RAM is low.
- **tier-review** (F5): a *different model family* from tier-work, loaded sequentially.
- **tier-cloud** (optional, off): Claude / Gemini / others. Requires owner approval and a per-job $ cap.
- **Free-tier privacy rule:** providers that may train on prompts never receive private code or secrets; the Glass layers enforce this.

### Crash safety
Every step writes a checkpoint. On crash or restart, the Scheduler resumes each job from its last good checkpoint. Health check endpoint + auto-restart (launchd in v1).

---

## 5. Floor framework (shared by every floor)

- **Roles as config:** each role is a YAML file — name, model tier, allowed tools, prompt, output schema. The org chart changes without code changes.
- **Per floor:** 1 **Lead** (plans, splits work), N **Workers** (execute tasks), 1 **HR** (in-floor quality and process check before handoff).
- **Tower-wide C-suite:** **CPO** (turns the owner's prompt into a spec via clarifying questions; an app spec carries 3–6 testable acceptance criteria — one re-ask when thin, then marked tower defaults), **CTO** (approves tech choices), **CEO** (final recommendation; the owner signs off). All report to the **Owner**.
- **HR vs F5:** HR checks quality *inside* one floor. F5 checks *across* floors plus guardrails and security.
- **Idle agents ("breaks"):** agents exist only when the Scheduler assigns a task. On completion they persist context to Memory and go idle (no compute, no tokens). Concurrency default = 1 active thinking agent (8 GB limit), configurable.
- **Work package (handoff contract):** structured output of each floor — `summary`, `artifacts` (files), `sources`, `checks_run` + results, `open_questions`. Validated against a schema; invalid packages are rejected.
- **Gate:** F5 evaluates each package → `pass` or `send_back(reasons)`. Every floor handoff (F2→F3→F4→F5) gets a deterministic F5 gate (the floor's own reality checks, recorded as gate events); one cross-family model gate then reviews the whole package against the spec and guardrails. Max send-backs come from `guardrails.yaml` (default 3), then escalate to Owner.

---

## 6. The five floors (v1 = web apps)

| Floor | Input → Output | Objective checks (reality first) |
|---|---|---|
| **F1 Research** | Spec → research brief | Every claim has a source link; sources passed Glass 1 |
| **F2 Dev** | Brief → architecture + code. Architect (Lead) plans files + a routes contract (CTO approves) and the plan is split into coder units (MVP unit first: entry + tests); Coder workers write one unit each, then fix in a loop driven by real Sandbox test output; Dev HR reviews the integrated code | Unit tests pass in Sandbox (runner's own summary, ≥2 real tests, and a test imports the app itself); standard-library-only check |
| **F3 Build** | Code → MVP → full app | MVP: app runs in Sandbox and GET / answers 200 (Build Lead's home-page text is a soft check); full app: probe workers GET every route of the contract (no 404/5xx/silence); Build HR diagnoses failures for the coder |
| **F4 Deploy/QA** | App → deployed + QA report | QA model (other family) writes HTTP acceptance checks, run in Sandbox; pass → release (file hashes). Owner runs `watchtower deploy`: local Docker, internal network (no internet), 127.0.0.1 only, CSP edge; health check; auto-rollback. Playwright later (opt-in, ~1.5 GB). Vercel (free plan) later, owner-approved, token from Keychain |
| **F5 Oversight** | Every package → verdict | `guardrails.yaml`; Bandit + secret patterns (offline; serious findings fail); HTML-injection probe in the Sandbox (a harmless tag posted into every form must never come back raw); Spec Auditor; cross-family model gate; retrospective lessons; CEO recommendation → owner sign-off before any release |

**Coding engine:** the Coder agent writes complete files through the checked Workspace writer and is driven by real Sandbox test results (a tool-using loop). Aider was dropped: an extra process and RAM on 8 GB, and the loop already gets real test output.

**Guardrails:** an owner-editable policy file (`guardrails.yaml`, packaged defaults; the owner's copy in `~/.watchtower/` overrides key by key) that F5 enforces at every gate. v1 rules:
- **Spec match:** output must satisfy the approved spec's acceptance criteria; no unrequested features.
- **Evidence:** claims cite sources; code claims backed by passing checks.
- **Safety:** no secrets in code or logs; no disallowed licenses in dependencies; no actions outside the role's tool permissions.
- **Budget:** within the job's token/time/$ limits.
- **Scope:** files touched only inside the job's workspace.

Each rule maps to a deterministic check where possible, and to a tier-review model judgment only where not.

**Toolkits:** output-type specific tool bundles plugged into F2–F4. v1 ships the **web toolkit**. Later: mobile (simulators; store publishing needs paid accounts and owner approval), CLI, API, ML, docs.

**Learning:** after each job, F5 writes a short retrospective to Memory; future jobs retrieve relevant lessons.

---

## 7. Beacon + Glass layers

### Beacon (two sides)
- **Search side:** targeted search on floor request via DuckDuckGo (free, no Docker); SearXNG (self-hosted) optional later + page fetch/extract.
- **Watch side:** scheduled watch list (security advisories for used dependencies, library releases). Not a continuous full-internet crawl.
- All results stored in Knowledge (RAG) with provenance (URL, fetch time, hash).

### Quarantine rule
All web content is labeled **untrusted data**. It is never executed or followed as instructions. Instruction-like text is stripped or flagged before any agent sees it.

### Glass layers (one per floor)
Pipeline, cheapest checks first:
1. **Deterministic:** domain allow/deny lists, schema/format checks, regex injection patterns, secret detection.
2. **Relevance filter** against the floor's current task (tier-small).
3. **Source credibility** scoring.
4. **Independent corroboration:** a factual claim passes only with **2+ independent sources on different domains**.
5. **Consistency check** against Knowledge (flags contradictions; Knowledge is never treated as proof, since the Beacon filled it).

Each glass has floor-specific rules in `beacon/glass_rules/fN.yaml` (owner-editable): Glass 1 open web with a deny list; Glass 2 technical docs and API references; Glass 3 docs + Q&A for crash causes; Glass 4 HTTP references; Glass 5 security references (allow-lists). Credibility (step 3) is by rule: listed/allow-listed sites and .gov/.edu rank first and are marked; low-credibility domains are rejected. Corroboration (step 4) applies to F1 research claims. Consistency (step 5): at most one model check per task against a page from another site; a contradiction becomes a note for the floor, never a reject. Floors 2–5 ask the Beacon through their own glass only with `--research`, at most twice per floor per job, with code-built queries that carry no app data (F3 sends only the exception kind and known phrases); a lookup returns only pages its own glass passed in that lookup, never another floor's cached pages. A floor's reference may be handed on as fix guidance (F3's to Build HR, F4/F5's to the coder), always wrapped and labelled with the glass it came through. Rejected content is logged with a reason, never silently dropped.

---

## 8. Interface

- **API:** FastAPI (REST) + WebSocket for live events.
- **CLI:** `watchtower run "<idea>"` (whole tower), `research "<topic>"` (Floor 1 brief), `ask` (one model), `status`, `approve <id>`, `pause`, `resume`, `logs`, `budget`, `deploy`/`rollback`/`undeploy`/`deployments`, `doctor`, `knowledge`, `beacon`.
- **Dashboard (Next.js, localhost):** animated lighthouse — floors light when active, agents shown working/idle, beacon rotates while searching. Panels: approval queue, job timeline, work packages, audit log, budget meters.
- **Auth from day one:** local login; data model has `user` and `workspace` scoping so multi-user/SaaS needs no schema rewrite.

---

## 9. Security

- Sandbox for all agent code execution; owner's files are mounted read-only and only when allowed.
- Per-floor, per-role tool permissions (least privilege).
- Secrets in macOS Keychain; agents receive scoped handles, never raw values in prompts.
- Web content quarantine + injection scan (Glass).
- **Owner approval required** for: deploy outside local Docker, deleting anything outside the Sandbox, any paid model spend, publishing, network calls to new domains from build code.
- Append-only audit log of every agent action, tool call, and decision.

## 10. Error handling

- Retries with exponential backoff for transient failures.
- Checkpoint resume after crash.
- Model limit / rate limit → job pauses, resumes automatically when available.
- Budget exhausted → hard stop, owner notified.
- Gate retry limit hit or ambiguity → escalate to Owner via approval queue.

## 11. Testing

- Unit tests per Engine module.
- Contract tests on work-package schemas.
- Golden jobs (e.g. "build a todo app") as end-to-end tests.
- Red-team suite: prompt-injection pages fed to Beacon/Glass must be blocked.
- Load check: tower stays within 8 GB RAM during a golden job.

---

## 12. Build phases

Each phase gets its own spec → plan → implementation cycle.

1. **Ground Engine**, split into three sub-phases:
   - **1a:** Model Socket + Memory + Governor (budgets, audit log, Keychain) + CLI skeleton
   - **1b:** Scheduler + Bus + Workflow checkpoints (pause/resume)
   - **1c:** Sandbox + Tool Hub (MCP) + Knowledge (RAG)
2. **Floor framework** + Gate + C-suite (CPO spec step).
3. **Beacon + Glass + F1 Research** → first real output (research brief).
4. **F2 → F3 → F4** with the web toolkit.
5. **F5 Oversight** complete (security scans, cross-family review, retrospectives).
6. **Dashboard** (lighthouse UI, approvals, audit).
7. More toolkits → hybrid cloud (adapters) → SaaS / open source.

## 13. Out of scope for v1

- Non-web toolkits (mobile, ML, CLI, docs).
- Cloud deployment of the tower itself.
- Multiple concurrent human users (data model is ready; UI/ops are not).
- Paid app-store publishing.
