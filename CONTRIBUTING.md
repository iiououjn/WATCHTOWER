# Contributing to Watchtower

Thanks for your interest in contributing! Here's how to get set up and the ground rules.

## Development setup

```bash
git clone https://github.com/rishiupadhyaygithub/watchtower.git
cd watchtower
uv sync --group dev       # installs runtime + dev deps (pytest)
```

You'll also need [Ollama](https://ollama.com) running with the default models pulled, and [Docker Desktop](https://www.docker.com/products/docker-desktop/) for the sandbox tests:

```bash
ollama pull llama3.2:3b
ollama pull qwen2.5-coder:3b
```

Verify with:

```bash
watchtower doctor
```

## Running tests

```bash
uv run pytest                # full suite
uv run pytest tests/ -x      # stop on first failure
uv run pytest tests/ -k gate # run only gate-related tests
```

Tests are designed to run without Ollama or Docker (they mock the model socket and sandbox), so the full suite should pass on any machine with Python 3.12+.

## Project structure

See the [Architecture section](README.md#architecture) in the README for a full source tree map.

Key conventions:
- **Roles are config, not code** — agent personas live in `src/watchtower/roles/` as YAML files.
- **Floors are self-contained** — each floor in `src/watchtower/floors/` owns its workers, office logic, and tests.
- **Engine is shared infrastructure** — model socket, sandbox, jobs, workflow, bus, audit, budget.
- **Beacon is the web research subsystem** — search, fetch, Glass content filter, knowledge store.

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(f2): architect generates a file plan before coding
fix(f5): stray files no longer block a signed-off release
docs: update quickstart with new CLI flags
chore: update .gitignore
```

Scopes: `f1`–`f5`, `cli`, `beacon`, `engine`, `roles`, `config`, `guardrails`, `csuite`, `deploy`.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Add tests for any new behavior.
3. Make sure `uv run pytest` passes.
4. Keep PRs focused — one feature or fix per PR.

## Code style

- Python 3.12+, type hints everywhere.
- No third-party imports inside agent-generated code (stdlib only by default, enforced by guardrails).
- Untrusted text (model output, web content) must be wrapped with `untrusted()` or `untrusted_code()` from `floors.framework`.

## Security

If you find a security vulnerability, please **do not** open a public issue. Instead, email the maintainer directly.
