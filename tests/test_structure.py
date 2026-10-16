"""8d (audit E-S2, E-A3, A-F19): components nothing used are removed, with their dependencies, and stay removed."""
import dataclasses
import importlib.util
import tomllib
from pathlib import Path

import pytest

from watchtower.roles import ROLES_DIR, Role

ROOT = Path(__file__).resolve().parents[1]
REMOVED_MODULES = ["watchtower.engine.tools.hub", "watchtower.engine.tools", "watchtower.engine.governor.secrets",
                   "watchtower.engine.memory"]
REMOVED_DEPS = ["mcp", "keyring"]


@pytest.mark.parametrize("name", REMOVED_MODULES)
def test_removed_modules_stay_removed(name):
    try:
        assert importlib.util.find_spec(name) is None
    except ModuleNotFoundError:  # its parent package is gone too
        pass


@pytest.mark.parametrize("dep", REMOVED_DEPS)
def test_removed_dependencies_stay_removed(dep):
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert not [d for d in deps if d.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip() == dep]
    assert f'\nname = "{dep}"\n' not in (ROOT / "uv.lock").read_text()


def test_roles_carry_no_tool_permissions():  # the Tool Hub is deferred: a role has no tools to grant
    assert "tools" not in {f.name for f in dataclasses.fields(Role)}
    assert not [p.name for p in ROLES_DIR.rglob("*.yaml") if "\ntools:" in p.read_text()]


def test_every_model_tier_is_used_by_a_role():  # A-F19: a tier no role uses is config nobody reads
    from watchtower.config import DEFAULT_TIERS
    from watchtower.roles import load_roles
    used = {r.tier for r in load_roles(tiers=DEFAULT_TIERS).values()}
    assert set(DEFAULT_TIERS) == used
