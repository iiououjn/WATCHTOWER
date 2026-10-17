<p align="center">
  <strong>🏗️ THE WATCHTOWER</strong><br>
  <em>A local-first agentic software factory — from idea to deployed app, on your machine.</em>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#tech-stack">Tech Stack</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#cli-reference">CLI</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#contributing">Contributing</a>
</p>

---

Watchtower is an **offline-capable, multi-agent pipeline** that turns a one-sentence idea into a running Python web app — researched, designed, coded, tested, security-scanned, and deployed — entirely on your local machine.

Every agent runs through local [Ollama](https://ollama.com) models (no API keys, no cloud, no data leaves your Mac). The agents themselves run in the tower's own process; the code they write runs only inside a sandboxed Docker container with no internet access. You stay in the loop at every critical decision point: approving the spec, signing off the final app, and deploying it.

## Tech stack

### Core runtime

| Technology | What it does in Watchtower |
|---|---|
| **Python 3.12+** | Runtime — the entire system is Python (type hints are documentation; no type checker runs) |
| **[Ollama](https://ollama.com)** | Local LLM inference server — runs all models on-device, no API keys |
| **[Docker](https://www.docker.com)** | Sandboxed code execution (no network, read-only mounts, tmpfs scratch) and isolated app deployment |
| **SQLite** | Job persistence, audit log, budget tracking, knowledge store — zero-config, single-file DB |

### LLM & agent layer

| Package | Role |
|---|---|
| **[LangGraph](https://github.com/langchain-ai/langgraph)** | Stateful agent graphs with checkpointed execution — used for the workflow engine |
| **[langgraph-checkpoint-sqlite](https://pypi.org/project/langgraph-checkpoint-sqlite/)** | SQLite-backed checkpointing so jobs can pause/resume across restarts |

### CLI & interface

| Package | Role |
|---|---|
| **[Typer](https://typer.tiangolo.com)** | CLI framework — all `watchtower` commands with auto-generated help |
| **[Click](https://click.palletsprojects.com)** | Installed with Typer; imported directly to catch Ctrl-C during CPO questions |
| **[three.js](https://threejs.org)** | The 3D dashboard (vendored, hash-pinned, MIT); plain JavaScript modules, no build step |

### Web research (Beacon subsystem)

| Package | Role |
|---|---|
| **[ddgs](https://pypi.org/project/ddgs/)** | DuckDuckGo search — privacy-respecting, no API key needed |
| **[httpx](https://www.python-httpx.org)** | HTTP client — fetches web pages, and is the tower's only model client: one `/api/chat` call to Ollama on loopback |
| **[trafilatura](https://trafilatura.readthedocs.io)** | Web content extraction — strips boilerplate, returns clean text from HTML |

### Security & safety

| Package | Role |
|---|---|
| **[Bandit](https://bandit.readthedocs.io)** | Offline static security analysis — scans agent-generated Python code for vulnerabilities |
| **[PyYAML](https://pyyaml.org)** | Parses `guardrails.yaml`, role definitions, and Glass domain rules |

### Testing

| Package | Role |
|---|---|
| **[pytest](https://docs.pytest.org)** | Test runner — all mocked to run without Ollama/Docker |
| **[Ruff](https://docs.astral.sh/ruff/)** | Lint — CI runs `ruff check` before the tests |

### Build system

| Tool | Role |
|---|---|
| **[Hatchling](https://hatch.pypa.io)** | PEP 517 build backend — builds the `watchtower` wheel |
| **[uv](https://docs.astral.sh/uv/)** | Fast Python package manager — resolves and installs deps in seconds |

### Default models

| Tier | Model | Used for |
|---|---|---|
| `small` | `llama3.2:3b` | Quick tasks and reviews — CPO questions, Glass relevance checks, QA check generation, the dev gate, audit, CEO/CTO |
| `work` | `qwen2.5-coder:7b` | Heavy lifting — architecture, coding and the spec gate (set `WATCHTOWER_WORK_MODEL=qwen2.5-coder:3b` for a cooler, weaker coder) |

> All models run locally via Ollama. Override the work model with `WATCHTOWER_WORK_MODEL=<model>`. The model client refuses any Ollama address that is not loopback, and no cloud client is built, so prompts never leave your machine.

## Quickstart

### Prerequisites

| Tool | Why |
|---|---|
| **Python 3.12+** | Runtime |
| **[Ollama](https://ollama.com)** | Local LLM inference |
| **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** | Sandboxed code execution & isolated deploy |
| **[uv](https://docs.astral.sh/uv/)** | Fast Python package manager (recommended) |

### Install

```bash
git clone https://github.com/rishiupadhyaygithub/watchtower.git
cd watchtower
uv sync          # or: pip install -e .
```

### Pull the default models

```bash
ollama pull llama3.2:3b
ollama pull qwen2.5-coder:7b   # ~4.7 GB; the 3b works too, but rarely passes its own tests
```

### Check everything is wired up

```bash
watchtower doctor
```

You should see all green `✓` checks for Ollama, Docker, RAM, Bandit, and Guardrails.

### Build an app

```bash
watchtower run "a pomodoro timer web app with dark mode"
```

Watchtower will:
1. **CPO** asks you clarifying questions
2. **Spec** is drafted and you approve it
3. **Floor 1** researches the topic (optional, with `--research`)
4. **Floor 2** architects and codes the app in a sandboxed workspace
5. **Floor 3** smoke-tests the app
6. **Floor 4** runs QA checks written from the spec
7. **Floor 5** runs a security scan (Bandit + secret detection), audits against the spec, and gates the release
8. **CTO** approves the technical plan; **CEO** recommends before your sign-off
9. **You** sign off, then optionally deploy

### Deploy it (isolated, no internet)

```bash
watchtower deploy <job-id>
# → http://127.0.0.1:<port>  (app has no internet, only reachable from your Mac)
```

## How it works

Watchtower is structured as a **five-floor tower** with a C-suite and a cross-floor communication bus:

```
┌─────────────────────────────────────────────────┐
│  OWNER (you)                                    │
│  approve spec · sign off app · deploy           │
├─────────────────────────────────────────────────┤
│  C-SUITE: CPO → CTO → CEO                      │
│  spec questions · tech plan approval · release  │
│  recommendation                                 │
├─────────────────────────────────────────────────┤
│  F5  OVERSIGHT          gate · security scan ·  │
│                         spec audit · retro      │
├─────────────────────────────────────────────────┤
│  F4  QA & DEPLOY        QA checks from spec ·   │
│                         isolated Docker deploy  │
├─────────────────────────────────────────────────┤
│  F3  BUILD              smoke test the app ·    │
│                         crash diagnosis         │
├─────────────────────────────────────────────────┤
│  F2  DEV                architect file plan ·   │
│                         coder writes code ·     │
│                         unit tests in sandbox   │
├─────────────────────────────────────────────────┤
│  F1  RESEARCH           web search · fetch ·    │
│                         Glass content filter    │
├─────────────────────────────────────────────────┤
│  ENGINE                 model socket · sandbox  │
│                         jobs · workflow · audit  │
│                         budget · knowledge · bus │
├─────────────────────────────────────────────────┤
│  BEACON                 search · fetch · Glass  │
│                         (prompt injection       │
│                          detection + filtering) │
└─────────────────────────────────────────────────┘
```

Each dev attempt runs F2 → F3 → F4 → F5 checks, then one **Floor 5 gate** (deterministic rules + one model review on the `small` tier); floor handoffs pass on each floor's own checks. A failure anywhere is sent back with feedback. The `guardrails.yaml` config controls gate rules, send-back limits, security severity thresholds, and more.

### Key safety layers

- **Glass** — Content filter on web-fetched pages: domain allow/deny lists, prompt-injection detection (regex + Cyrillic homoglyph normalization), secret scanning, and model-based relevance checks.
- **Sandbox** — All agent-written code runs in a locked-down Docker container with no network, read-only workspace mount, and 64 MB tmpfs scratch space. Agent code can never modify host files.
- **Guardrails** — Owner-editable `guardrails.yaml` enforced at every gate: stdlib-only constraint, security severity thresholds, minimum source domains, max send-backs.
- **Audit log** — Hash-chained, tamper-evident log of every action. Verify with `watchtower logs`.
- **Budget** — Per-job token, time, and cost limits.
- **Owner approval** — Spec approval and app sign-off are explicit human-in-the-loop checkpoints.

## The 3D dashboard

`watchtower dashboard` opens a live, read-only 3D view of the tower in your browser: **http://127.0.0.1:8765** (loopback only).
**Try it without installing anything:** the [hosted demo](https://rishiupadhyaygithub.github.io/watchtower/) plays a made-up run (no tower, no data behind it).

```bash
uv run watchtower dashboard            # default port 8765; --port N to change
```

**What you see.** A lighthouse on a sea rock, cut open towards you so each floor is a furnished office: penthouse C-suite,
F5 Oversight, F4 QA & Deploy, F3 Build, F2 Dev, F1 Research. Every agent from the org chart is a person in its floor's office.
When the tower wakes an agent it walks to its desk and types (name tag above its head); idle agents wander and sit. The floor with
live work lights up, a glowing packet rides the lift when a job moves between floors, the beam sweeps, deployed apps are boats
labelled `127.0.0.1:<port>`, and the "ground engine" cottage smokes when anything is working. The **Ledger** (top right) holds the
plain tables: approvals waiting for you, jobs, deployed apps, budgets and the audit log.

**Controls.** Drag to orbit, scroll to zoom, right-drag to pan, click a floor (or the floor buttons) to fly to it, hover a person for
their role. Bottom bar: pick a place (Scotland, Wales, Mumbai, Japan, Korea, USA, Dubai, open ocean), set the time of day or follow
your clock, toggle auto-orbit, glow and weather.

**Real photo backdrops.** The places are built in 3D (landmarks, physical sky, water, shadows), not photographs. For a true photo,
drop equirectangular panoramas (`.jpg`, `.png` or `.webp`, up to 30 MB and 8192 px wide, names like `tokyo-dawn.jpg`) into
`<home>/backdrops/` (default `~/.watchtower/backdrops/`); they appear as extra places and light the scene.

**How it works.** The server (`src/watchtower/dashboard/`, Python stdlib) is read-only: it opens the tower's SQLite file with
`mode=ro` + `query_only`, answers `GET`/`HEAD` only, checks the `Host` header against DNS rebinding, and sends a strict CSP. The page
polls `/api/state` every 3 s (cached 2 s server side) and the scene reacts: `web/app/` is plain JavaScript modules on a vendored,
hash-pinned [three.js](https://threejs.org) (MIT, `web/vendor/three/`), with no build step, no CDN and no runtime network. Text from the
tower (prompts, audit detail) only ever reaches the screen through `textContent` or canvas `fillText`.

**Not for the internet.** There is no login, and the page shows job prompts and audit entries. Keep it on loopback. To look at it from
another device, use a private tunnel you control (for example Tailscale) rather than a public URL. The public demo is safe only because
it contains no real data (`scripts/build_demo.py` builds it; `.github/workflows/pages.yml` publishes it).

## CLI reference

| Command | Description |
|---|---|
| `watchtower run "<idea>"` | Full pipeline: spec → all 5 floors → CEO → sign-off |
| `watchtower research "<topic>"` | Floor 1 only: spec → research brief with sources |
| `watchtower ask "<prompt>"` | Quick one-model Q&A (no floors) |
| `watchtower dashboard` | Live, read-only 3D view of the tower at http://127.0.0.1:8765 (`--port N`) |
| `watchtower approve <job-id>` | Approve a pending spec or sign off a finished app |
| `watchtower approve <job-id> --reject` | Reject a pending spec or app |
| `watchtower status` | List recent jobs |
| `watchtower logs [job-id]` | Audit log with hash-chain verification |
| `watchtower budget <job-id>` | Token / time / cost usage for a job |
| `watchtower pause <job-id>` | Pause a running job after its current step |
| `watchtower resume <job-id>` | Resume a paused job |
| `watchtower deploy <job-id>` | Deploy a finished, signed-off app to isolated local Docker |
| `watchtower rollback <name>` | Roll back to the previous deployment |
| `watchtower undeploy <name>` | Stop and remove a deployment |
| `watchtower deployments` | List all deployments |
| `watchtower beacon "<query>"` | Search the web and add pages to the knowledge store |
| `watchtower knowledge add <file>` | Add a local file to the knowledge store |
| `watchtower knowledge search "<q>"` | Full-text search the knowledge store |
| `watchtower doctor` | Health check: Ollama, Docker, RAM, Bandit, guardrails |

### Flags

| Flag | Used with | Description |
|---|---|---|
| `--yes` | `run`, `research` | Skip CPO questions, auto-approve the spec (you still sign off the app) |
| `--offline` | `run`, `research` | Don't search the web |
| `--research` | `run` | Have Floor 1 research the topic before dev |
| `--tier <t>` | `ask` | Model tier: `small`, `work` |
| `--max-tokens <n>` | `run`, `research`, `ask` | Override the default token budget |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `WATCHTOWER_HOME` | `~/.watchtower` | Data directory (DB, workspaces, guardrails) |
| `WATCHTOWER_WORK_MODEL` | `qwen2.5-coder:7b` | Override the `work` tier Ollama model |
| `WATCHTOWER_SANDBOX_IMAGE` | `python:3.14.8@sha256:b9767f…` | Docker image for sandbox and deploy; must be pinned by digest (`name[:tag]@sha256:…`) |
| `WATCHTOWER_MIN_FREE_RAM_PCT` | `20` | Minimum free RAM % before pausing |
| `WATCHTOWER_OFFLINE` | _(unset)_ | Set to `1` to disable web search |

## Architecture

```
src/watchtower/
├── tower/                # The tower: CPO spec → floors 1-5 → CEO → sign-off
│   ├── pipeline.py       # TowerPipeline — the workflow steps that tie the floors together
│   ├── spec_steps.py     # CPO questions, spec, approval, Floor 1
│   ├── dev_run.py        # DevRun — one app job's F2→F5 attempts
│   ├── memos.py          # The door every agent goes through; memo routing
│   ├── signoff.py        # Release text and owner sign-off
│   └── errors.py         # NeedsOwner, SpecRejected, AppRejected
├── config.py             # Settings & model tier resolution
├── guardrails.py         # Guardrails loader & enforcement
├── guardrails.yaml       # Default guardrails (copy to ~/.watchtower/ to customize)
├── interface/
│   ├── cli.py            # Typer CLI entry point — job commands
│   ├── shell.py          # The Typer app, DB opening, output cleaning
│   ├── checks.py         # doctor checks
│   ├── deploy_cmds.py    # deploy, rollback, undeploy, deployments
│   └── knowledge_cmds.py # knowledge add/search, beacon
├── beacon/               # Web research subsystem
│   ├── beacon.py         # Search → fetch → Glass → knowledge pipeline
│   ├── search.py         # DuckDuckGo search wrapper
│   ├── fetcher.py        # HTTP fetcher with trafilatura extraction
│   ├── glass.py          # Content filter: injection detection, secrets, relevance
│   ├── netguard.py       # Network-level URL filtering
│   └── glass_rules/      # Per-floor YAML allow/deny domain lists
├── engine/               # Core infrastructure
│   ├── model_socket.py   # One way to call a model: tiers, one model in RAM, retries, budget, JSON parsing
│   ├── ollama_client.py  # Direct httpx call to Ollama's /api/chat (loopback only)
│   ├── runner.py         # JobRunner — checkpointed workflow execution
│   ├── sandbox.py        # Docker sandbox for code execution
│   ├── workflow.py       # Step-based workflow with checkpointing
│   ├── jobs.py           # Job persistence (SQLite)
│   ├── bus.py            # Cross-floor event bus
│   ├── knowledge.py      # Full-text search knowledge store
│   ├── scheduler.py      # Agent slots (concurrency control)
│   ├── workspace.py      # Safe file I/O for agent workspaces
│   ├── system.py         # System health (RAM)
│   └── governor/         # Oversight subsystem
│       ├── audit.py      # Hash-chained audit log
│       ├── budget.py     # Token / time / cost budgets
│       └── approvals.py  # Human-in-the-loop approval flow
├── floors/               # The five floors
│   ├── framework.py      # WorkPackage, untrusted text wrapping, helpers
│   ├── board.py          # Tower notice board (cross-floor awareness)
│   ├── gate.py           # Gate reviewer (deterministic + model)
│   ├── f1_research/      # Floor 1: web research
│   ├── f2_dev/           # Floor 2: architecture + coding
│   ├── f3_build/         # Floor 3: smoke testing
│   ├── f4_qa_deploy/     # Floor 4: QA + Docker deploy
│   └── f5_oversight/     # Floor 5: security, audit, retrospective
├── csuite/               # Executive agents
│   ├── cpo.py            # Chief Product Officer (driven by tower/spec_steps.py)
│   ├── cto.py            # Chief Technology Officer
│   └── ceo.py            # Chief Executive Officer
└── roles/                # Agent role definitions (YAML config)
    ├── f1/ f2/ f3/ f4/ f5/
    ├── csuite/
    └── glass/
```

## Guardrails

Copy the default guardrails to customize them:

```bash
cp "$(python -c 'import watchtower; print(watchtower.__file__)'  | xargs dirname)/guardrails.yaml" \
   ~/.watchtower/guardrails.yaml
```

Then edit `~/.watchtower/guardrails.yaml`:

```yaml
stdlib_only: true                 # apps may import only the Python standard library
security_fail_on: [HIGH, MEDIUM]  # lowest severity that fails the build (Bandit + secret scan); HIGH always fails
min_source_domains: 2             # research needs sources from N independent sites
max_send_backs: 3                 # gate retries per floor before owner decides

rules:
  - "Spec match: output must satisfy the approved spec."
  - "Evidence: claims cite sources; code claims backed by passing checks."
  - "Safety: no secrets in code or logs."
  - "Budget: stay within token and time limits."
  - "Scope: files touched only inside the job's workspace."
```

## Running tests

```bash
uv run ruff check src tests # lint, as CI does
uv run pytest               # the whole suite
uv run pytest tests/ -x     # stop on first failure
```

## License

[MIT](LICENSE)
