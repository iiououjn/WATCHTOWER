from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

ROLES_DIR = Path(__file__).parent
REQUIRED = ("id", "title", "floor", "tier", "prompt")


@dataclass(frozen=True)
class Role:
    id: str
    title: str
    floor: str
    tier: str
    tools: tuple[str, ...]
    prompt: str

    @property
    def system(self) -> str:
        return f"[role:{self.id}] {self.prompt.strip()}"


def load_roles(directory: Path = ROLES_DIR, tiers: Iterable[str] | None = None) -> dict[str, Role]:
    """Load every role YAML in a directory. The org chart is config, not code."""
    known_tiers = set(tiers) if tiers is not None else None
    roles: dict[str, Role] = {}
    for path in sorted(directory.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"{path.name}: role file must be a mapping")
        missing = [k for k in REQUIRED if not str(data.get(k) or "").strip()]
        if missing:
            raise ValueError(f"{path.name}: missing {', '.join(missing)}")
        if known_tiers is not None and data["tier"] not in known_tiers:
            raise ValueError(f"{path.name}: unknown tier {data['tier']!r}")
        if data["id"] in roles:
            raise ValueError(f"{path.name}: duplicate role id {data['id']!r}")
        roles[data["id"]] = Role(str(data["id"]), str(data["title"]), str(data["floor"]), str(data["tier"]),
                                 tuple(data.get("tools") or ()), str(data["prompt"]))
    return roles
