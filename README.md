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

Every agent runs through local [Ollama](https://ollama.com) models by default (no API keys, no cloud, no data leaves your Mac), inside a sandboxed Docker container with no internet access. You stay in the loop at every critical decision point: approving the spec, signing off the final app, and deploying it.

## Tech stack

### Core runtime

| Technology | What it does in Watchtower |
|---|---|
| **Python 3.12+** | Runtime — the entire system is Python, type-hinted throughout |
| **[Ollama](https://ollama.com)** | Local LLM inference server — runs all models on-device, no API keys |
| **[Docker](https://www.docker.com)** | Sandboxed code execution (no network, read-only mounts, tmpfs scratch) and isolated app deployment |
| **SQLite** | Job persistence, audit log, budget tracking, knowledge store — zero-config, single-file DB |

### LLM & agent layer

| Package | Role |
|---|---|
| **[LiteLLM](https://github.com/BerriAI/litellm)** | Unified LLM interface — wraps Ollama (and optionally cloud providers) with retries, JSON extraction, and token counting |
| **[LangGraph](https://github.com/langchain-ai/langgraph)** | Stateful agent graphs with checkpointed execution — used for the workflow engine |
| **[langgraph-checkpoint-sqlite](https://pypi.org/project/langgraph-checkpoint-sqlite/)** | SQLite-backed checkpointing so jobs can pause/resume across restarts |
| **[MCP](https://pypi.org/project/mcp/)** (Model Context Protocol) | Tool-use protocol — agents call tools through a standardized stdio interface |

### CLI & interface

| Package | Role |
|---|---|
| **[Typer](https://typer.tiangolo.com)** | CLI framework — all `watchtower` commands with auto-generated help |
| **[Click](https://click.palletsprojects.com)** | Typer's backend — used directly for prompt handling during CPO questions |

### Web research (Beacon subsystem)

| Package | Role |
|---|---|
| **[ddgs](https://pypi.org/project/ddgs/)** | DuckDuckGo search — privacy-respecting, no API key needed |
| **[httpx](https://www.python-httpx.org)** | Async-capable HTTP client — fetches web pages, talks to Ollama API |
| **[trafilatura](https://trafilatura.readthedocs.io)** | Web content extraction — strips boilerplate, returns clean text from HTML |

### Security & safety

| Package | Role |
|---|---|
| **[Bandit](https://bandit.readthedocs.io)** | Offline static security analysis — scans agent-generated Python code for vulnerabilities |
| **[Keyring](https://pypi.org/project/keyring/)** | OS keychain integration for any secret storage (no plaintext `.env` files) |
| **[PyYAML](https://pyyaml.org)** | Parses `guardrails.yaml`, role definitions, and Glass domain rules |

### Testing

| Package | Role |
|---|---|
| **[pytest](https://docs.pytest.org)** | Test runner — 40+ test files, all mocked to run without Ollama/Docker |

### Build system

| Tool | Role |
|---|---|
| **[Hatchling](https://hatch.pypa.io)** | PEP 517 build backend — builds the `watchtower` wheel |
| **[uv](https://docs.astral.sh/uv/)** | Fast Python package manager — resolves and installs deps in seconds |

### Default models

| Tier | Model | Used for |
|---|---|---|
| `small` | `llama3.2:3b` | Quick tasks — CPO questions, Glass relevance checks, gate reviews |
| `work` | `qwen2.5-coder:3b` | Heavy lifting — architecture, coding, QA check generation |
| `review` | `llama3.2:3b` | Audit, security review, CEO/CTO recommendations |

> All models run locally via Ollama. Override the work model with `WATCHTOWER_WORK_MODEL=<model>`. No data ever leaves your machine unless you explicitly enable cloud providers through LiteLLM.

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
ollama pull qwen2.5-coder:3b
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

Every floor handoff passes through a **Floor 5 gate** (deterministic rules + model review). If a gate rejects, work is sent back with feedback. The `guardrails.yaml` config controls gate rules, send-back limits, security severity thresholds, and more.

### Key safety layers

- **Glass** — Content filter on web-fetched pages: domain allow/deny lists, prompt-injection detection (regex + Cyrillic homoglyph normalization), secret scanning, and model-based relevance checks.
- **Sandbox** — All agent-written code runs in a locked-down Docker container with no network, read-only workspace mount, and 64 MB tmpfs scratch space. Agent code can never modify host files.
- **Guardrails** — Owner-editable `guardrails.yaml` enforced at every gate: stdlib-only constraint, security severity thresholds, minimum source domains, max send-backs.
- **Audit log** — Hash-chained, tamper-evident log of every action. Verify with `watchtower logs`.
- **Budget** — Per-job token, time, and cost limits.
- **Owner approval** — Spec approval and app sign-off are explicit human-in-the-loop checkpoints.

## CLI reference

| Command | Description |
|---|---|
| `watchtower run "<idea>"` | Full pipeline: spec → all 5 floors → CEO → sign-off |
| `watchtower research "<topic>"` | Floor 1 only: spec → research brief with sources |
| `watchtower ask "<prompt>"` | Quick one-model Q&A (no floors) |
| `watchtower approve <job-id>` | Approve a pending spec or sign off a finished app |
| `watchtower approve <job-id> --reject` | Reject a pending spec or app |
| `watchtower status` | List recent jobs |
| `watchtower logs [job-id]` | Audit log with hash-chain verification |
| `watchtower budget <job-id>` | Token / time / cost usage for a job |
| `watchtower pause <job-id>` | Pause a running job after its current step |
| `watchtower resume <job-id>` | Resume a paused job |
| `watchtower deploy <job-id>` | Deploy a finished app to isolated local Docker |
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
| `--yes` | `run`, `research` | Skip CPO questions, auto-approve spec and sign-off |
| `--offline` | `run`, `research` | Don't search the web |
| `--research` | `run` | Have Floor 1 research the topic before dev |
| `--tier <t>` | `ask` | Model tier: `small`, `work`, `review` |
| `--max-tokens <n>` | `run`, `research`, `ask` | Override the default token budget |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `WATCHTOWER_HOME` | `~/.watchtower` | Data directory (DB, workspaces, guardrails) |
| `WATCHTOWER_WORK_MODEL` | `qwen2.5-coder:3b` | Override the `work` tier Ollama model |
| `WATCHTOWER_SANDBOX_IMAGE` | `python:latest` | Docker image for sandbox execution |
| `WATCHTOWER_MIN_FREE_RAM_PCT` | `20` | Minimum free RAM % before pausing |
| `WATCHTOWER_OFFLINE` | _(unset)_ | Set to `1` to disable web search |

## Architecture

```
src/watchtower/
├── tower.py              # TowerPipeline — orchestrates all floors
├── config.py             # Settings & model tier resolution
├── guardrails.py         # Guardrails loader & enforcement
├── guardrails.yaml       # Default guardrails (copy to ~/.watchtower/ to customize)
├── interface/
│   └── cli.py            # Typer CLI — all user-facing commands
├── beacon/               # Web research subsystem
│   ├── beacon.py         # Search → fetch → Glass → knowledge pipeline
│   ├── search.py         # DuckDuckGo search wrapper
│   ├── fetcher.py        # HTTP fetcher with trafilatura extraction
│   ├── glass.py          # Content filter: injection detection, secrets, relevance
│   ├── netguard.py       # Network-level URL filtering
│   └── glass_rules/      # Per-floor YAML allow/deny domain lists
├── engine/               # Core infrastructure
│   ├── model_socket.py   # LiteLLM wrapper with retries, JSON extraction
│   ├── runner.py         # JobRunner — checkpointed workflow execution
│   ├── sandbox.py        # Docker sandbox for code execution
│   ├── workflow.py       # Step-based workflow with checkpointing
│   ├── jobs.py           # Job persistence (SQLite)
│   ├── bus.py            # Cross-floor event bus
│   ├── knowledge.py      # Full-text search knowledge store
│   ├── memory.py         # Context store for agent memory
│   ├── scheduler.py      # Concurrency control
│   ├── workspace.py      # Safe file I/O for agent workspaces
│   ├── system.py         # System health (RAM)
│   └── governor/         # Oversight subsystem
│       ├── audit.py      # Hash-chained audit log
│       ├── budget.py     # Token / time / cost budgets
│       ├── approvals.py  # Human-in-the-loop approval flow
│       └── secrets.py    # Secret detection patterns
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
│   ├── cpo.py            # Chief Product Officer (built into tower.py)
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
uv run pytest               # all 40+ test files
uv run pytest tests/ -x     # stop on first failure
```

## License

[MIT](LICENSE)
