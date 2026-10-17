"""`watchtower doctor`'s health checks; `docker_status` also gates an app job before any model work (8d: split out
of cli.py)."""
from __future__ import annotations

import yaml

from watchtower.config import Settings
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.sandbox import Sandbox
from watchtower.engine.system import free_ram_pct


def ollama_status(settings: Settings) -> tuple[bool, str]:
    from watchtower.engine import ollama_client  # review r1: the loopback client, never an environment proxy

    try:
        version = ollama_client.get(settings.ollama_url, "/api/version", timeout=3)["version"]
        names = {m["name"] for m in ollama_client.get(settings.ollama_url, "/api/tags", timeout=3)["models"]}
    except Exception:
        return False, "not reachable — open the Ollama app"
    missing = sorted({m.removeprefix("ollama/") for m in settings.tiers.values()} - names)
    if missing:
        return True, f"{version} · missing models: {', '.join(missing)} (ollama pull <name>)"
    return True, f"{version} · all tier models present"


def docker_status(settings: Settings, audit: AuditLog) -> tuple[bool, str]:
    problem = Sandbox(settings, audit).check()
    return (problem is None), (problem or f"ready ({settings.sandbox_image})")


def guardrails_status(settings: Settings) -> tuple[bool, str]:
    from watchtower.guardrails import GuardrailsError, load_guardrails
    try:
        g = load_guardrails(settings.home)
    except GuardrailsError as e:
        return False, str(e)
    owner = (settings.home / "guardrails.yaml").is_file()
    return True, f"{len(g.rules)} rules, {g.max_send_backs} send-backs ({'your copy' if owner else 'defaults'})"


def glass_status() -> tuple[bool, str]:
    """Every floor's glass rules file loads (a typo there would otherwise surface mid-job)."""
    from watchtower.beacon import glass as glass_mod
    for n in range(1, 6):
        try:
            glass_mod.load_glass_rules(f"f{n}", glass_mod.GLASS_DIR)
        except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
            return False, f"f{n}.yaml: {str(e)[:120]} (in {glass_mod.GLASS_DIR})"
    return True, "Glass 1–5 rules load"


def bandit_status() -> tuple[bool, str]:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return True, f"{version('bandit')} (offline security scanner)"
    except PackageNotFoundError:
        return False, "not installed; run: uv sync"


def doctor_checks(settings: Settings, audit: AuditLog) -> list[tuple[str, bool, str]]:
    """(name, ok, detail) for each engine part, in the order doctor prints them."""
    ram = free_ram_pct()
    return [
        ("Ollama", *ollama_status(settings)),
        ("Docker", *docker_status(settings, audit)),
        ("RAM", ram is None or ram >= settings.min_free_ram_pct,
         "unknown" if ram is None else f"{ram}% free (need {settings.min_free_ram_pct}%)"),
        ("Audit chain", audit.verify(), "ok" if audit.verify() else "BROKEN"),
        ("Bandit", *bandit_status()),
        ("Guardrails", *guardrails_status(settings)),
        ("Glass", *glass_status()),
    ]
