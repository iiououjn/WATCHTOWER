from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

PACKAGED = Path(__file__).parent / "guardrails.yaml"
SEVERITIES = ("HIGH", "MEDIUM", "LOW")
MAX_FILE_BYTES = 64_000


class GuardrailsError(ValueError):
    pass


@dataclass(frozen=True)
class Guardrails:
    stdlib_only: bool
    security_fail_on: tuple[str, ...]
    min_source_domains: int
    max_send_backs: int
    rules: tuple[str, ...]


def _int(data: dict, key: str, low: int, high: int) -> int:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise GuardrailsError(f"guardrails: {key} must be a whole number from {low} to {high}")
    return value


def _parse(data, base: Guardrails | None) -> Guardrails:
    if data is None:  # an empty or fully commented-out file changes nothing
        data = {}
    if not isinstance(data, dict):
        raise GuardrailsError("guardrails: the file must be a mapping of settings")
    unknown = set(data) - set(Guardrails.__dataclass_fields__)
    if unknown:
        raise GuardrailsError(f"guardrails: unknown setting(s) {', '.join(sorted(map(str, unknown)))}")
    out = {}
    if "stdlib_only" in data:
        if not isinstance(data["stdlib_only"], bool):
            raise GuardrailsError("guardrails: stdlib_only must be true or false")
        out["stdlib_only"] = data["stdlib_only"]
    if "security_fail_on" in data:
        levels = data["security_fail_on"]
        if not isinstance(levels, list) or not all(isinstance(x, str) and x.upper() in SEVERITIES for x in levels):
            raise GuardrailsError(f"guardrails: security_fail_on must list some of {', '.join(SEVERITIES)}")
        # a minimum, not a pick-list: [LOW] means LOW and above; HIGH (secrets included) always fails
        lowest = max((SEVERITIES.index(x.upper()) for x in levels), default=0)
        out["security_fail_on"] = SEVERITIES[:lowest + 1]
    if "min_source_domains" in data:
        out["min_source_domains"] = _int(data, "min_source_domains", 0, 5)
    if "max_send_backs" in data:
        out["max_send_backs"] = _int(data, "max_send_backs", 1, 5)
    if "rules" in data:
        rules = data["rules"]
        if (not isinstance(rules, list) or len(rules) > 12
                or not all(isinstance(r, str) and 0 < len(r) <= 200 and r.isprintable() for r in rules)):
            raise GuardrailsError("guardrails: rules must be up to 12 lines of up to 200 characters")
        out["rules"] = tuple(rules)
    if base is None:
        missing = set(Guardrails.__dataclass_fields__) - set(out)
        if missing:
            raise GuardrailsError(f"guardrails: packaged file misses {', '.join(sorted(missing))}")
        return Guardrails(**out)
    return replace(base, **out)


def load_guardrails(home: Path | None) -> Guardrails:
    """The packaged guardrails, overridden key by key by the owner's copy in the tower home, if any."""
    base = _parse(yaml.safe_load(PACKAGED.read_text()), None)
    owner = home / "guardrails.yaml" if home is not None else None
    if owner is None or not os.path.lexists(owner):
        return base
    if not owner.is_file():  # a dangling link or a folder must not silently drop the owner's stricter rules
        raise GuardrailsError(f"guardrails: {owner} exists but is not a readable file")
    try:
        if owner.stat().st_size > MAX_FILE_BYTES:
            raise GuardrailsError(f"guardrails: {owner} is larger than {MAX_FILE_BYTES // 1000} KB")
        data = yaml.safe_load(owner.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError, RecursionError) as e:
        raise GuardrailsError(f"guardrails: cannot read {owner} ({type(e).__name__})") from e
    return _parse(data, base)
